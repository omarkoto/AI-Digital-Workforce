"""The anchor chain — D20.

Per-tenant chains detect modification in the middle. They do **not** detect
truncation or wholesale rewrite: an operator with write access can recompute
every hash from any point forward and produce something internally consistent
and indistinguishable from the original. Anchoring is what closes that.

An anchor record captures one tenant chain's head at a moment. Anchor records
chain to **each other across all tenants**, so rewriting one tenant's history
past its last anchor requires rewriting every subsequent anchor — including
anchors belonging to other tenants. That entanglement lives here, in a layer
carrying only identifiers and hashes, so no tenant record ever enters a shared
chain.

Hash input, following D20 and D23 exactly as the record chain does — a JSON
object, canonicalized with RFC 8785, binary values as lowercase hex:

    anchor_hash = SHA256( JCS{ prev_anchor_hash, anchor_seq, tenant_id,
                               tenant_seq, tenant_head_hash, anchor_time,
                               hash_algorithm } )
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Final
from uuid import UUID

from adw.domain.errors import ChainIntegrityError
from adw.domain.hashing import HASH_ALGORITHM, digest_structure

GENESIS_PREV_ANCHOR_HASH: Final[str | None] = None
"""Marker for the first anchor. JSON ``null`` — there is no previous anchor."""

_FIRST_ANCHOR_SEQ: Final = 1


@dataclass(frozen=True, slots=True)
class AnchorRecordHeader:
    """The hashed portion of one anchor record.

    Carries no payload and no tenant content — only which tenant, how far its
    chain had advanced, and what its head hash was.
    """

    anchor_seq: int
    prev_anchor_hash: str | None
    tenant_id: UUID
    tenant_seq: int
    tenant_head_hash: str
    anchor_time: datetime
    hash_algorithm: str = HASH_ALGORITHM


@dataclass(frozen=True, slots=True)
class AnchorRecord:
    """A sealed anchor header together with the hash binding it."""

    header: AnchorRecordHeader
    anchor_hash: str


def _encode_time(value: datetime) -> str:
    if value.tzinfo is None or value.utcoffset() is None:
        msg = "anchor_time must be timezone-aware; a naive timestamp cannot be sealed"
        raise ChainIntegrityError(msg)
    return value.astimezone(UTC).isoformat(timespec="microseconds")


def _hash_input(header: AnchorRecordHeader) -> dict[str, object]:
    return {
        "prev_anchor_hash": header.prev_anchor_hash,
        "anchor_seq": header.anchor_seq,
        "tenant_id": str(header.tenant_id),
        "tenant_seq": header.tenant_seq,
        "tenant_head_hash": header.tenant_head_hash,
        "anchor_time": _encode_time(header.anchor_time),
        "hash_algorithm": header.hash_algorithm,
    }


def compute_anchor_hash(header: AnchorRecordHeader) -> str:
    """Return the lowercase hex hash binding ``header`` to its predecessor."""
    return digest_structure(_hash_input(header))


def seal_anchor(header: AnchorRecordHeader) -> AnchorRecord:
    """Bind ``header`` to its computed hash."""
    return AnchorRecord(header=header, anchor_hash=compute_anchor_hash(header))


def verify_anchor_chain(anchors: Sequence[AnchorRecord]) -> None:
    """Verify the anchor chain's own entanglement.

    Anchors from different tenants interleave in one sequence by design, so a
    tenant change between adjacent records is expected rather than an error —
    unlike the record chain, where it would mean a mixed sequence.

    Raises:
        ChainIntegrityError: on the first inconsistency, naming the anchor
            sequence number.
    """
    previous: AnchorRecord | None = None

    for anchor in anchors:
        header = anchor.header
        expected = compute_anchor_hash(header)
        if expected != anchor.anchor_hash:
            msg = (
                f"anchor hash mismatch at anchor_seq {header.anchor_seq}: "
                "header does not produce stored hash"
            )
            raise ChainIntegrityError(msg)

        if previous is None:
            if (
                header.anchor_seq == _FIRST_ANCHOR_SEQ
                and header.prev_anchor_hash != GENESIS_PREV_ANCHOR_HASH
            ):
                msg = (
                    f"anchor_seq {header.anchor_seq} is the first anchor but does "
                    "not carry the genesis marker"
                )
                raise ChainIntegrityError(msg)
        else:
            if header.anchor_seq != previous.header.anchor_seq + 1:
                msg = (
                    f"anchor sequence break at anchor_seq {header.anchor_seq}: "
                    f"expected {previous.header.anchor_seq + 1}, anchors may have been removed"
                )
                raise ChainIntegrityError(msg)
            if header.prev_anchor_hash != previous.anchor_hash:
                msg = (
                    f"broken anchor link at anchor_seq {header.anchor_seq}: "
                    "prev_anchor_hash does not match the predecessor"
                )
                raise ChainIntegrityError(msg)

        previous = anchor
