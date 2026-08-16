"""Identifier generation — D28.

UUIDv7 for normal entities, UUIDv4 for tenants. PostgreSQL 16/18 has no native
UUIDv7 function, so generation happens here.
"""

from __future__ import annotations

import time
from uuid import UUID

import pytest

from adw.domain.ids import (
    new_id,
    new_tenant_id,
    timestamp_ms,
    uuid_version,
)

DRAWS = 2_000


@pytest.mark.unit
def test_new_id_is_uuid_version_7() -> None:
    assert uuid_version(new_id()) == 7


@pytest.mark.unit
def test_new_tenant_id_is_uuid_version_4() -> None:
    """D28: the tenant identifier is the isolation boundary and discloses nothing."""
    assert uuid_version(new_tenant_id()) == 4


@pytest.mark.unit
@pytest.mark.parametrize("factory", [new_id, new_tenant_id])
def test_variant_bits_are_rfc_9562_compliant(factory: object) -> None:
    """Bits 63-62 must be 0b10."""
    assert callable(factory)
    for _ in range(200):
        value = factory()
        assert isinstance(value, UUID)
        assert (value.int >> 62) & 0b11 == 0b10


@pytest.mark.unit
@pytest.mark.parametrize("factory", [new_id, new_tenant_id])
def test_identifiers_are_unique(factory: object) -> None:
    assert callable(factory)
    drawn = {factory() for _ in range(DRAWS)}
    assert len(drawn) == DRAWS


@pytest.mark.unit
def test_uuid7_timestamp_tracks_wall_clock() -> None:
    before = time.time_ns() // 1_000_000
    value = new_id()
    after = time.time_ns() // 1_000_000
    assert before <= timestamp_ms(value) <= after


@pytest.mark.unit
def test_uuid7_values_are_time_ordered_by_bytes() -> None:
    """The index-locality property D28 selects UUIDv7 for.

    Values drawn in distinct milliseconds must sort in creation order by raw
    bytes. Within a single millisecond RFC 9562 leaves ordering to chance, so
    the draws are separated.
    """
    drawn = []
    for _ in range(6):
        drawn.append(new_id())
        time.sleep(0.002)
    assert [v.bytes for v in drawn] == sorted(v.bytes for v in drawn)


@pytest.mark.unit
def test_uuid7_timestamps_are_non_decreasing() -> None:
    stamps = [timestamp_ms(new_id()) for _ in range(500)]
    assert stamps == sorted(stamps)


@pytest.mark.unit
def test_tenant_ids_carry_no_time_ordering() -> None:
    """A v4 tenant id must not leak creation time, so it must not sort by time."""
    drawn = []
    for _ in range(24):
        drawn.append(new_tenant_id())
        time.sleep(0.002)
    assert [v.bytes for v in drawn] != sorted(v.bytes for v in drawn)


@pytest.mark.unit
def test_timestamp_ms_rejects_a_non_v7_identifier() -> None:
    from adw.domain.errors import InvalidIdentifierError

    with pytest.raises(InvalidIdentifierError):
        timestamp_ms(new_tenant_id())


@pytest.mark.unit
def test_uuid7_randomness_differs_within_one_millisecond() -> None:
    """Two ids from the same millisecond must still differ in their random bits."""
    batch = [new_id() for _ in range(50)]
    assert len({v.int & ((1 << 74) - 1) for v in batch}) == len(batch)
