"""Control Gates, rework, and human approval — D4, D6, D7, D11, I5.

A Control Gate is the mandatory checkpoint. Its **definition** is versioned and
platform-curated; its **decision** is a runtime record naming the verdict, who
decided, what was judged, and which rule produced it.

Two rules are enforced by the database rather than by a service, because both are
load-bearing claims the product is sold on:

* **The producer can never be the approver** (D4/I5) — a CHECK constraint, which
  is possible because both identities live on the same row. `CLAUDE.md` §3
  requires this in code rather than by prompt instruction.
* **Rework is capped at three attempts** (D11) — a CHECK constraint, so the limit
  holds even where a service forgets.

Approval expiry is the third: D7 says it must never auto-approve, auto-reject, or
silently proceed. That is a state machine property rather than a constraint, and
it is enforced in the approval service and asserted in tests.
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, UniqueConstraint
from sqlalchemy import Enum as SqlEnum
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from adw.domain.ids import new_id
from adw.domain.states import ApprovalState, GateEvaluationKind, GateVerdict
from adw.models.base import Base, CreatedAtMixin, TenantScopedMixin

MAX_REWORK_ATTEMPTS = 3
"""D11. Mirrors the cap on Task.attempt_no; both refer to the same budget."""


class GateDefinition(Base, CreatedAtMixin):
    """The durable identity of a checkpoint. Platform-curated (D30)."""

    __tablename__ = "gate_definition"

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True, default=new_id)
    key: Mapped[str] = mapped_column(unique=True, nullable=False)
    name: Mapped[str] = mapped_column(nullable=False)

    versions: Mapped[list[GateDefinitionVersion]] = relationship(
        back_populates="definition",
        order_by="GateDefinitionVersion.version_no",
    )


class GateDefinitionVersion(Base, CreatedAtMixin):
    """One immutable revision of a checkpoint's rule."""

    __tablename__ = "gate_definition_version"
    __table_args__ = (UniqueConstraint("gate_definition_id", "version_no"),)

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True, default=new_id)
    gate_definition_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("gate_definition.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    version_no: Mapped[int] = mapped_column(nullable=False)

    rule_id: Mapped[str] = mapped_column(nullable=False)
    """Which evaluator runs. Named on every decision, so a verdict can always
    say what produced it (DESIGN.md §11.5)."""

    evaluation_kind: Mapped[GateEvaluationKind] = mapped_column(
        SqlEnum(
            GateEvaluationKind,
            name="gate_evaluation_kind",
            native_enum=False,
            values_callable=lambda enum: [member.value for member in enum],
            length=32,
        ),
        nullable=False,
    )
    """Deterministic, model-assessed, or human. Carried into the decision so a
    model-assessed verdict is never presented with the finality of a
    deterministic check."""

    requires_human: Mapped[bool] = mapped_column(default=False, nullable=False)
    config_json: Mapped[str] = mapped_column(nullable=False, default="{}")

    definition: Mapped[GateDefinition] = relationship(back_populates="versions")


class GateDecision(Base, TenantScopedMixin, CreatedAtMixin):
    """One verdict on one artifact version.

    A verdict never appears without an approver, a timestamp, the artifact
    version judged, and the rule applied (DESIGN.md §11.5). All four are
    non-nullable here for that reason.
    """

    __tablename__ = "gate_decision"
    __table_args__ = (
        # D4/I5, enforced where it cannot be routed around. CLAUDE.md §3 requires
        # this in code, not by prompt instruction.
        CheckConstraint(
            "decided_by_identity <> producer_identity", name="producer_is_not_the_approver"
        ),
    )

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True, default=new_id)
    gate_definition_version_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("gate_definition_version.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    """Pinned (D9): the rule as it stood, not as it stands now."""

    artifact_version_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("artifact_version.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    task_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("task.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )

    verdict: Mapped[GateVerdict] = mapped_column(
        SqlEnum(
            GateVerdict,
            name="gate_verdict",
            native_enum=False,
            values_callable=lambda enum: [member.value for member in enum],
            length=16,
        ),
        nullable=False,
        index=True,
    )
    decided_by_identity: Mapped[str] = mapped_column(nullable=False)
    producer_identity: Mapped[str] = mapped_column(nullable=False)
    decided_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    rule_id: Mapped[str] = mapped_column(nullable=False)
    evaluation_kind: Mapped[GateEvaluationKind] = mapped_column(
        SqlEnum(
            GateEvaluationKind,
            name="gate_evaluation_kind",
            native_enum=False,
            values_callable=lambda enum: [member.value for member in enum],
            length=32,
        ),
        nullable=False,
    )
    failure_detail: Mapped[str | None] = mapped_column(nullable=True)
    waiver_reason: Mapped[str | None] = mapped_column(nullable=True)
    """A waiver bypasses a mandatory gate, so it is governed harder than an
    approval: it never happens silently and its reason is part of the record."""


class ReworkAttempt(Base, TenantScopedMixin, CreatedAtMixin):
    """One controlled return of a task after a failed gate.

    Append-only and counted, so `DESIGN.md` §12.1 can render "Rework 2 of 3".
    Failure is a first-class visible path, never a hidden retry.
    """

    __tablename__ = "rework_attempt"
    __table_args__ = (
        UniqueConstraint("task_id", "attempt_no"),
        CheckConstraint(
            f"attempt_no BETWEEN 1 AND {MAX_REWORK_ATTEMPTS}", name="within_rework_limit"
        ),
    )

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True, default=new_id)
    task_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("task.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    attempt_no: Mapped[int] = mapped_column(nullable=False)
    triggering_gate_decision_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("gate_decision.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    failure_detail: Mapped[str] = mapped_column(nullable=False)
    """What to fix, attached to the reopened task. A rework with no reason is a
    retry, and D11 exists to stop those."""


class ApprovalItem(Base, TenantScopedMixin, CreatedAtMixin):
    """A human gate awaiting a decision — D6, D7.

    Every execution ends in one of these (D6): a fully autonomous execution does
    not exist in this product.
    """

    __tablename__ = "approval_item"
    __table_args__ = (
        # I5 again, at the point where a human decides. Both exclusions matter:
        # D4 bars the producer, and PRODUCT.md §18 bars the requester too.
        CheckConstraint(
            "decided_by_identity IS NULL OR "
            "(decided_by_identity <> producer_identity "
            "AND decided_by_identity <> requester_identity)",
            name="decider_is_neither_producer_nor_requester",
        ),
        CheckConstraint(
            "(state = 'pending') = (decided_at IS NULL)", name="decided_states_carry_a_timestamp"
        ),
    )

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True, default=new_id)
    artifact_version_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("artifact_version.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    gate_definition_version_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("gate_definition_version.id", ondelete="RESTRICT"),
        nullable=False,
    )
    task_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("task.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )

    state: Mapped[ApprovalState] = mapped_column(
        SqlEnum(
            ApprovalState,
            name="approval_state",
            native_enum=False,
            values_callable=lambda enum: [member.value for member in enum],
            length=16,
        ),
        default=ApprovalState.PENDING,
        nullable=False,
        index=True,
    )

    producer_identity: Mapped[str] = mapped_column(nullable=False)
    requester_identity: Mapped[str] = mapped_column(nullable=False)
    decided_by_identity: Mapped[str | None] = mapped_column(nullable=True)
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    sla_deadline: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    """D7: 72 hours by default, computed from the database clock so the deadline
    a user sees and the deadline the scheduler enforces cannot diverge."""

    escalated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    escalated_to: Mapped[str | None] = mapped_column(nullable=True)
    """Escalation is explicit and audited (D7), never an implicit consequence of
    time passing."""

    gate_decision_id: Mapped[UUID | None] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("gate_decision.id", ondelete="RESTRICT"),
        nullable=True,
    )
    """Set when a human decides. Null while pending, and null forever if the item
    expires — because expiry produces no verdict."""
