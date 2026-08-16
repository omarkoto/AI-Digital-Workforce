"""Chain verification against persisted records.

The arithmetic lives in :mod:`adw.domain.chain` and needs no database. This
module only loads rows, converts them to the domain's value objects, and hands
them over — so verification can be reproduced by anyone holding an export, with
none of our infrastructure running.

Verification needs no key. Record hashes cover the ciphertext digest rather than
the plaintext (I12), so a chain still verifies after its tenant key is destroyed.
"""

from __future__ import annotations

from collections.abc import Sequence
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from adw.domain.chain import ChainRecord, ChainRecordHeader, verify_chain
from adw.domain.errors import ChainIntegrityError
from adw.models.audit import AuditChainHead, AuditChainRecord


def _to_domain(row: AuditChainRecord) -> ChainRecord:
    return ChainRecord(
        header=ChainRecordHeader(
            tenant_id=row.tenant_id,
            seq=row.seq,
            prev_hash=row.prev_hash,
            event_type=row.event_type,
            actor_id=row.actor_id,
            event_time=row.event_time,
            payload_digest=row.payload_digest,
            key_id=row.key_id,
            hash_algorithm=row.hash_algorithm,
        ),
        record_hash=row.record_hash,
    )


def load_chain(session: Session, tenant_id: UUID) -> Sequence[ChainRecord]:
    """Return a tenant's chain in sequence order."""
    rows = session.scalars(
        select(AuditChainRecord)
        .where(AuditChainRecord.tenant_id == tenant_id)
        .order_by(AuditChainRecord.seq)
    ).all()
    return [_to_domain(row) for row in rows]


def verify_tenant_chain(session: Session, tenant_id: UUID) -> int:
    """Verify a tenant's whole chain and return the number of records checked.

    Raises:
        ChainIntegrityError: on the first inconsistency, naming the sequence
            number so the failure is locatable.
    """
    records = load_chain(session, tenant_id)
    verify_chain(records)
    _verify_head_agrees(session, tenant_id, records)
    return len(records)


def _verify_head_agrees(session: Session, tenant_id: UUID, records: Sequence[ChainRecord]) -> None:
    """Check the head row against the records it claims to summarise.

    A chain can verify internally while its head has been moved backwards to
    conceal a truncation. Comparing the two catches that locally; catching it
    against an operator who edits both is what the anchor chain in Task 6 adds.
    """
    head = session.scalar(select(AuditChainHead).where(AuditChainHead.tenant_id == tenant_id))
    if head is None:
        if records:
            msg = f"tenant has {len(records)} chain records but no head row"
            raise ChainIntegrityError(msg)
        return

    if not records:
        msg = f"chain head claims seq {head.seq} but no records exist"
        raise ChainIntegrityError(msg)

    last = records[-1]
    if head.seq != last.header.seq:
        msg = f"chain head claims seq {head.seq} but the last record is seq {last.header.seq}"
        raise ChainIntegrityError(msg)
    if head.head_hash != last.record_hash:
        msg = f"chain head hash does not match the record at seq {last.header.seq}"
        raise ChainIntegrityError(msg)
