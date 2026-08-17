"""Rebuild an execution's narrative from persisted state — CLAUDE.md §1.

"Every one of those twelve steps must be observable in persisted state. If a step
cannot be reconstructed from the database after the fact, it did not happen in a
way this platform accepts."

This module is that claim, executable. It reads rows and returns a narrative. It
needs no running service, no original input files, no model, and no key — the
chain is ordered by sequence (I11) and the events describe themselves.

Where a payload is unreadable because the tenant key was destroyed, the narrative
still lists the event, its actor, and its time. Erasure removes content; it never
removes the record that something happened.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from adw.models.audit import AuditChainRecord
from adw.ports.keystore import EncryptedPayload, KeyStore, KeyUnavailableError


@dataclass(frozen=True, slots=True)
class NarrativeEntry:
    """One line of the reconstructed story."""

    seq: int
    event_type: str
    actor_id: str
    event_time: datetime
    detail: str

    def render(self) -> str:
        stamp = self.event_time.isoformat(timespec="seconds")
        return f"{self.seq:>4}  {stamp}  {self.event_type:<28} {self.actor_id:<32} {self.detail}"


def reconstruct(
    session: Session,
    *,
    tenant_id: UUID,
    keystore: KeyStore | None = None,
) -> Sequence[NarrativeEntry]:
    """Return a tenant's execution narrative, ordered by the chain sequence.

    Ordered by ``seq`` rather than by timestamp: the sequence is the
    authoritative order (I11), and a timestamp is evidence of when, not of order.

    ``keystore`` is optional. Without it — or after key destruction — the
    narrative still lists every event, with its detail marked unreadable.
    """
    rows = session.scalars(
        select(AuditChainRecord)
        .where(AuditChainRecord.tenant_id == tenant_id)
        .order_by(AuditChainRecord.seq)
    ).all()

    entries: list[NarrativeEntry] = []
    for row in rows:
        detail = "<encrypted; no key supplied>"
        if keystore is not None:
            try:
                payload = keystore.decrypt(
                    tenant_id,
                    EncryptedPayload(ciphertext=row.payload_ciphertext, key_id=row.key_id),
                )
                detail = payload.decode("utf-8")
            except KeyUnavailableError:
                detail = "<unreadable; tenant key destroyed>"
        entries.append(
            NarrativeEntry(
                seq=row.seq,
                event_type=row.event_type,
                actor_id=row.actor_id,
                event_time=row.event_time,
                detail=detail,
            )
        )
    return entries


def render(entries: Sequence[NarrativeEntry]) -> str:
    """Render a narrative as text, for an export or a support conversation."""
    return "\n".join(entry.render() for entry in entries)


def event_sequence(entries: Sequence[NarrativeEntry]) -> list[str]:
    """Return just the event types, in order — the shape of what happened."""
    return [entry.event_type for entry in entries]
