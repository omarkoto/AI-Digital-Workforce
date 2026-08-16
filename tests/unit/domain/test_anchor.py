"""Anchor hashing and entanglement — D20.

Pure functions, no database. The persisted behaviour is proved in
``tests/security/test_anchor_chain.py``.
"""

from __future__ import annotations

import dataclasses
from collections.abc import Callable
from datetime import UTC, datetime
from uuid import UUID

import pytest

from adw.domain.anchor import (
    GENESIS_PREV_ANCHOR_HASH,
    AnchorRecord,
    AnchorRecordHeader,
    seal_anchor,
    verify_anchor_chain,
)
from adw.domain.errors import ChainIntegrityError
from adw.domain.hashing import HASH_ALGORITHM

TENANT_A = UUID("aaaaaaaa-0000-4000-8000-00000000000a")
TENANT_B = UUID("bbbbbbbb-0000-4000-8000-00000000000b")
WHEN = datetime(2026, 3, 14, 9, 41, 7, 123456, tzinfo=UTC)


def header(anchor_seq: int, prev: str | None, tenant: UUID = TENANT_A) -> AnchorRecordHeader:
    return AnchorRecordHeader(
        anchor_seq=anchor_seq,
        prev_anchor_hash=prev,
        tenant_id=tenant,
        tenant_seq=anchor_seq * 10,
        tenant_head_hash="a" * 64,
        anchor_time=WHEN,
        hash_algorithm=HASH_ALGORITHM,
    )


def build(length: int, tenants: tuple[UUID, ...] = (TENANT_A, TENANT_B)) -> list[AnchorRecord]:
    anchors: list[AnchorRecord] = []
    prev: str | None = GENESIS_PREV_ANCHOR_HASH
    for seq in range(1, length + 1):
        anchor = seal_anchor(header(seq, prev, tenants[(seq - 1) % len(tenants)]))
        anchors.append(anchor)
        prev = anchor.anchor_hash
    return anchors


Mutation = Callable[[AnchorRecordHeader], AnchorRecordHeader]

FIELD_MUTATIONS: list[tuple[str, Mutation]] = [
    ("anchor_seq", lambda h: dataclasses.replace(h, anchor_seq=99)),
    ("prev_anchor_hash", lambda h: dataclasses.replace(h, prev_anchor_hash="c" * 64)),
    ("tenant_id", lambda h: dataclasses.replace(h, tenant_id=TENANT_B)),
    ("tenant_seq", lambda h: dataclasses.replace(h, tenant_seq=999)),
    ("tenant_head_hash", lambda h: dataclasses.replace(h, tenant_head_hash="b" * 64)),
    (
        "anchor_time",
        lambda h: dataclasses.replace(
            h, anchor_time=datetime(2026, 3, 14, 9, 41, 7, 123457, tzinfo=UTC)
        ),
    ),
    ("hash_algorithm", lambda h: dataclasses.replace(h, hash_algorithm="sha-512")),
]


@pytest.mark.unit
def test_every_header_field_is_covered_by_this_suite() -> None:
    covered = {name for name, _ in FIELD_MUTATIONS}
    declared = {f.name for f in dataclasses.fields(AnchorRecordHeader)}
    assert covered == declared


@pytest.mark.unit
@pytest.mark.parametrize(("field", "mutate"), FIELD_MUTATIONS, ids=[n for n, _ in FIELD_MUTATIONS])
def test_changing_any_field_changes_the_hash(field: str, mutate: Mutation) -> None:
    base = header(1, GENESIS_PREV_ANCHOR_HASH)
    assert seal_anchor(base).anchor_hash != seal_anchor(mutate(base)).anchor_hash


@pytest.mark.unit
def test_hash_is_deterministic_and_hex() -> None:
    value = seal_anchor(header(1, GENESIS_PREV_ANCHOR_HASH)).anchor_hash
    assert value == seal_anchor(header(1, GENESIS_PREV_ANCHOR_HASH)).anchor_hash
    assert len(value) == 64
    assert all(c in "0123456789abcdef" for c in value)


@pytest.mark.unit
def test_naive_anchor_time_is_rejected() -> None:
    base = header(1, GENESIS_PREV_ANCHOR_HASH)
    naive = dataclasses.replace(base, anchor_time=datetime(2026, 3, 14, 9, 41, 7))  # noqa: DTZ001
    with pytest.raises(ChainIntegrityError):
        seal_anchor(naive)


@pytest.mark.unit
def test_valid_anchor_chain_verifies() -> None:
    verify_anchor_chain(build(6))


@pytest.mark.unit
def test_empty_anchor_chain_verifies() -> None:
    verify_anchor_chain([])


@pytest.mark.unit
def test_tenants_interleave_without_error() -> None:
    """Unlike the record chain, a tenant change between anchors is expected.

    Interleaving is the mechanism: it is what makes one tenant's anchors
    depend on another's.
    """
    anchors = build(4)
    tenants = [a.header.tenant_id for a in anchors]
    assert len(set(tenants)) == 2
    verify_anchor_chain(anchors)


@pytest.mark.unit
def test_altered_anchor_is_detected() -> None:
    """Tamper scenario 4."""
    anchors = build(5)
    anchors[2] = dataclasses.replace(
        anchors[2],
        header=dataclasses.replace(anchors[2].header, tenant_head_hash="f" * 64),
    )
    with pytest.raises(ChainIntegrityError, match="anchor_seq 3"):
        verify_anchor_chain(anchors)


@pytest.mark.unit
def test_removed_anchor_is_detected() -> None:
    anchors = build(5)
    del anchors[2]
    with pytest.raises(ChainIntegrityError):
        verify_anchor_chain(anchors)


@pytest.mark.unit
def test_broken_anchor_link_is_detected() -> None:
    anchors = build(4)
    anchors[2] = dataclasses.replace(
        anchors[2],
        header=dataclasses.replace(anchors[2].header, prev_anchor_hash="d" * 64),
        anchor_hash=anchors[2].anchor_hash,
    )
    with pytest.raises(ChainIntegrityError):
        verify_anchor_chain(anchors)


@pytest.mark.unit
def test_first_anchor_must_carry_the_genesis_marker() -> None:
    with pytest.raises(ChainIntegrityError):
        verify_anchor_chain([seal_anchor(header(1, "e" * 64))])


@pytest.mark.unit
def test_anchor_header_carries_no_tenant_content() -> None:
    """I13: identifiers, sequences, hashes, and time — nothing else."""
    fields = {f.name for f in dataclasses.fields(AnchorRecordHeader)}
    assert fields == {
        "anchor_seq",
        "prev_anchor_hash",
        "tenant_id",
        "tenant_seq",
        "tenant_head_hash",
        "anchor_time",
        "hash_algorithm",
    }
