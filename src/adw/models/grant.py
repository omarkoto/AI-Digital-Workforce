"""Tool permission grants — D10, I9, `PHASE-3-IMPLEMENTATION-PLAN.md` §6 (B3).

**Permissions are pre-declared.** The set is fixed when the task is created and
the Tool Gateway refuses any tool not in it. There are no dynamic grants: a
running agent cannot acquire a capability it did not start with, by any path,
including asking for one.

That is the strong form of D10's separation between instruction and capability.
An agent's context can be poisoned; its permission set cannot, because nothing
the model emits reaches the code that writes these rows.

A grant does double duty, and deliberately so. It is the **authorization** —
"this task may call this tool" — and it is the tool version's **pin** (I4), so
one row answers both "was this allowed?" and "which version ran?". A task cannot
hold two versions of the same tool, because a grant reviewed against one
descriptor must not silently come to mean another.

**The authorization columns never change.** A trigger rejects any update that
touches the task, the version, the scopes, or the expiry — widening a permission
after it was declared is precisely what pre-declaration exists to prevent.
Revocation is the one thing that may be applied later, because it only ever
narrows.
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column

from adw.domain.ids import new_id
from adw.models.base import Base, CreatedAtMixin, TenantScopedMixin

DEFAULT_GRANT_TTL_SECONDS = 4 * 60 * 60
"""Four hours, matching `PRODUCT.md` §25's maximum execution wall-clock. A grant
that outlives the longest possible execution is not time-boxed in any sense that
matters (I9)."""


class ToolGrant(Base, TenantScopedMixin, CreatedAtMixin):
    """One task's permission to call one tool version, until it expires."""

    __tablename__ = "tool_grant"
    __table_args__ = (
        UniqueConstraint("task_id", "tool_definition_id", name="one_version_per_tool_per_task"),
        CheckConstraint(
            "(revoked_at IS NULL) = (revoked_by_identity IS NULL)",
            name="a_revocation_names_who_made_it",
        ),
    )

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True, default=new_id)
    task_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("task.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )

    tool_definition_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("tool_definition.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    """Denormalised from the version so the gateway's lookup — by tool *key* —
    is one join, and so "one version per tool per task" is expressible as a
    constraint rather than as a convention."""

    tool_definition_version_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("tool_definition_version.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    """The pin (I4). ``RESTRICT`` because the descriptor that was authorized must
    survive as long as the record of the authorization does."""

    scopes_json: Mapped[str] = mapped_column(nullable=False, default="[]")
    """What this grant permits within the tool. Checked against the descriptor's
    required scopes at invocation, and never widened by anything the model says."""

    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    """D10/I9: time-boxed. Computed from the database clock (D21/G6), so the
    expiry the gateway enforces and the expiry a console shows cannot diverge."""

    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    revoked_by_identity: Mapped[str | None] = mapped_column(nullable=True)
    """The only thing that may be applied after creation, because it only ever
    narrows. Both columns move together or neither does."""
