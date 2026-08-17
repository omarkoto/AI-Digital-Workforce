"""Dispatch queue and idempotency ledger — D17, I13.

**Platform-scoped, not tenant-scoped, and deliberately so.** Row-level security
requires tenant context per transaction, but a worker cannot know which tenant's
job to claim until it has read the queue. So the queue carries ``tenant_id`` as a
*routing field* and **no business content whatsoever** — one of the three
structures I13 places outside tenant scope.

That rule is a security boundary rather than a convention, so the column set is
asserted by a test: adding a payload column fails the build.

``JobExecution`` is the idempotency ledger. At-least-once delivery is the only
delivery a database queue provides, so a redelivered job must produce no second
effect — and "handlers are naturally idempotent" is a hope, not a mechanism.
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import CheckConstraint, DateTime, Index, UniqueConstraint
from sqlalchemy import Enum as SqlEnum
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column

from adw.domain.ids import new_id
from adw.domain.states import JobState
from adw.models.base import Base

QUEUE_COLUMNS = frozenset(
    {
        "id",
        "tenant_id",
        "job_type",
        "target_id",
        "idempotency_key",
        "available_at",
        "claimed_at",
        "claimed_by",
        "attempts",
        "state",
        "created_at",
    }
)
"""The complete, permitted column set. Identifiers and scheduling only.

Enforced by test rather than by comment: a payload column here would hand every
worker cross-tenant business content, which is exactly what I13 forbids.
"""


class DispatchJob(Base):
    """One unit of queued work.

    Claimed with ``SELECT ... FOR UPDATE SKIP LOCKED``, so concurrent workers
    never contend for the same row and a slow handler blocks nobody.
    """

    __tablename__ = "dispatch_queue"
    __table_args__ = (
        UniqueConstraint("tenant_id", "idempotency_key"),
        CheckConstraint("attempts >= 0", name="attempts_not_negative"),
        Index("ix_dispatch_queue_claimable", "state", "available_at"),
    )

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True, default=new_id)
    tenant_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False, index=True)
    """A routing field. Deliberately *not* behind a tenant policy: the worker
    reads this to learn which context to open, so it cannot itself require one."""

    job_type: Mapped[str] = mapped_column(nullable=False)
    target_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False)
    """What to act on — an identifier, never the thing itself."""

    idempotency_key: Mapped[str] = mapped_column(nullable=False)
    available_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    claimed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    claimed_by: Mapped[str | None] = mapped_column(nullable=True)
    attempts: Mapped[int] = mapped_column(nullable=False, default=0)

    state: Mapped[JobState] = mapped_column(
        SqlEnum(
            JobState,
            name="job_state",
            native_enum=False,
            values_callable=lambda enum: [member.value for member in enum],
            length=16,
        ),
        default=JobState.READY,
        nullable=False,
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class JobExecution(Base):
    """Proof that a job already ran, keyed for idempotency.

    The unique key is the mechanism: a redelivered job finds its own row and
    returns the recorded outcome instead of acting twice.
    """

    __tablename__ = "job_execution"
    __table_args__ = (UniqueConstraint("tenant_id", "idempotency_key"),)

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True, default=new_id)
    tenant_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False, index=True)
    idempotency_key: Mapped[str] = mapped_column(nullable=False)
    job_type: Mapped[str] = mapped_column(nullable=False)
    outcome: Mapped[str] = mapped_column(nullable=False)

    duplicate_deliveries: Mapped[int] = mapped_column(nullable=False, default=0)
    """Duplicates are counted rather than silently swallowed: a rising number is
    a signal about delivery, not something to hide."""

    completed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
