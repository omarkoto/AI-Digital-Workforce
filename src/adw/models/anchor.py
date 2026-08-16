"""The anchor chain, persisted — D20, I13.

Platform-scoped, not tenant-scoped: these rows carry identifiers, sequence
numbers, hashes, and timestamps, and never any tenant content. They are one of
the three structures invariant I13 places outside tenant scope.

Deliberately **not tenant-readable**. Access is restricted to the anchoring role
and the auditor role. Exposing them to tenants would leak the existence, volume,
and timing of every other tenant's activity — which is exactly the metadata leak
that ruled out a single global record chain in D20.
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column

from adw.domain.ids import new_id
from adw.models.base import Base

ANCHOR_HEAD_ID = 1
"""The anchor chain has exactly one head, pinned by a CHECK constraint."""


class AnchorRecord(Base):
    """One capture of one tenant chain's head, entangled with every other."""

    __tablename__ = "anchor_record"
    __table_args__ = (
        UniqueConstraint("anchor_seq"),
        UniqueConstraint("tenant_id", "tenant_seq"),
        CheckConstraint("anchor_seq >= 1", name="anchor_seq_positive"),
    )

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True, default=new_id)

    anchor_seq: Mapped[int] = mapped_column(nullable=False)
    """Global across all tenants. This is what entangles them: rewriting one
    tenant's anchors requires rewriting every later anchor, whoever owns it."""

    prev_anchor_hash: Mapped[str | None] = mapped_column(nullable=True)

    tenant_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("tenant.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    """An identifier, not tenant content. P2 remains open on whether this should
    become a salted pseudonym; it is readable only by the anchoring and auditor
    roles either way."""

    tenant_seq: Mapped[int] = mapped_column(nullable=False)
    tenant_head_hash: Mapped[str] = mapped_column(nullable=False)
    anchor_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    hash_algorithm: Mapped[str] = mapped_column(nullable=False)
    anchor_hash: Mapped[str] = mapped_column(nullable=False)


class AnchorHead(Base):
    """The single head of the global anchor chain."""

    __tablename__ = "anchor_head"
    __table_args__ = (CheckConstraint(f"id = {ANCHOR_HEAD_ID}", name="single_row"),)

    id: Mapped[int] = mapped_column(primary_key=True, default=ANCHOR_HEAD_ID)
    anchor_seq: Mapped[int] = mapped_column(nullable=False)
    head_hash: Mapped[str] = mapped_column(nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
