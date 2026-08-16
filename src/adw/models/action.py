"""Action and Evidence — CLAUDE.md §3, D12, D25, D29.

The Action carries the six-state lifecycle that is the platform's core integrity
claim. The distinction between planned, attempted, executed, succeeded, and
failed only exists because something records them as distinct states rather than
collapsing them into a boolean.

Evidence is the recorded proof. It is written redacted (D12), stored encrypted
(D1), and digested over the raw ciphertext bytes (D29) — so the record survives
key destruction even though the content does not.

**An action cannot reach ``succeeded`` without linked evidence** (I10/G15). That
is enforced by a database trigger, not by a service that might be bypassed: it is
the single rule that stops the platform claiming work it cannot prove.
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import (
    CheckConstraint,
    ForeignKey,
    LargeBinary,
    UniqueConstraint,
)
from sqlalchemy import Enum as SqlEnum
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from adw.domain.ids import new_id
from adw.domain.states import ActionState
from adw.models.base import Base, CreatedAtMixin, TenantScopedMixin, UpdatedAtMixin


class Action(Base, TenantScopedMixin, CreatedAtMixin, UpdatedAtMixin):
    """One tool invocation within a task."""

    __tablename__ = "action"
    __table_args__ = (UniqueConstraint("task_id", "sequence"),)

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True, default=new_id)
    task_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("task.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    sequence: Mapped[int] = mapped_column(nullable=False)

    tool_name: Mapped[str] = mapped_column(nullable=False)
    """Which tool was invoked. Not the arguments — those are evidence."""

    state: Mapped[ActionState] = mapped_column(
        SqlEnum(
            ActionState,
            name="action_state",
            native_enum=False,
            values_callable=lambda enum: [member.value for member in enum],
            length=32,
        ),
        default=ActionState.PLANNED,
        nullable=False,
        index=True,
    )
    """Transitions are **not** enforced. The Action machine has documented states
    but undocumented edges: nothing states what precedes ``unverified``, and a
    timeout fits neither ``executed`` nor ``failed`` as `CLAUDE.md` §3 defines
    them. See :mod:`adw.domain.transitions`."""

    failure_detail: Mapped[str | None] = mapped_column(nullable=True)
    """A summary, never a payload. Payloads are evidence."""

    evidence: Mapped[list[Evidence]] = relationship(back_populates="action")


class Evidence(Base, TenantScopedMixin, CreatedAtMixin):
    """Recorded proof that an action occurred, or that a gate decided.

    Attaches to exactly one of the two. ``gate_decision_id`` has no foreign key
    yet because gate decisions arrive in Task 9; the exclusivity invariant is
    enforced from the first row regardless, so no evidence can ever be orphaned
    or doubly-owned.
    """

    __tablename__ = "evidence"

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True, default=new_id)

    action_id: Mapped[UUID | None] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("action.id", ondelete="RESTRICT"),
        nullable=True,
        index=True,
    )
    gate_decision_id: Mapped[UUID | None] = mapped_column(
        PgUUID(as_uuid=True), nullable=True, index=True
    )

    kind: Mapped[str] = mapped_column(nullable=False)
    """What sort of proof this is — exit status, response payload, row count,
    file digest. Descriptive, and not a schema."""

    inline_ciphertext: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)
    blob_key: Mapped[str | None] = mapped_column(nullable=True)
    """Small evidence is stored inline, large evidence as a blob. Exactly one,
    never both — otherwise the record has two sources of truth."""

    key_id: Mapped[str] = mapped_column(nullable=False)
    """D25. Without it, rotation is impossible and erasure becomes guesswork."""

    content_digest: Mapped[str] = mapped_column(nullable=False)
    """Raw-byte digest of the ciphertext (D29), never of a canonical form."""

    size_bytes: Mapped[int] = mapped_column(nullable=False)

    redaction_count: Mapped[int] = mapped_column(nullable=False, default=0)
    """How many redaction rules fired before this was written. Recorded so the
    record shows redaction *ran*, not merely that it was configured."""

    recorded_at: Mapped[datetime | None] = mapped_column(nullable=True)
    """When the evidence was observed, if the source reported it. Distinct from
    ``created_at``, which is when the platform wrote it — a value a tool reported
    is content, never the platform's own event time (D21)."""

    action: Mapped[Action | None] = relationship(back_populates="evidence")

    __table_args__ = (
        CheckConstraint(
            "num_nonnulls(action_id, gate_decision_id) = 1",
            name="attaches_to_exactly_one_subject",
        ),
        CheckConstraint(
            "num_nonnulls(inline_ciphertext, blob_key) = 1",
            name="stored_inline_or_as_blob",
        ),
        CheckConstraint("size_bytes >= 0", name="size_not_negative"),
        CheckConstraint("redaction_count >= 0", name="redaction_count_not_negative"),
    )
