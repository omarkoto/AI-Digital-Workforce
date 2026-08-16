"""The anchoring job — D20, I13.

Runs under ``adw_anchor``: the one role permitted to read chain heads across
tenants, and permitted to read nothing else. It never touches ``chain_record``,
never sees a payload, and never holds a key. That narrowness is the whole design
— it is a permanent capability rather than break-glass, so it is granted
precisely where needed and nowhere else.

Cadence (P1, proposed default): a tenant is anchored when its chain has advanced
at least ``RECORDS_PER_ANCHOR`` records since its last anchor, or when
``SECONDS_PER_ANCHOR`` have elapsed, whichever comes first. The cadence sets the
detection window: tampering within the current interval is invisible until the
next anchor.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime, timedelta
from typing import Final
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from adw.domain.anchor import GENESIS_PREV_ANCHOR_HASH, AnchorRecordHeader, seal_anchor
from adw.domain.hashing import HASH_ALGORITHM
from adw.models.anchor import ANCHOR_HEAD_ID, AnchorHead, AnchorRecord
from adw.models.audit import AuditChainHead

RECORDS_PER_ANCHOR: Final = 100
SECONDS_PER_ANCHOR: Final = 300


def _database_now(session: Session) -> datetime:
    now: datetime = session.execute(select(func.transaction_timestamp())).scalar_one()
    return now


def _locked_anchor_head(session: Session) -> AnchorHead | None:
    """Return the global anchor head, locked.

    One lock for the whole anchor chain is acceptable where one lock for the
    whole record chain was not: anchoring is a low-volume background job, not a
    step in every state transition.
    """
    return session.scalar(
        select(AnchorHead).where(AnchorHead.id == ANCHOR_HEAD_ID).with_for_update()
    )


def _last_anchor_for(session: Session, tenant_id: UUID) -> AnchorRecord | None:
    return session.scalar(
        select(AnchorRecord)
        .where(AnchorRecord.tenant_id == tenant_id)
        .order_by(AnchorRecord.tenant_seq.desc())
        .limit(1)
    )


def tenants_due(session: Session, *, now: datetime | None = None) -> Sequence[AuditChainHead]:
    """Return the chain heads whose tenants are due for anchoring."""
    moment = now if now is not None else _database_now(session)
    cutoff = moment - timedelta(seconds=SECONDS_PER_ANCHOR)
    due: list[AuditChainHead] = []

    for head in session.scalars(select(AuditChainHead).order_by(AuditChainHead.tenant_id)).all():
        last = _last_anchor_for(session, head.tenant_id)
        if last is None:
            due.append(head)
        elif head.seq > last.tenant_seq and (
            head.seq - last.tenant_seq >= RECORDS_PER_ANCHOR or last.anchor_time <= cutoff
        ):
            due.append(head)
    return due


def anchor_tenant(session: Session, head: AuditChainHead) -> AnchorRecord:
    """Append one anchor for ``head``'s tenant and return it."""
    anchor_head = _locked_anchor_head(session)
    anchor_time = _database_now(session)

    header = AnchorRecordHeader(
        anchor_seq=1 if anchor_head is None else anchor_head.anchor_seq + 1,
        prev_anchor_hash=(
            GENESIS_PREV_ANCHOR_HASH if anchor_head is None else anchor_head.head_hash
        ),
        tenant_id=head.tenant_id,
        tenant_seq=head.seq,
        tenant_head_hash=head.head_hash,
        anchor_time=anchor_time,
        hash_algorithm=HASH_ALGORITHM,
    )
    sealed = seal_anchor(header)

    record = AnchorRecord(
        anchor_seq=header.anchor_seq,
        prev_anchor_hash=header.prev_anchor_hash,
        tenant_id=header.tenant_id,
        tenant_seq=header.tenant_seq,
        tenant_head_hash=header.tenant_head_hash,
        anchor_time=header.anchor_time,
        hash_algorithm=header.hash_algorithm,
        anchor_hash=sealed.anchor_hash,
    )
    session.add(record)

    if anchor_head is None:
        session.add(
            AnchorHead(
                id=ANCHOR_HEAD_ID,
                anchor_seq=header.anchor_seq,
                head_hash=sealed.anchor_hash,
                updated_at=anchor_time,
            )
        )
    else:
        anchor_head.anchor_seq = header.anchor_seq
        anchor_head.head_hash = sealed.anchor_hash
        anchor_head.updated_at = anchor_time
    session.flush()
    return record


def run_anchoring_pass(session: Session, *, now: datetime | None = None) -> int:
    """Anchor every tenant that is due and return how many anchors were written.

    Idempotent in effect rather than by key: a tenant whose chain has not
    advanced since its last anchor is not due, so a repeated pass writes nothing.
    """
    written = 0
    for head in tenants_due(session, now=now):
        anchor_tenant(session, head)
        written += 1
    return written
