"""Verification against the anchor chain — D20.

This is the layer that makes the tamper-evidence claim true rather than
aspirational. A per-tenant chain alone catches modification in the middle; it
cannot catch truncation or wholesale rewrite, because an operator who recomputes
every hash from a point forward produces something internally consistent.

Two checks, and both are needed:

* :func:`verify_anchor_chain_integrity` — the anchor chain's own entanglement.
* :func:`verify_tenant_against_anchors` — each anchored head hash still matches
  the tenant record at that sequence.

Rewriting a tenant's history changes its record hashes, so the anchored head no
longer matches. Repairing that requires editing the anchor, which breaks the
anchor chain, which requires rewriting every later anchor — including other
tenants'. That is the cost anchoring imposes.
"""

from __future__ import annotations

from collections.abc import Sequence
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from adw.domain.anchor import AnchorRecord as DomainAnchor
from adw.domain.anchor import AnchorRecordHeader, verify_anchor_chain
from adw.domain.errors import ChainIntegrityError
from adw.models.anchor import AnchorRecord
from adw.models.audit import AuditChainRecord


def _to_domain(row: AnchorRecord) -> DomainAnchor:
    return DomainAnchor(
        header=AnchorRecordHeader(
            anchor_seq=row.anchor_seq,
            prev_anchor_hash=row.prev_anchor_hash,
            tenant_id=row.tenant_id,
            tenant_seq=row.tenant_seq,
            tenant_head_hash=row.tenant_head_hash,
            anchor_time=row.anchor_time,
            hash_algorithm=row.hash_algorithm,
        ),
        anchor_hash=row.anchor_hash,
    )


def load_anchor_chain(session: Session) -> Sequence[DomainAnchor]:
    """Return every anchor in global sequence order."""
    rows = session.scalars(select(AnchorRecord).order_by(AnchorRecord.anchor_seq)).all()
    return [_to_domain(row) for row in rows]


def verify_anchor_chain_integrity(session: Session) -> int:
    """Verify the anchor chain's entanglement and return the anchor count.

    Raises:
        ChainIntegrityError: on the first inconsistency.
    """
    anchors = load_anchor_chain(session)
    verify_anchor_chain(anchors)
    return len(anchors)


def verify_tenant_against_anchors(session: Session, tenant_id: UUID) -> int:
    """Check a tenant's chain against every anchor taken of it.

    Returns the number of anchors checked.

    Raises:
        ChainIntegrityError: if a record an anchor covered is missing
            (truncation) or no longer produces the anchored hash (rewrite).
    """
    anchors = session.scalars(
        select(AnchorRecord)
        .where(AnchorRecord.tenant_id == tenant_id)
        .order_by(AnchorRecord.tenant_seq)
    ).all()

    for anchor in anchors:
        record = session.scalar(
            select(AuditChainRecord).where(
                AuditChainRecord.tenant_id == tenant_id,
                AuditChainRecord.seq == anchor.tenant_seq,
            )
        )
        if record is None:
            msg = (
                f"anchor {anchor.anchor_seq} covers seq {anchor.tenant_seq} but no such "
                "record exists: the chain was truncated below an anchored point"
            )
            raise ChainIntegrityError(msg)
        if record.record_hash != anchor.tenant_head_hash:
            msg = (
                f"anchor {anchor.anchor_seq} recorded a different hash for seq "
                f"{anchor.tenant_seq}: the chain was rewritten below an anchored point"
            )
            raise ChainIntegrityError(msg)

    return len(anchors)
