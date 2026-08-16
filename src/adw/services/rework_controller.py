"""The Rework Controller — D11, I5.

Turns a FAIL verdict into a bounded, visible, counted retry. Failure is a
first-class path here, never an invisible loop: every attempt is a row, so
`DESIGN.md` §12.1 can render "Rework 2 of 3" from the record rather than from a
guess.

At three attempts the task stops and goes to a human. A task failing its gate
three times is not a retry problem — it is a signal that the plan, the
definition, or the input is wrong, and D11 exists to make somebody look.

Does **not** decide why something failed, modify artifacts, bypass a gate, or
retry transient infrastructure errors, which are a different mechanism at the
tool layer.
"""

from __future__ import annotations

from typing import Final

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from adw.domain.errors import DomainError
from adw.domain.states import GateVerdict, TaskState
from adw.models.gate import MAX_REWORK_ATTEMPTS, GateDecision, ReworkAttempt
from adw.models.task import Task
from adw.ports.keystore import KeyStore
from adw.services import audit_writer, task_service

EVENT_REWORK_OPENED: Final = "task.rework_opened"
EVENT_REWORK_EXHAUSTED: Final = "task.rework_exhausted"


class NotAFailureError(DomainError):
    """Rework was requested for a verdict that did not fail."""


def attempts_used(session: Session, task: Task) -> int:
    count = session.execute(
        select(func.count()).select_from(ReworkAttempt).where(ReworkAttempt.task_id == task.id)
    ).scalar_one()
    return int(count)


def open_rework(
    session: Session,
    *,
    task: Task,
    decision: GateDecision,
    keystore: KeyStore,
    actor_id: str,
) -> ReworkAttempt | None:
    """Record a rework attempt and return the task to the queue.

    Returns the attempt, or ``None`` when the budget is exhausted — in which case
    the task is moved to ``blocked`` for a human decision rather than retried.

    Raises:
        NotAFailureError: if the verdict was not a FAIL.
    """
    if decision.verdict is not GateVerdict.FAIL:
        msg = f"cannot open rework for a {decision.verdict.value!r} verdict"
        raise NotAFailureError(msg)

    used = attempts_used(session, task)
    if used >= MAX_REWORK_ATTEMPTS:
        # ARCHITECTURE.md §5.8 routes exhaustion through REWORKING:
        # AwaitingGate -> Reworking -> Blocked. There is no edge straight from a
        # gate to blocked, and the record should show the task did re-enter
        # rework before a human was asked to look.
        task_service.transition(
            session, task, TaskState.REWORKING, keystore=keystore, actor_id=actor_id
        )
        task_service.transition(
            session, task, TaskState.BLOCKED, keystore=keystore, actor_id=actor_id
        )
        audit_writer.append(
            session,
            tenant_id=task.tenant_id,
            event_type=EVENT_REWORK_EXHAUSTED,
            actor_id=actor_id,
            payload={
                "task_id": str(task.id),
                "attempts_used": used,
                "limit": MAX_REWORK_ATTEMPTS,
                "triggering_gate_decision_id": str(decision.id),
            },
            keystore=keystore,
        )
        return None

    attempt = ReworkAttempt(
        tenant_id=task.tenant_id,
        task_id=task.id,
        attempt_no=used + 1,
        triggering_gate_decision_id=decision.id,
        failure_detail=decision.failure_detail or "gate failed without detail",
    )
    session.add(attempt)
    # The task's attempt counter mirrors the rework rows rather than being
    # incremented independently. One budget, one authority: the rows are the
    # record, and D11 is counted from them.
    task.attempt_no = attempt.attempt_no + 1
    session.flush()

    audit_writer.append(
        session,
        tenant_id=task.tenant_id,
        event_type=EVENT_REWORK_OPENED,
        actor_id=actor_id,
        payload={
            "task_id": str(task.id),
            "attempt_no": attempt.attempt_no,
            "of": MAX_REWORK_ATTEMPTS,
            "triggering_gate_decision_id": str(decision.id),
            "failure_detail": attempt.failure_detail,
        },
        keystore=keystore,
    )

    task_service.transition(
        session, task, TaskState.REWORKING, keystore=keystore, actor_id=actor_id
    )
    task_service.transition(session, task, TaskState.QUEUED, keystore=keystore, actor_id=actor_id)
    return attempt
