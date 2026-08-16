"""The per-tenant audit chain — D14, D20, D21.

Two tables. ``chain_record`` holds the append-only records; ``chain_head`` holds
one row per tenant naming the current sequence and hash, and is the row an
append locks so that writes serialize per tenant rather than platform-wide.

Neither is mutable through the application: the migration revokes UPDATE and
DELETE from the runtime role and installs a trigger, because an audit trail
anyone can rewrite is not an audit trail (D14).

``chain_head`` is one of the two structures I13 permits to be read across
tenants — the anchoring role reads head hashes and nothing else. That is granted
by a role-scoped policy rather than by weakening the tenant policy.
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import DateTime, ForeignKey, LargeBinary, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column

from adw.domain.ids import new_id
from adw.models.base import Base, TenantScopedMixin

PLATFORM_TENANT_ID = UUID("00000000-0000-0000-0000-000000000000")
"""The reserved chain for events belonging to no tenant.

Deliberately not a valid UUIDv4, so it can never collide with a real tenant
identifier issued under D28.
"""

EVENT_TIME_ANOMALY = "chain.time_anomaly"
"""Emitted when an append observes time moving backwards (D21).

Recorded as its own chain record rather than a flag, because the hash input is
fixed by D20 and adding a field would change every historical hash. The anomaly
record is therefore tamper-evident like any other.
"""


class AuditChainRecord(Base, TenantScopedMixin):
    """One append-only entry in a tenant's chain."""

    __tablename__ = "chain_record"
    __table_args__ = (UniqueConstraint("tenant_id", "seq"),)

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True, default=new_id)
    seq: Mapped[int] = mapped_column(nullable=False)
    """Per-tenant, gap-free, and **the authoritative order of events** (I11).
    The timestamp is evidence of when; the sequence is evidence of order."""

    prev_hash: Mapped[str | None] = mapped_column(nullable=True)
    """NULL marks the genesis record — "there is no previous record"."""

    event_type: Mapped[str] = mapped_column(nullable=False)
    actor_id: Mapped[str] = mapped_column(nullable=False)
    event_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    payload_ciphertext: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    payload_digest: Mapped[str] = mapped_column(nullable=False)
    """Raw-byte digest of the ciphertext (D29). The record hash covers this, not
    the plaintext, so verification survives key destruction (I12)."""

    key_id: Mapped[str] = mapped_column(nullable=False)
    hash_algorithm: Mapped[str] = mapped_column(nullable=False)
    record_hash: Mapped[str] = mapped_column(nullable=False)


class AuditChainHead(Base):
    """The current head of one tenant's chain.

    Appends take ``SELECT ... FOR UPDATE`` on this row, so contention is scoped
    to a single tenant. A global head would serialize every transition across
    every tenant — and because a transition and its audit record share one
    transaction (G2), that would couple all tenants at exactly the moment
    `PRODUCT.md` §15 says load spikes.
    """

    __tablename__ = "chain_head"

    tenant_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("tenant.id", ondelete="RESTRICT"),
        primary_key=True,
    )
    seq: Mapped[int] = mapped_column(nullable=False)
    head_hash: Mapped[str] = mapped_column(nullable=False)
    last_event_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
