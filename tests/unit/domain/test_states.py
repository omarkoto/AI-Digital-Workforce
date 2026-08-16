"""State vocabularies.

Each set is asserted against a literal list taken from the documents, so a
rename or a quiet addition fails the build rather than drifting.
"""

from __future__ import annotations

from enum import StrEnum

import pytest

from adw.domain.states import (
    ActionState,
    ApprovalState,
    ExecutionState,
    GateEvaluationKind,
    GateVerdict,
    TaskState,
)


@pytest.mark.unit
def test_action_states_match_the_action_truth_model() -> None:
    """CLAUDE.md §3 plus `unverified` from ARCHITECTURE.md §5.4."""
    assert {s.value for s in ActionState} == {
        "planned",
        "attempted",
        "executed",
        "succeeded",
        "failed",
        "unverified",
    }


@pytest.mark.unit
def test_action_truth_model_has_exactly_six_states() -> None:
    """The distinction CLAUDE.md §3 calls the core integrity rule, counted."""
    assert len(ActionState) == 6


@pytest.mark.unit
def test_execution_states_match_the_implementation_plan() -> None:
    """PHASE-1-IMPLEMENTATION-PLAN §8."""
    assert {s.value for s in ExecutionState} == {
        "draft",
        "planning",
        "awaiting_confirmation",
        "running",
        "awaiting_approval",
        "completed",
        "failed",
        "blocked",
        "cancelled",
        "expired",
    }


@pytest.mark.unit
def test_task_states_match_the_architecture_state_machine() -> None:
    """ARCHITECTURE.md §5.8."""
    assert {s.value for s in TaskState} == {
        "planned",
        "queued",
        "running",
        "producing",
        "awaiting_gate",
        "passed",
        "reworking",
        "blocked",
        "failed",
    }


@pytest.mark.unit
def test_approval_states_match_the_implementation_plan() -> None:
    """PHASE-1-IMPLEMENTATION-PLAN §18."""
    assert {s.value for s in ApprovalState} == {"pending", "approved", "rejected", "expired"}


@pytest.mark.unit
def test_gate_verdicts_match_the_design_document() -> None:
    """DESIGN.md §11.5."""
    assert {v.value for v in GateVerdict} == {"pass", "fail", "waived"}


@pytest.mark.unit
def test_gate_evaluation_kinds_are_distinguished() -> None:
    """DESIGN.md §11.5: a model-assessed verdict is never presented as deterministic."""
    assert {k.value for k in GateEvaluationKind} == {"deterministic", "model_assessed"}


@pytest.mark.unit
@pytest.mark.parametrize(
    "enum_type",
    [ActionState, ApprovalState, ExecutionState, GateEvaluationKind, GateVerdict, TaskState],
)
def test_states_are_strings_for_stable_persistence(enum_type: type[StrEnum]) -> None:
    """Values persist and appear in the audit chain, so they must be stable strings."""
    for member in enum_type:
        assert isinstance(member.value, str)
        assert member.value == member.value.lower()
        assert member.value.strip() == member.value
