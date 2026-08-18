"""Cost accounting — `PRODUCT.md` §25.

Two tables, both tenant-scoped, and both deliberately **separate from the Action
record** rather than columns on it. Cost is a Phase 2 operational concern; the
Action is the Phase 1 integrity record that the audit chain covers. Keeping them
apart means the cost model can change without touching the record whose whole
value is that it does not.

``action_cost`` exists because the usage figures already live inside encrypted
evidence, which cannot be summed. A budget that has to decrypt every payload to
know what has been spent is a budget that never gets checked.
"""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import CheckConstraint, ForeignKey, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column

from adw.domain.ids import new_id
from adw.models.base import Base, CreatedAtMixin, TenantScopedMixin


class ActionCost(Base, TenantScopedMixin, CreatedAtMixin):
    """What one action consumed.

    Plain integers, queryable without a key. The same numbers are also inside the
    action's evidence, encrypted; this is the summable copy, and it carries no
    prompt, no completion, and no content of any kind — only counts.
    """

    __tablename__ = "action_cost"
    __table_args__ = (
        UniqueConstraint("action_id", name="one_cost_row_per_action"),
        CheckConstraint("prompt_tokens >= 0", name="prompt_tokens_not_negative"),
        CheckConstraint("completion_tokens >= 0", name="completion_tokens_not_negative"),
    )

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True, default=new_id)
    action_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("action.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    execution_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("execution.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    """Denormalised from the task deliberately. Checking a budget on every turn
    should not cost a three-table join, and an action never changes execution."""

    provider: Mapped[str] = mapped_column(nullable=False)
    model: Mapped[str] = mapped_column(nullable=False)
    """Which model was billed. Attribution per `PRODUCT.md` §25 — a cost that
    cannot be attributed cannot be controlled. Never a credential."""

    prompt_tokens: Mapped[int] = mapped_column(nullable=False, default=0)
    completion_tokens: Mapped[int] = mapped_column(nullable=False, default=0)


class ExecutionBudget(Base, TenantScopedMixin, CreatedAtMixin):
    """A token ceiling for one execution, and the record of who raised it.

    `PRODUCT.md` §25 makes this tenant-configurable and a hard stop: pause at
    100%, warn at 80%, and require human authorization to continue. Continuing is
    therefore an explicit act that raises the ceiling and names who did it —
    never a retry that quietly succeeds because a counter reset.
    """

    __tablename__ = "execution_budget"
    __table_args__ = (
        UniqueConstraint("execution_id", name="one_budget_per_execution"),
        CheckConstraint("max_total_tokens > 0", name="budget_is_positive"),
        CheckConstraint(
            "warn_at_ratio > 0 AND warn_at_ratio < 1", name="warning_precedes_exhaustion"
        ),
    )

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True, default=new_id)
    execution_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("execution.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )

    max_total_tokens: Mapped[int] = mapped_column(nullable=False)
    warn_at_ratio: Mapped[float] = mapped_column(nullable=False, default=0.8)

    authorized_by_identity: Mapped[str | None] = mapped_column(nullable=True)
    """Set when a human raised the ceiling. Null means the budget is still the
    one it was created with."""
