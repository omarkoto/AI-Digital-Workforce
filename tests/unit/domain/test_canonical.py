"""RFC 8785 canonicalization — D23.

Verified against the official test vectors from
github.com/cyberphone/json-canonicalization, committed under
tests/fixtures/rfc8785 so the suite pins them rather than fetching at run time.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from adw.domain.canonical import canonicalize
from adw.domain.errors import CanonicalizationFailedError

VECTORS = Path(__file__).resolve().parents[2] / "fixtures" / "rfc8785"
VECTOR_NAMES = ["arrays", "french", "structures", "unicode", "values", "weird"]


@pytest.mark.unit
@pytest.mark.parametrize("name", VECTOR_NAMES)
def test_official_rfc8785_vector(name: str) -> None:
    source = json.loads((VECTORS / f"{name}.input.json").read_text(encoding="utf-8"))
    expected = (VECTORS / f"{name}.output.json").read_bytes()
    assert canonicalize(source) == expected


@pytest.mark.unit
def test_all_vectors_were_committed() -> None:
    """Guards against a silently empty fixture directory making the suite vacuous."""
    for name in VECTOR_NAMES:
        assert (VECTORS / f"{name}.input.json").is_file()
        assert (VECTORS / f"{name}.output.json").is_file()


@pytest.mark.unit
def test_key_order_does_not_affect_output() -> None:
    """The property the audit chain depends on."""
    assert canonicalize({"b": 1, "a": 2}) == canonicalize({"a": 2, "b": 1})


@pytest.mark.unit
def test_output_is_utf8_bytes() -> None:
    result = canonicalize({"greeting": "héllo"})
    assert isinstance(result, bytes)
    assert result.decode("utf-8")


@pytest.mark.unit
def test_canonicalization_is_deterministic_across_calls() -> None:
    value = {"z": [1, 2, {"y": None, "x": True}], "a": "text"}
    assert canonicalize(value) == canonicalize(value)


@pytest.mark.unit
def test_unserialisable_value_raises_a_domain_error() -> None:
    """Library failures surface as domain errors, not as third-party types."""
    with pytest.raises(CanonicalizationFailedError):
        canonicalize({"bad": float("nan")})


@pytest.mark.unit
def test_unsupported_python_type_raises_a_domain_error() -> None:
    with pytest.raises(CanonicalizationFailedError):
        canonicalize({"bad": object()})
