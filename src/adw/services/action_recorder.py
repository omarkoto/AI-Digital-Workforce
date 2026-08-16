"""The only writer of the Action lifecycle — CLAUDE.md §3, I10, G2.

Each transition writes its audit chain record in the same transaction, so the
lifecycle and the record cannot diverge.

**Reaching ``succeeded`` requires linked evidence.** The database enforces it by
trigger; this service refuses earlier, so the caller gets a clear failure rather
than a constraint violation. Both layers exist deliberately: the service explains,
the trigger guarantees.

Transitions are not validated against a machine, because the Action machine's
edges are not documented — nothing states what precedes ``unverified``, and a
timeout fits neither ``executed`` nor ``failed`` as defined. What *is* enforced
is the one rule the documents state unambiguously.
"""

from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from adw.domain.errors import DomainError
from adw.domain.states import ActionState
from adw.models.action import Action, Evidence
from adw.models.task import Task
from adw.ports.keystore import KeyStore
from adw.services import audit_writer

EVENT_ACTION_TRANSITIONED = "action.transitioned"


class EvidenceRequiredError(DomainError):
    """An action was moved to ``succeeded`` with no evidence linked.

    `CLAUDE.md` §3: never claim an action was completed without execution
    evidence. An agent's assertion is not evidence.
    """


def plan_action(session: Session, *, task: Task, sequence: int, tool_name: str) -> Action:
    """Record an action the plan says should occur, before anything runs."""
    action = Action(
        tenant_id=task.tenant_id,
        task_id=task.id,
        sequence=sequence,
        tool_name=tool_name,
        state=ActionState.PLANNED,
    )
    session.add(action)
    session.flush()
    return action


def has_evidence(session: Session, action: Action) -> bool:
    count = session.execute(
        select(func.count()).select_from(Evidence).where(Evidence.action_id == action.id)
    ).scalar_one()
    return bool(count)


def transition(
    session: Session,
    action: Action,
    proposed: ActionState,
    *,
    keystore: KeyStore,
    actor_id: str,
    failure_detail: str | None = None,
) -> Action:
    """Move ``action`` to ``proposed``, recording it in the audit chain.

    Raises:
        EvidenceRequiredError: on a move to ``succeeded`` with no evidence.
    """
    if proposed is ActionState.SUCCEEDED and not has_evidence(session, action):
        msg = (
            f"action {action.id} cannot reach 'succeeded' without linked evidence; "
            "a reported completion with no evidence is 'unverified', never success"
        )
        raise EvidenceRequiredError(msg)

    previous = action.state
    action.state = proposed
    if failure_detail is not None:
        action.failure_detail = failure_detail
    session.flush()

    audit_writer.append(
        session,
        tenant_id=action.tenant_id,
        event_type=EVENT_ACTION_TRANSITIONED,
        actor_id=actor_id,
        payload={
            "action_id": str(action.id),
            "task_id": str(action.task_id),
            "tool_name": action.tool_name,
            "from_state": previous.value,
            "to_state": proposed.value,
        },
        keystore=keystore,
    )
    return action
