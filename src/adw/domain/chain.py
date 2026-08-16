"""Per-tenant audit chain hashing — D20.

Pure functions. No clock, no database, no key store: every input is supplied by
the caller, so a record's hash is fully determined by its header and a chain can
be verified anywhere, including by a party running none of our infrastructure.

The hash covers a *digest of the encrypted payload*, never the payload itself
(I12). That is what lets a chain still verify after crypto-shredding under D1:
destroying a tenant key removes readability, not verifiability.

Hash input, per D20 and D23 — assembled as a JSON object, canonicalized with
RFC 8785, binary values as lowercase hex:

    record_hash = SHA256( JCS{ prev_hash, tenant_id, seq, event_type,
                               actor_id, event_time, payload_digest,
                               hash_algorithm, key_id } )
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Final
from uuid import UUID

from adw.domain.errors import ChainIntegrityError
from adw.domain.hashing import HASH_ALGORITHM, digest_structure

GENESIS_PREV_HASH: Final[str | None] = None
"""Marker for the first record in a tenant's chain.

Represented as JSON ``null`` — "there is no previous record" — rather than a
sentinel string, so the absence is explicit in the canonical bytes. This is a
representation choice, not a business rule.
"""

_FIRST_SEQ: Final = 1


@dataclass(frozen=True, slots=True)
class ChainRecordHeader:
    """The hashed portion of one audit chain record.

    Deliberately carries no payload field. Sealing requires no plaintext and no
    key, which is the property that keeps verification possible after erasure.
    """

    tenant_id: UUID
    seq: int
    prev_hash: str | None
    event_type: str
    actor_id: str
    event_time: datetime
    payload_digest: str
    key_id: str
    hash_algorithm: str = HASH_ALGORITHM


@dataclass(frozen=True, slots=True)
class ChainRecord:
    """A sealed header: the record together with the hash that binds it."""

    header: ChainRecordHeader
    record_hash: str


def _encode_event_time(value: datetime) -> str:
    """Return a fixed-width UTC representation of ``value``.

    A naive datetime is rejected rather than assumed to be UTC. Guessing a zone
    would make the resulting hash a statement about a time nobody asserted.
    """
    if value.tzinfo is None or value.utcoffset() is None:
        msg = "event_time must be timezone-aware; a naive timestamp cannot be sealed"
        raise ChainIntegrityError(msg)
    return value.astimezone(UTC).isoformat(timespec="microseconds")


def _hash_input(header: ChainRecordHeader) -> dict[str, object]:
    """Return the JSON object that is canonicalized and hashed.

    Key order here is irrelevant — RFC 8785 sorts them — but every field of the
    header must appear, or that field would be unprotected by the hash.
    """
    return {
        "prev_hash": header.prev_hash,
        "tenant_id": str(header.tenant_id),
        "seq": header.seq,
        "event_type": header.event_type,
        "actor_id": header.actor_id,
        "event_time": _encode_event_time(header.event_time),
        "payload_digest": header.payload_digest,
        "hash_algorithm": header.hash_algorithm,
        "key_id": header.key_id,
    }


def compute_record_hash(header: ChainRecordHeader) -> str:
    """Return the lowercase hex hash binding ``header`` to its predecessor."""
    return digest_structure(_hash_input(header))


def seal(header: ChainRecordHeader) -> ChainRecord:
    """Bind ``header`` to its computed hash."""
    return ChainRecord(header=header, record_hash=compute_record_hash(header))


def verify_chain(records: Sequence[ChainRecord]) -> None:
    """Verify a contiguous slice of one tenant's chain.

    Checks, in order, for each record: that its stored hash matches its header,
    that it belongs to the same tenant as its predecessor, that its sequence
    follows contiguously, and that it links to the predecessor's hash. A slice
    beginning at sequence 1 must additionally carry the genesis marker.

    Raises:
        ChainIntegrityError: on the first inconsistency found, naming the
            sequence number so the failure is locatable.
    """
    previous: ChainRecord | None = None

    for record in records:
        header = record.header
        expected = compute_record_hash(header)
        if expected != record.record_hash:
            msg = f"record hash mismatch at seq {header.seq}: header does not produce stored hash"
            raise ChainIntegrityError(msg)

        if previous is None:
            if header.seq == _FIRST_SEQ and header.prev_hash != GENESIS_PREV_HASH:
                msg = f"seq {header.seq} is the first record but does not carry the genesis marker"
                raise ChainIntegrityError(msg)
        else:
            if header.tenant_id != previous.header.tenant_id:
                msg = (
                    f"tenant changed at seq {header.seq}: chains are per-tenant and "
                    "a mixed sequence is not a chain"
                )
                raise ChainIntegrityError(msg)
            if header.seq != previous.header.seq + 1:
                msg = (
                    f"sequence break at seq {header.seq}: expected "
                    f"{previous.header.seq + 1}, records may have been removed"
                )
                raise ChainIntegrityError(msg)
            if header.prev_hash != previous.record_hash:
                msg = f"broken link at seq {header.seq}: prev_hash does not match the predecessor"
                raise ChainIntegrityError(msg)

        previous = record
