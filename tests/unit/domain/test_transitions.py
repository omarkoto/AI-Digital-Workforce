"""The four unimplemented machines still fail loudly.

Task 4 implemented the Task machine, which is the only one the documents specify
completely. Execution, Action, Approval, and Rework remain blocked on unresolved
product decisions, and these tests pin that absence so it stays deliberate: if
someone later implements them, they must delete these consciously rather than
discover the module quietly started allowing things.

The Task machine's own tests live in ``test_task_transitions.py``.
"""

from __future__ import annotations

import pytest

from adw.domain.errors import DomainError, TransitionsNotAvailableError
from adw.domain.states import ActionState, ApprovalState, ExecutionState
from adw.domain.transitions import assert_transition_allowed

BLOCKED_PAIRS = [
    (ExecutionState.DRAFT, ExecutionState.PLANNING),
    (ExecutionState.AWAITING_APPROVAL, ExecutionState.COMPLETED),
    (ActionState.PLANNED, ActionState.ATTEMPTED),
    (ActionState.EXECUTED, ActionState.SUCCEEDED),
    (ApprovalState.PENDING, ApprovalState.APPROVED),
    (ApprovalState.EXPIRED, ApprovalState.APPROVED),
]


@pytest.mark.unit
@pytest.mark.parametrize(("current", "proposed"), BLOCKED_PAIRS)
def test_blocked_machines_refuse_every_transition(current: object, proposed: object) -> None:
    """Even a transition the documents *do* describe stays refused.

    The Execution happy path is documented; its alternates are not. Permitting
    the documented half would imply the machine is settled when it is not.
    """
    with pytest.raises(TransitionsNotAvailableError):
        assert_transition_allowed(current, proposed)


@pytest.mark.unit
def test_failure_is_catchable_as_a_domain_error() -> None:
    with pytest.raises(DomainError):
        assert_transition_allowed(ExecutionState.RUNNING, ExecutionState.FAILED)


@pytest.mark.unit
def test_the_error_names_why_it_is_blocked() -> None:
    with pytest.raises(TransitionsNotAvailableError) as excinfo:
        assert_transition_allowed(ExecutionState.RUNNING, ExecutionState.COMPLETED)
    assert "unresolved product decisions" in str(excinfo.value)


@pytest.mark.unit
def test_no_transition_table_exists_for_a_blocked_machine() -> None:
    """Only Task has a table. A second one appearing means someone invented rules."""
    from adw.domain import transitions

    tables = {name for name in dir(transitions) if name.isupper() and name.endswith("_TRANSITIONS")}
    assert tables == {"TASK_TRANSITIONS"}
