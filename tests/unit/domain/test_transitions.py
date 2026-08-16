"""The transitions placeholder fails loudly rather than permitting anything.

Task 2 ships no transition rules. These tests pin that absence so it stays
deliberate: if someone later implements transitions, they must delete these
tests consciously rather than discover the module quietly started allowing
things.
"""

from __future__ import annotations

import pytest

from adw.domain.errors import DomainError, TransitionsNotAvailableError
from adw.domain.states import ExecutionState, TaskState
from adw.domain.transitions import assert_transition_allowed


@pytest.mark.unit
def test_any_transition_check_raises() -> None:
    with pytest.raises(TransitionsNotAvailableError):
        assert_transition_allowed(ExecutionState.DRAFT, ExecutionState.PLANNING)


@pytest.mark.unit
def test_it_refuses_even_an_obviously_illegal_transition() -> None:
    """It does not decide; it declines. Refusing only bad input would be a rule."""
    with pytest.raises(TransitionsNotAvailableError):
        assert_transition_allowed(TaskState.PASSED, TaskState.RUNNING)


@pytest.mark.unit
def test_failure_is_catchable_as_a_domain_error() -> None:
    with pytest.raises(DomainError):
        assert_transition_allowed(TaskState.PLANNED, TaskState.QUEUED)


@pytest.mark.unit
def test_the_error_names_why_it_is_blocked() -> None:
    with pytest.raises(TransitionsNotAvailableError) as excinfo:
        assert_transition_allowed(ExecutionState.RUNNING, ExecutionState.COMPLETED)
    message = str(excinfo.value)
    assert "unresolved product decisions" in message


@pytest.mark.unit
def test_module_exports_no_transition_tables() -> None:
    """Nothing here may be mistaken for a rule."""
    from adw.domain import transitions

    exported = {name for name in dir(transitions) if not name.startswith("_")}
    assert exported == {
        "Never",
        "TransitionsNotAvailableError",
        "annotations",
        "assert_transition_allowed",
    }
