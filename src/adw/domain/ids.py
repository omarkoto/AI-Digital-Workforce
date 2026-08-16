"""Identifier generation — D28.

UUIDv7 for every entity except one, UUIDv4 for tenant identifiers.

The exception exists because UUIDv7 embeds its creation time, and one identifier
should disclose nothing at all: the tenant identifier is the isolation boundary.
Tenants are also low-volume, so the index locality that motivates v7 buys
nothing there.

PostgreSQL 16 and 18 have no native UUIDv7 function — ``gen_random_uuid()``
produces v4 — so v7 values are generated here, per RFC 9562 §5.7.
"""

from __future__ import annotations

import secrets
import time
import uuid
from typing import Final

from adw.domain.errors import InvalidIdentifierError

_VERSION_7: Final = 7
_VERSION_4: Final = 4
_VARIANT_RFC_9562: Final = 0b10

# RFC 9562 §5.7 field widths, most significant first:
#   unix_ts_ms 48 | ver 4 | rand_a 12 | var 2 | rand_b 62
_TIMESTAMP_SHIFT: Final = 80
_VERSION_SHIFT: Final = 76
_RAND_A_SHIFT: Final = 64
_VARIANT_SHIFT: Final = 62
_RAND_A_BITS: Final = 12
_RAND_B_BITS: Final = 62


def new_id() -> uuid.UUID:
    """Return a fresh UUIDv7.

    Time-ordered to millisecond resolution, with 74 random bits. Ordering within
    a single millisecond is unspecified by RFC 9562 and is not relied upon.
    """
    unix_ts_ms = time.time_ns() // 1_000_000
    value = (
        (unix_ts_ms << _TIMESTAMP_SHIFT)
        | (_VERSION_7 << _VERSION_SHIFT)
        | (secrets.randbits(_RAND_A_BITS) << _RAND_A_SHIFT)
        | (_VARIANT_RFC_9562 << _VARIANT_SHIFT)
        | secrets.randbits(_RAND_B_BITS)
    )
    return uuid.UUID(int=value)


def new_tenant_id() -> uuid.UUID:
    """Return a fresh UUIDv4 for use as a tenant identifier.

    Fully random by design: the tenant identifier must reveal neither creation
    order nor creation time.
    """
    return uuid.uuid4()


def uuid_version(value: uuid.UUID) -> int:
    """Return the RFC 9562 version nibble of ``value``."""
    return (value.int >> _VERSION_SHIFT) & 0xF


def timestamp_ms(value: uuid.UUID) -> int:
    """Return the embedded Unix millisecond timestamp of a UUIDv7.

    Raises:
        InvalidIdentifierError: if ``value`` is not a UUIDv7. A v4 identifier
            carries no timestamp, and returning its leading bits as one would be
            a fabrication.
    """
    version = uuid_version(value)
    if version != _VERSION_7:
        msg = f"expected a UUIDv7 identifier, received version {version}"
        raise InvalidIdentifierError(msg)
    return value.int >> _TIMESTAMP_SHIFT
