"""Audit chain hashing — D20.

Pure functions only. No database, no clock, no I/O: every input is supplied by
the caller so the result is fully determined and fully testable.
"""

from __future__ import annotations

import dataclasses
from collections.abc import Callable
from datetime import UTC, datetime
from uuid import UUID

import pytest

from adw.domain.chain import (
    GENESIS_PREV_HASH,
    ChainRecord,
    ChainRecordHeader,
    seal,
    verify_chain,
)
from adw.domain.errors import ChainIntegrityError
from adw.domain.hashing import HASH_ALGORITHM

TENANT = UUID("6f9619ff-8b86-d011-b42d-00cf4fc964ff")
WHEN = datetime(2026, 3, 14, 9, 41, 7, 123456, tzinfo=UTC)


def header(seq: int, prev_hash: str | None) -> ChainRecordHeader:
    return ChainRecordHeader(
        tenant_id=TENANT,
        seq=seq,
        prev_hash=prev_hash,
        event_type="task.transitioned",
        actor_id="agent:data-preparation",
        event_time=WHEN,
        payload_digest="a" * 64,
        key_id="tenant-key-1",
        hash_algorithm=HASH_ALGORITHM,
    )


def build_chain(length: int) -> list[ChainRecord]:
    records: list[ChainRecord] = []
    prev: str | None = GENESIS_PREV_HASH
    for seq in range(1, length + 1):
        record = seal(header(seq, prev))
        records.append(record)
        prev = record.record_hash
    return records


@pytest.mark.unit
def test_hash_is_deterministic() -> None:
    assert seal(header(1, GENESIS_PREV_HASH)).record_hash == (
        seal(header(1, GENESIS_PREV_HASH)).record_hash
    )


@pytest.mark.unit
def test_hash_is_lowercase_hex() -> None:
    value = seal(header(1, GENESIS_PREV_HASH)).record_hash
    assert len(value) == 64
    assert all(c in "0123456789abcdef" for c in value)


Mutation = Callable[[ChainRecordHeader], ChainRecordHeader]

FIELD_MUTATIONS: list[tuple[str, Mutation]] = [
    ("seq", lambda h: dataclasses.replace(h, seq=2)),
    ("event_type", lambda h: dataclasses.replace(h, event_type="task.other")),
    ("actor_id", lambda h: dataclasses.replace(h, actor_id="agent:someone-else")),
    (
        "event_time",
        lambda h: dataclasses.replace(
            h, event_time=datetime(2026, 3, 14, 9, 41, 7, 123457, tzinfo=UTC)
        ),
    ),
    ("payload_digest", lambda h: dataclasses.replace(h, payload_digest="b" * 64)),
    ("key_id", lambda h: dataclasses.replace(h, key_id="tenant-key-2")),
    ("hash_algorithm", lambda h: dataclasses.replace(h, hash_algorithm="sha-512")),
    (
        "tenant_id",
        lambda h: dataclasses.replace(h, tenant_id=UUID("00000000-0000-4000-8000-000000000001")),
    ),
    ("prev_hash", lambda h: dataclasses.replace(h, prev_hash="c" * 64)),
]


@pytest.mark.unit
def test_every_header_field_is_covered_by_this_suite() -> None:
    """A new header field must not slip in unhashed and untested."""
    covered = {name for name, _ in FIELD_MUTATIONS}
    declared = {f.name for f in dataclasses.fields(ChainRecordHeader)}
    assert covered == declared


@pytest.mark.unit
@pytest.mark.parametrize(("field", "mutate"), FIELD_MUTATIONS, ids=[n for n, _ in FIELD_MUTATIONS])
def test_changing_any_single_field_changes_the_hash(field: str, mutate: Mutation) -> None:
    """Every hashed input must actually be covered by the hash."""
    base = header(1, GENESIS_PREV_HASH)
    assert seal(base).record_hash != seal(mutate(base)).record_hash


@pytest.mark.unit
def test_naive_datetime_is_rejected() -> None:
    """D21 stores UTC; an ambiguous timestamp must never enter the hash."""
    base = header(1, GENESIS_PREV_HASH)
    naive = dataclasses.replace(base, event_time=datetime(2026, 3, 14, 9, 41, 7))  # noqa: DTZ001
    with pytest.raises(ChainIntegrityError):
        seal(naive)


@pytest.mark.unit
def test_equivalent_instants_in_different_zones_hash_alike() -> None:
    """The same instant is the same instant, however it was expressed."""
    from datetime import timedelta, timezone

    base = header(1, GENESIS_PREV_HASH)
    shifted = dataclasses.replace(
        base,
        event_time=WHEN.astimezone(timezone(timedelta(hours=2))),
    )
    assert seal(base).record_hash == seal(shifted).record_hash


@pytest.mark.unit
def test_valid_chain_verifies() -> None:
    verify_chain(build_chain(5))


@pytest.mark.unit
def test_single_record_chain_verifies() -> None:
    verify_chain(build_chain(1))


@pytest.mark.unit
def test_empty_chain_verifies() -> None:
    verify_chain([])


@pytest.mark.unit
def test_mid_chain_modification_is_detected() -> None:
    """Scenario 1 of the tamper-detection requirement."""
    records = build_chain(5)
    tampered = dataclasses.replace(
        records[2],
        header=dataclasses.replace(records[2].header, payload_digest="f" * 64),
    )
    records[2] = tampered
    with pytest.raises(ChainIntegrityError, match="seq 3"):
        verify_chain(records)


@pytest.mark.unit
def test_broken_link_is_detected() -> None:
    records = build_chain(4)
    records[2] = dataclasses.replace(
        records[2],
        header=dataclasses.replace(records[2].header, prev_hash="d" * 64),
        record_hash=records[2].record_hash,
    )
    with pytest.raises(ChainIntegrityError):
        verify_chain(records)


@pytest.mark.unit
def test_removed_record_is_detected() -> None:
    """Deleting from the middle breaks both sequence contiguity and the link."""
    records = build_chain(5)
    del records[2]
    with pytest.raises(ChainIntegrityError):
        verify_chain(records)


@pytest.mark.unit
def test_forged_record_hash_is_detected() -> None:
    records = build_chain(3)
    records[1] = dataclasses.replace(records[1], record_hash="0" * 64)
    with pytest.raises(ChainIntegrityError):
        verify_chain(records)


@pytest.mark.unit
def test_first_record_must_carry_the_genesis_marker() -> None:
    with pytest.raises(ChainIntegrityError):
        verify_chain([seal(header(1, "e" * 64))])


@pytest.mark.unit
def test_records_from_two_tenants_cannot_form_one_chain() -> None:
    """Chains are per-tenant (D20); a mixed sequence is not a chain."""
    records = build_chain(3)
    foreign = dataclasses.replace(
        records[1].header, tenant_id=UUID("00000000-0000-4000-8000-00000000abcd")
    )
    records[1] = seal(foreign)
    with pytest.raises(ChainIntegrityError):
        verify_chain(records)


@pytest.mark.unit
def test_hash_covers_the_payload_digest_not_the_payload() -> None:
    """I12: verification must survive key destruction.

    The header holds only a digest of the encrypted payload. Sealing therefore
    needs no plaintext and no key, which is what lets a chain still verify after
    crypto-shredding under D1.
    """
    fields = {f.name for f in dataclasses.fields(ChainRecordHeader)}
    assert "payload_digest" in fields
    assert not fields & {"payload", "plaintext", "payload_ciphertext"}
