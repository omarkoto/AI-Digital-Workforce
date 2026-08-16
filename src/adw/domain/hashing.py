"""Hashing — D24 and D29.

One algorithm, two modes that must never be mixed.

**Content** is digested over its exact raw bytes: artifacts of every type,
evidence blobs, encrypted payloads. Canonicalizing before digesting content
would let two byte-different files share a digest, which would allow serving a
file that is not the one a Control Gate approved. That is an integrity failure,
not an optimisation — and it cannot work at all for XLSX, PDF, or PNG, which
have no canonical JSON form.

**Structures** the platform itself constructs are canonicalized first, so that
the same logical record always produces the same bytes regardless of key order.
In Phase 1 that means the audit chain record header and nothing else.

``HASH_ALGORITHM`` is recorded alongside every digest that is persisted. Without
it stored from the first record, migrating to another algorithm later would be
impossible, because verification could not know which algorithm produced which
record.
"""

from __future__ import annotations

import hashlib
from typing import Final

from adw.domain.canonical import canonicalize

HASH_ALGORITHM: Final = "sha-256"
"""Identifier persisted with every chain record. See D24."""


def digest_content(data: bytes) -> str:
    """Return the lowercase hex SHA-256 of ``data`` exactly as given.

    Use for artifact content, evidence blobs, and ciphertext payloads.
    """
    return hashlib.sha256(data).hexdigest()


def digest_structure(value: object) -> str:
    """Return the lowercase hex SHA-256 of ``value`` in RFC 8785 canonical form.

    Use only for structures the platform builds for hashing. Never use it on
    content that a user supplied or that will be served back.
    """
    return hashlib.sha256(canonicalize(value)).hexdigest()
