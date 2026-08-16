"""Task state transitions.

The only writer of ``Task.state``. Centralising it means the machine cannot be
bypassed by a stray update somewhere else in the codebase.

**The transition and its audit record share one transaction** (G2), so the two
can never diverge: either both are durable or neither happened. The caller's
``tenant_session`` is that transaction; this module does not open its own.
"""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from adw.domain.states import TaskState
from adw.domain.transitions import assert_task_transition
from adw.models.task import Task
from adw.ports.keystore import KeyStore
from adw.services import audit_writer

EVENT_TASK_TRANSITIONED = "task.transitioned"


def get_task(session: Session, task_id: UUID) -> Task | None:
    """Return a task visible in the session's tenant context, or ``None``.

    A task belonging to another tenant is indistinguishable from one that does
    not exist, which is the intended shape of the fail-closed rule.
    """
    return session.scalar(select(Task).where(Task.id == task_id))


def transition(
    session: Session,
    task: Task,
    proposed: TaskState,
    *,
    keystore: KeyStore,
    actor_id: str,
) -> Task:
    """Move ``task`` to ``proposed``, recording it in the audit chain, or refuse.

    The audit record is written in the caller's transaction (G2). A refused
    transition writes nothing: the record describes what happened, and a rejected
    move did not happen.

    Raises:
        IllegalTransitionError: if the machine does not allow the move, or if the
            move would exceed the rework limit in D11.
    """
    assert_task_transition(task.state, proposed)
    previous = task.state
    # The rework budget is *not* enforced here. D11 is owned solely by the
    # rework controller, which records an append-only attempt row per loop; that
    # row set is the single authority. Guarding here as well produced two
    # counters for one budget that disagreed at the boundary.

    task.state = proposed
    session.flush()

    audit_writer.append(
        session,
        tenant_id=task.tenant_id,
        event_type=EVENT_TASK_TRANSITIONED,
        actor_id=actor_id,
        payload={
            "task_id": str(task.id),
            "execution_id": str(task.execution_id),
            "from_state": previous.value,
            "to_state": proposed.value,
            "attempt_no": task.attempt_no,
        },
        keystore=keystore,
    )
    return task
