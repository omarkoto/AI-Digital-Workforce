"""The only writer of the audit chain — D14, D20, D21.

Every append is one transaction with whatever it records, so a state transition
and its audit entry can never diverge (G2). Nothing else in the codebase inserts
into ``chain_record``.

Order of operations, which is not interchangeable:

1. Canonicalize the payload (D23) and **encrypt** it (D1).
2. Digest the **ciphertext**, over raw bytes (D29).
3. Take the event time from the **database** clock (D21/G6).
4. Seal the header, which covers the digest and never the plaintext (I12).

Redaction belongs before step 1 and arrives with the evidence recorder in Task 7;
what reaches this writer is already whatever it is allowed to keep.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime
from typing import Final
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from adw.domain.canonical import canonicalize
from adw.domain.chain import GENESIS_PREV_HASH, ChainRecordHeader, seal
from adw.domain.hashing import HASH_ALGORITHM, digest_content
from adw.models.audit import EVENT_TIME_ANOMALY, AuditChainHead, AuditChainRecord
from adw.ports.keystore import KeyStore

FIRST_SEQ: Final = 1


def _database_now(session: Session) -> datetime:
    """Return the database transaction timestamp.

    Never the application host's clock: multiple workers mean multiple clocks,
    and a record whose timestamps contradict causality is challengeable in full
    (D21).
    """
    now: datetime = session.execute(select(func.transaction_timestamp())).scalar_one()
    return now


def _locked_head(session: Session, tenant_id: UUID) -> AuditChainHead | None:
    """Return the tenant's chain head, locked for update.

    The lock is what serializes appends within a tenant. Its scope is one row,
    so one tenant's load cannot slow another's.
    """
    return session.scalar(
        select(AuditChainHead).where(AuditChainHead.tenant_id == tenant_id).with_for_update()
    )


def append(
    session: Session,
    *,
    tenant_id: UUID,
    event_type: str,
    actor_id: str,
    payload: Mapping[str, object],
    keystore: KeyStore,
) -> AuditChainRecord:
    """Append one record to a tenant's chain and return it.

    Must be called inside a transaction already scoped to ``tenant_id``, since
    row-level security governs both tables.
    """
    return _append(
        session,
        tenant_id=tenant_id,
        event_type=event_type,
        actor_id=actor_id,
        payload=payload,
        keystore=keystore,
        check_monotonicity=True,
    )


def _append(
    session: Session,
    *,
    tenant_id: UUID,
    event_type: str,
    actor_id: str,
    payload: Mapping[str, object],
    keystore: KeyStore,
    check_monotonicity: bool,
) -> AuditChainRecord:
    head = _locked_head(session, tenant_id)
    event_time = _database_now(session)

    encrypted = keystore.encrypt(tenant_id, canonicalize(payload))
    header = ChainRecordHeader(
        tenant_id=tenant_id,
        seq=FIRST_SEQ if head is None else head.seq + 1,
        prev_hash=GENESIS_PREV_HASH if head is None else head.head_hash,
        event_type=event_type,
        actor_id=actor_id,
        event_time=event_time,
        payload_digest=digest_content(encrypted.ciphertext),
        key_id=encrypted.key_id,
        hash_algorithm=HASH_ALGORITHM,
    )
    sealed = seal(header)

    record = AuditChainRecord(
        tenant_id=tenant_id,
        seq=header.seq,
        prev_hash=header.prev_hash,
        event_type=header.event_type,
        actor_id=header.actor_id,
        event_time=header.event_time,
        payload_ciphertext=encrypted.ciphertext,
        payload_digest=header.payload_digest,
        key_id=header.key_id,
        hash_algorithm=header.hash_algorithm,
        record_hash=sealed.record_hash,
    )
    session.add(record)

    went_backwards = head is not None and event_time < head.last_event_time
    previous_time = head.last_event_time if head is not None else event_time

    if head is None:
        session.add(
            AuditChainHead(
                tenant_id=tenant_id,
                seq=header.seq,
                head_hash=sealed.record_hash,
                last_event_time=event_time,
            )
        )
    else:
        head.seq = header.seq
        head.head_hash = sealed.record_hash
        head.last_event_time = event_time
    session.flush()

    if check_monotonicity and went_backwards:
        # Recorded, not swallowed and not raised: D21 requires backwards time to
        # become an integrity anomaly rather than being silently accepted or
        # silently rejected. The anomaly append skips this check, because its own
        # timestamp is drawn from the same suspect clock and would recurse.
        _append(
            session,
            tenant_id=tenant_id,
            event_type=EVENT_TIME_ANOMALY,
            actor_id="platform:audit_writer",
            payload={
                "observed_event_time": event_time.isoformat(timespec="microseconds"),
                "previous_event_time": previous_time.isoformat(timespec="microseconds"),
                "anomalous_seq": header.seq,
            },
            keystore=keystore,
            check_monotonicity=False,
        )

    return record
