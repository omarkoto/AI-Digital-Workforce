"""Legal state transitions — NOT IMPLEMENTED, and deliberately so.

This module is a placeholder. It defines no transition tables because the
documents do not yet contain enough to derive them, and inventing the missing
rules here would smuggle product decisions into code.

`CLAUDE.md` §6 requires workflows to be declared state machines with enumerated
states and legal transitions. The states exist — see :mod:`adw.domain.states`.
The transitions do not, for the reasons below.

What *is* fully specified, and can be implemented the moment this module is
unblocked: the **Task** machine, in ARCHITECTURE.md §5.8.

What is blocked, with the gap in each case:

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
    non-terminal while naming no exit. The documents define what expiry must not
    do and never define what it may do.

Rework
    No document enumerates Rework states at all. `CLAUDE.md` §6 lists Rework
    among the state machines, while PHASE-1-IMPLEMENTATION-PLAN §17 models a
    Rework Attempt as an append-only record with no state field, and DESIGN.md
    §12.1 renders it as a counter ("Rework 2 of 3"). Both readings are
    consistent with what is written; choosing between them is a product
    decision, not an implementation detail.

Until those are resolved, this module exports nothing that could be mistaken for
a rule. Anything reaching for a transition check gets an explicit, named
failure rather than a permissive default.
"""

from __future__ import annotations

from typing import Never

from adw.domain.errors import TransitionsNotAvailableError

__all__ = ["assert_transition_allowed"]


def assert_transition_allowed(current: object, proposed: object) -> Never:
    """Always raise. Transition rules do not exist yet.

    Present so that a caller written against this interface fails loudly and
    traceably, rather than silently permitting a transition that no document
    authorises.

    Raises:
        TransitionsNotAvailableError: always.
    """
    msg = (
        "state transition rules are not implemented: the legal transitions for "
        "Execution, Action, Approval, and Rework contain unresolved product "
        "decisions. See the module docstring for the specific gaps."
    )
    raise TransitionsNotAvailableError(msg)
