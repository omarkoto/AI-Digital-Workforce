"""State vocabularies.

Only the *names* live here. The legal transitions between them are deliberately
absent — see :mod:`adw.domain.transitions`.

Values are lowercase strings because they are persisted and appear inside audit
chain records, where a rename would invalidate every historical hash.
"""

from __future__ import annotations

from enum import StrEnum


class ExecutionState(StrEnum):
    """One run of one requirement. PHASE-1-IMPLEMENTATION-PLAN §8."""

    DRAFT = "draft"
    PLANNING = "planning"
    AWAITING_CONFIRMATION = "awaiting_confirmation"
    RUNNING = "running"
    AWAITING_APPROVAL = "awaiting_approval"
    COMPLETED = "completed"
    FAILED = "failed"
    BLOCKED = "blocked"
    CANCELLED = "cancelled"
    EXPIRED = "expired"


class TaskState(StrEnum):
    """The unit of assignment. ARCHITECTURE.md §5.8."""

    PLANNED = "planned"
    QUEUED = "queued"
    RUNNING = "running"
    PRODUCING = "producing"
    AWAITING_GATE = "awaiting_gate"
    PASSED = "passed"
    REWORKING = "reworking"
    BLOCKED = "blocked"
    FAILED = "failed"


class ActionState(StrEnum):
    """The action truth model. CLAUDE.md §3, plus `unverified` from ARCHITECTURE.md §5.4.

    These six are the platform's core integrity claim. They are distinct
    persisted states and must never be collapsed into a boolean.

    ``UNVERIFIED`` means a completion was reported with no execution evidence
    recorded. It is never presented as success.
    """

    PLANNED = "planned"
    ATTEMPTED = "attempted"
    EXECUTED = "executed"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    UNVERIFIED = "unverified"


class ApprovalState(StrEnum):
    """A human gate awaiting a decision. PHASE-1-IMPLEMENTATION-PLAN §18."""

    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    EXPIRED = "expired"


class JobState(StrEnum):
    """A unit of queued work. D17.

    Dispatch state only — it says nothing about the business outcome, which lives
    in the execution record. A ``done`` job may well have recorded a failed
    action; the two are different questions.
    """

    READY = "ready"
    CLAIMED = "claimed"
    DONE = "done"
    FAILED = "failed"


class GateVerdict(StrEnum):
    """The outcome of a Control Gate. DESIGN.md §11.5."""

    PASS = "pass"  # noqa: S105 — a gate verdict, not a credential
    FAIL = "fail"
    WAIVED = "waived"


class GateEvaluationKind(StrEnum):
    """How a verdict was reached. DESIGN.md §11.5.

    A model-assessed verdict is never presented with the same finality as a
    deterministic check, so the distinction is carried in the record itself.
    """

    DETERMINISTIC = "deterministic"
    MODEL_ASSESSED = "model_assessed"
