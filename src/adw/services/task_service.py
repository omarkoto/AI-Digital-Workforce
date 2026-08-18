"""Task state transitions.

The only writer of ``Task.state``. Centralising it means the machine cannot be
bypassed by a stray update somewhere else in the codebase.

**The transition and its audit record share one transaction** (G2), so the two
can never diverge: either both are durable or neither happened. The caller's
``tenant_session`` is that transaction; this module does not open its own.
"""

from __future__ import annotations

from collections.abc import Sequence
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from adw.domain.states import TaskState
from adw.domain.transitions import assert_task_transition
from adw.models.definition import AgentDefinitionVersion, SkillVersion
from adw.models.task import Task, TaskSkillPin
from adw.ports.keystore import KeyStore
from adw.services import audit_writer, grant_service

EVENT_TASK_TRANSITIONED = "task.transitioned"
EVENT_TASK_CREATED = "task.created"


def create_task(
    session: Session,
    *,
    tenant_id: UUID,
    execution_id: UUID,
    sequence: int,
    agent_version: AgentDefinitionVersion,
    skill_versions: Sequence[SkillVersion] = (),
    tool_grants: Sequence[grant_service.GrantRequest] = (),
    keystore: KeyStore,
    actor_id: str,
) -> Task:
    """Create a task with its definition versions pinned (D9/I4) and its
    permission set declared (D10/B3).

    Pinning happens here and nowhere else, at creation and once. A task that
    picked up "the current instructions" at run time could never answer what its
    instructions *were*, which is the question the whole record exists to answer.
    The pins are real foreign keys, so the database refuses to drop a version an
    execution relied on.

    The audit record names the pinned versions, so the reconstruction in
    :mod:`adw.verification.reconstructor` can report which rules governed the
    task without joining through mutable state.

    ``tool_grants`` is the task's **complete** permission set, and this is the
    only place one can be declared (B3). Nothing adds a permission to a running
    task, which is what makes "an agent cannot acquire a capability it did not
    start with" a property of the code rather than a promise about it. Grants are
    written in this transaction, so a task's capability and its instructions
    become durable together or not at all.
    """
    task = Task(
        tenant_id=tenant_id,
        execution_id=execution_id,
        sequence=sequence,
        agent_definition_version_id=agent_version.id,
        state=TaskState.PLANNED,
        attempt_no=1,
    )
    session.add(task)
    session.flush()

    for skill_version in skill_versions:
        session.add(
            TaskSkillPin(
                tenant_id=tenant_id,
                task_id=task.id,
                skill_version_id=skill_version.id,
            )
        )
    session.flush()

    grants = grant_service.declare(
        session,
        tenant_id=tenant_id,
        task_id=task.id,
        requests=tool_grants,
        keystore=keystore,
        actor_id=actor_id,
    )

    audit_writer.append(
        session,
        tenant_id=tenant_id,
        event_type=EVENT_TASK_CREATED,
        actor_id=actor_id,
        payload={
            "task_id": str(task.id),
            "execution_id": str(execution_id),
            "sequence": sequence,
            "agent_definition_version_id": str(agent_version.id),
            "agent_definition_version_no": agent_version.version_no,
            "skill_version_ids": [str(version.id) for version in skill_versions],
            "tool_grant_ids": [str(grant.id) for grant in grants],
        },
        keystore=keystore,
    )
    return task


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
