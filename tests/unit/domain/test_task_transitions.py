"""The Task state machine — ARCHITECTURE.md §5.8.

The only machine the documents specify completely. Rejection is asserted
exhaustively rather than by sample: every pair not in the table must fail.
"""

from __future__ import annotations

import itertools

import pytest

from adw.domain.errors import IllegalTransitionError, TransitionsNotAvailableError
from adw.domain.states import ExecutionState, TaskState
from adw.domain.transitions import (
    TASK_TRANSITIONS,
    assert_task_transition,
    assert_transition_allowed,
    is_task_transition_allowed,
    task_terminal_states,
)

DOCUMENTED = {
    TaskState.PLANNED: {TaskState.QUEUED},
    TaskState.QUEUED: {TaskState.RUNNING},
    TaskState.RUNNING: {TaskState.PRODUCING, TaskState.FAILED},
    TaskState.PRODUCING: {TaskState.AWAITING_GATE},
    TaskState.AWAITING_GATE: {TaskState.PASSED, TaskState.REWORKING},
    TaskState.REWORKING: {TaskState.QUEUED, TaskState.BLOCKED},
    TaskState.FAILED: {TaskState.BLOCKED},
    TaskState.BLOCKED: {TaskState.QUEUED},
    TaskState.PASSED: set(),
}


@pytest.mark.unit
def test_table_matches_the_architecture_document() -> None:
    assert {state: set(targets) for state, targets in TASK_TRANSITIONS.items()} == DOCUMENTED


@pytest.mark.unit
def test_every_state_appears_as_a_key() -> None:
    """A terminal state is an explicit empty set, never a missing key.

    Omission would be indistinguishable from an oversight.
    """
    assert set(TASK_TRANSITIONS) == set(TaskState)


@pytest.mark.unit
@pytest.mark.parametrize(
    ("current", "proposed"),
    [
        (current, proposed)
        for current, proposed in itertools.product(TaskState, repeat=2)
        if proposed not in DOCUMENTED[current]
    ],
)
def test_every_undocumented_transition_is_rejected(current: TaskState, proposed: TaskState) -> None:
    """Exhaustive: all 81 ordered pairs, minus the 12 legal ones."""
    assert is_task_transition_allowed(current, proposed) is False
    with pytest.raises(IllegalTransitionError):
        assert_task_transition(current, proposed)


@pytest.mark.unit
@pytest.mark.parametrize(
    ("current", "proposed"),
    [(current, proposed) for current, targets in DOCUMENTED.items() for proposed in targets],
)
def test_every_documented_transition_is_permitted(current: TaskState, proposed: TaskState) -> None:
    assert is_task_transition_allowed(current, proposed) is True
    assert_task_transition(current, proposed)


@pytest.mark.unit
def test_passed_is_the_only_terminal_state() -> None:
    assert task_terminal_states() == frozenset({TaskState.PASSED})


@pytest.mark.unit
def test_no_state_transitions_to_itself() -> None:
    for state, targets in TASK_TRANSITIONS.items():
        assert state not in targets


@pytest.mark.unit
def test_rejection_message_names_both_states_and_the_alternatives() -> None:
    with pytest.raises(IllegalTransitionError) as excinfo:
        assert_task_transition(TaskState.PASSED, TaskState.RUNNING)
    message = str(excinfo.value)
    assert "'passed'" in message
    assert "'running'" in message
    assert "terminal" in message


@pytest.mark.unit
def test_the_other_four_machines_are_still_blocked() -> None:
    """Execution, Action, Approval, and Rework remain unresolved."""
    with pytest.raises(TransitionsNotAvailableError):
        assert_transition_allowed(ExecutionState.DRAFT, ExecutionState.PLANNING)


@pytest.mark.unit
def test_the_blocked_message_points_at_the_working_entry_point() -> None:
    with pytest.raises(TransitionsNotAvailableError) as excinfo:
        assert_transition_allowed(ExecutionState.RUNNING, ExecutionState.COMPLETED)
    assert "assert_task_transition" in str(excinfo.value)
