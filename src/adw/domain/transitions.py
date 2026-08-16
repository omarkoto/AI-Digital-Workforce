"""Legal state transitions.

**One machine is implemented: Task.** It is the only one the documents specify
completely (ARCHITECTURE.md §5.8). The other four remain deliberately absent,
because deriving them would mean inventing the missing rules rather than reading
them.

Execution
    The happy path is documented as a chain (plan §8) and corroborated by the
    worked example (ARCHITECTURE.md §31):
    ``draft -> planning -> awaiting_confirmation -> running ->
    awaiting_approval -> completed``, plus ``awaiting_approval -> expired``
    from D7. But ``failed``, ``blocked``, and ``cancelled`` are listed as states
    with no documented entry or exit, and ``expired`` is stated to require
    "explicit human action" without naming any target state. Whether
    ``awaiting_confirmation -> planning`` exists is implied by ARCHITECTURE.md
    §10 step 3 ("confirms *or adjusts* the plan") but never stated.

Action
    ``planned -> attempted -> executed -> succeeded | failed`` is documented
    (ARCHITECTURE.md §5.4 and the §13 gateway sequence). Three gaps remain.
    Nothing states what precedes ``unverified``, nor whether it is terminal.
    And the timeout path is uncovered: `CLAUDE.md` §3 defines ``failed`` as "it
    ran and did not" meet its criteria, so a tool that never completed cannot
    legitimately be ``executed`` *or* ``failed`` as currently written.

Approval
    ``pending -> approved | rejected | expired`` is documented. D7 then states
    that expiry "must never auto-approve, auto-reject, or silently proceed" and
    "requires explicit human action" — which makes ``expired`` provably
    non-terminal while naming no exit.

Rework
    No document enumerates Rework states at all. `CLAUDE.md` §6 lists Rework
    among the state machines, while PHASE-1-IMPLEMENTATION-PLAN §17 models a
    Rework Attempt as an append-only record with no state field.

Anything reaching for one of those four gets an explicit, named failure rather
than a permissive default.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Final, Never

from adw.domain.errors import IllegalTransitionError, TransitionsNotAvailableError
from adw.domain.states import TaskState

__all__ = [
    "TASK_TRANSITIONS",
    "assert_task_transition",
    "assert_transition_allowed",
    "is_task_transition_allowed",
    "task_terminal_states",
]


TASK_TRANSITIONS: Final[Mapping[TaskState, frozenset[TaskState]]] = {
    TaskState.PLANNED: frozenset({TaskState.QUEUED}),
    TaskState.QUEUED: frozenset({TaskState.RUNNING}),
    TaskState.RUNNING: frozenset({TaskState.PRODUCING, TaskState.FAILED}),
    TaskState.PRODUCING: frozenset({TaskState.AWAITING_GATE}),
    TaskState.AWAITING_GATE: frozenset({TaskState.PASSED, TaskState.REWORKING}),
    # Which of the two a reworking task takes is decided by the attempt count,
    # not by the machine: D11 caps rework at three attempts, and that guard is a
    # service-level condition rather than a separate edge.
    TaskState.REWORKING: frozenset({TaskState.QUEUED, TaskState.BLOCKED}),
    TaskState.FAILED: frozenset({TaskState.BLOCKED}),
    TaskState.BLOCKED: frozenset({TaskState.QUEUED}),
    TaskState.PASSED: frozenset(),
}
"""The complete Task machine from ARCHITECTURE.md §5.8.

Every state appears as a key, so a state with no outgoing edges is recorded as
an explicit empty set rather than by omission. A missing key would be
indistinguishable from an oversight.
"""


def task_terminal_states() -> frozenset[TaskState]:
    """Return the Task states from which no transition is legal."""
    return frozenset(state for state, allowed in TASK_TRANSITIONS.items() if not allowed)


def is_task_transition_allowed(current: TaskState, proposed: TaskState) -> bool:
    """Return whether ``current -> proposed`` is a legal Task transition."""
    return proposed in TASK_TRANSITIONS[current]


def assert_task_transition(current: TaskState, proposed: TaskState) -> None:
    """Raise unless ``current -> proposed`` is a legal Task transition.

    Raises:
        IllegalTransitionError: naming both states, so the failure is diagnosable
            from the message alone.
    """
    if not is_task_transition_allowed(current, proposed):
        allowed = sorted(state.value for state in TASK_TRANSITIONS[current])
        msg = (
            f"illegal task transition {current.value!r} -> {proposed.value!r}; "
            f"allowed from {current.value!r}: {allowed or 'none (terminal)'}"
        )
        raise IllegalTransitionError(msg)


def assert_transition_allowed(current: object, proposed: object) -> Never:
    """Always raise. Rules for Execution, Action, Approval, and Rework do not exist.

    Task transitions have their own entry point, :func:`assert_task_transition`.
    This one stays deliberately unusable so that a caller for any other machine
    fails loudly rather than silently permitting a transition no document
    authorises.

    Raises:
        TransitionsNotAvailableError: always.
    """
    msg = (
        "state transition rules are not implemented for this machine: the legal "
        "transitions for Execution, Action, Approval, and Rework contain "
        "unresolved product decisions. See the module docstring for the specific "
        "gaps. Task transitions are available via assert_task_transition()."
    )
    raise TransitionsNotAvailableError(msg)
