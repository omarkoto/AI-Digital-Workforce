"""Task state transitions.

The only writer of ``Task.state``. Centralising it means the machine cannot be
bypassed by a stray update somewhere else in the codebase.

Task 5 adds the audit chain record to the same transaction, so that a transition
and its audit entry can never diverge (G2). The transaction boundary is already
the caller's ``tenant_session``, so that addition needs no restructuring here.
"""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from adw.domain.errors import IllegalTransitionError
from adw.domain.states import TaskState
from adw.domain.transitions import assert_task_transition
from adw.models.task import MAX_REWORK_ATTEMPTS, Task


def get_task(session: Session, task_id: UUID) -> Task | None:
    """Return a task visible in the session's tenant context, or ``None``.

    A task belonging to another tenant is indistinguishable from one that does
    not exist, which is the intended shape of the fail-closed rule.
    """
    return session.scalar(select(Task).where(Task.id == task_id))


def transition(session: Session, task: Task, proposed: TaskState) -> Task:
    """Move ``task`` to ``proposed``, or refuse.

    Raises:
        IllegalTransitionError: if the machine does not allow the move, or if the
            move would exceed the rework limit in D11.
    """
    assert_task_transition(task.state, proposed)

    if task.state is TaskState.REWORKING and proposed is TaskState.QUEUED:
        # The machine permits both REWORKING -> QUEUED and REWORKING -> BLOCKED.
        # Which one is legal here depends on the attempt count, which is a
        # service-level condition rather than an edge in the machine (D11).
        if task.attempt_no >= MAX_REWORK_ATTEMPTS:
            msg = (
                f"rework limit reached: task has used {task.attempt_no} of "
                f"{MAX_REWORK_ATTEMPTS} attempts and must move to "
                f"{TaskState.BLOCKED.value!r} for human decision"
            )
            raise IllegalTransitionError(msg)
        task.attempt_no += 1

    task.state = proposed
    session.flush()
    return task
