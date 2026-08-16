"""Hashing — D24 and D29.

Two modes that must never be mixed:
  * content        -> SHA-256 over raw bytes
  * structure      -> SHA-256 over RFC 8785 canonical bytes
"""

from __future__ import annotations

import hashlib

import pytest

from adw.domain.canonical import canonicalize
from adw.domain.hashing import (
    HASH_ALGORITHM,
    digest_content,
    digest_structure,
)


@pytest.mark.unit
def test_algorithm_identifier_is_recorded() -> None:
    """D24: the identifier is what keeps a future migration possible."""
    assert HASH_ALGORITHM == "sha-256"


@pytest.mark.unit
def test_content_digest_matches_known_sha256_vector() -> None:
    """NIST vector for the empty string."""
    expected = "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"
    assert digest_content(b"") == expected


@pytest.mark.unit
def test_content_digest_matches_known_sha256_vector_abc() -> None:
    expected = "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad"
    assert digest_content(b"abc") == expected


@pytest.mark.unit
def test_digests_are_lowercase_hex() -> None:
    value = digest_content(b"anything")
    assert len(value) == 64
    assert value == value.lower()
    assert all(c in "0123456789abcdef" for c in value)


@pytest.mark.unit
def test_content_digest_is_over_raw_bytes() -> None:
    assert digest_content(b"payload") == hashlib.sha256(b"payload").hexdigest()


@pytest.mark.unit
def test_structure_digest_is_over_canonical_bytes() -> None:
    value = {"b": 1, "a": 2}
    assert digest_structure(value) == hashlib.sha256(canonicalize(value)).hexdigest()


@pytest.mark.unit
def test_structure_digest_ignores_key_order() -> None:
    assert digest_structure({"b": 1, "a": 2}) == digest_structure({"a": 2, "b": 1})


@pytest.mark.unit
def test_d29_byte_different_but_semantically_equal_content_digests_differ() -> None:
    """The property D29 exists to protect.

    Canonicalising before digesting content would let two byte-different files
    share a digest, which would allow serving a file that is not the one a
    Control Gate approved. Content is digested raw, so these must differ.
    """
    compact = b'{"a":1,"b":2}'
    spaced = b'{ "b" : 2 , "a" : 1 }'
    assert digest_content(compact) != digest_content(spaced)


@pytest.mark.unit
def test_the_same_pair_agrees_once_treated_as_structure() -> None:
    """The mirror of the test above: structure mode is where equivalence belongs."""
    import json

    compact = b'{"a":1,"b":2}'
    spaced = b'{ "b" : 2 , "a" : 1 }'
    assert digest_structure(json.loads(compact)) == digest_structure(json.loads(spaced))


@pytest.mark.unit
def test_content_and_structure_modes_are_not_interchangeable() -> None:
    value = {"a": 1}
    raw = b'{"a":1}'
    assert digest_content(raw) == digest_structure(value)  # canonical form happens to match
    assert digest_content(b'{ "a" : 1 }') != digest_structure(value)
