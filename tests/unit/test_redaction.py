"""Redaction — D12, I3, G12.

Two properties matter equally. **Recall**: a credential must not survive into an
append-only store, because nothing can take it back afterwards. **Precision**:
over-redacting a genuine financial figure would silently corrupt an artifact,
which is why the patterns are anchored rather than greedy.
"""

from __future__ import annotations

import pytest

from adw.services.redaction import REDACTED, redact


@pytest.mark.unit
def test_a_clean_payload_is_unchanged() -> None:
    payload = {"variance": 1_243_880, "cost_centre": "MKT-01", "period": "2026-03"}
    result = redact(payload)
    assert result.value == payload
    assert result.redacted is False


@pytest.mark.unit
@pytest.mark.parametrize(
    "key",
    ["password", "api_key", "apiKey", "access-key", "SECRET", "authorization", "connection_string"],
)
def test_sensitive_key_names_have_their_values_removed(key: str) -> None:
    result = redact({key: "anything-at-all", "keep": "visible"})
    assert result.value == {key: REDACTED, "keep": "visible"}
    assert result.redacted is True


@pytest.mark.unit
def test_a_sensitive_key_is_redacted_whatever_its_value_looks_like() -> None:
    """The common case: the value itself is unremarkable."""
    result = redact({"password": "hunter2"})
    assert "hunter2" not in str(result.value)


@pytest.mark.unit
@pytest.mark.parametrize(
    ("label", "text"),
    [
        ("bearer", "Authorization header was Bearer abcdefghijklmnopqrstuvwxyz012345"),
        ("aws", "key AKIAIOSFODNN7EXAMPLE was used"),
        ("jwt", "token eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.dozjgNryP4J3jVmNHl0w5N"),
        ("basic", "sent Basic QWxhZGRpbjpvcGVuIHNlc2FtZQ== upstream"),
    ],
)
def test_credential_shapes_are_removed_from_free_text(label: str, text: str) -> None:
    result = redact({"note": text})
    assert REDACTED in str(result.value)
    assert result.redacted is True


@pytest.mark.unit
def test_url_credentials_keep_the_scheme_and_user() -> None:
    """The record should still say which system was reached and as whom."""
    result = redact({"dsn_note": "postgresql://adw_app:sup3rs3cret@db.internal:5432/adw"})
    rendered = str(result.value)
    assert "sup3rs3cret" not in rendered
    assert REDACTED in rendered


@pytest.mark.unit
def test_private_key_blocks_are_removed() -> None:
    block = "-----BEGIN RSA PRIVATE KEY-----\nMIIEow...\n-----END RSA PRIVATE KEY-----"
    result = redact({"body": block})
    assert "MIIEow" not in str(result.value)


@pytest.mark.unit
def test_nested_structures_are_traversed() -> None:
    payload = {
        "request": {"headers": {"authorization": "Bearer abcdefghijklmnopqrstuvwx"}},
        "rows": [{"api_key": "k-123456"}, {"amount": 42}],
    }
    result = redact(payload)
    rendered = str(result.value)
    assert "abcdefghijklmnopqrstuvwx" not in rendered
    assert "k-123456" not in rendered
    assert "42" in rendered


@pytest.mark.unit
def test_findings_name_the_rule_never_the_value() -> None:
    """A redaction report that quotes the secret has not redacted anything."""
    result = redact({"password": "hunter2", "note": "AKIAIOSFODNN7EXAMPLE"})
    joined = " ".join(result.findings)
    assert "hunter2" not in joined
    assert "AKIAIOSFODNN7EXAMPLE" not in joined
    assert any(f.startswith("key:") for f in result.findings)


@pytest.mark.unit
def test_count_reflects_how_many_rules_fired() -> None:
    assert redact({"a": 1}).count == 0
    assert redact({"password": "x"}).count == 1


@pytest.mark.unit
@pytest.mark.parametrize(
    "value",
    [
        {"amount": "1243880.55"},
        {"account": "4000-01-002"},
        {"iso_date": "2026-03-14T09:41:07+00:00"},
        {"digest": "a" * 64},
        {"description": "Marketing overspend against budget for the March close"},
    ],
)
def test_precision_ordinary_financial_content_survives(value: dict[str, str]) -> None:
    """Over-redaction would silently corrupt an artifact."""
    assert redact(value).value == value


@pytest.mark.unit
@pytest.mark.parametrize(
    "key", ["prompt_tokens", "completion_tokens", "total_tokens", "max_output_tokens"]
)
def test_precision_token_counts_are_not_credentials(key: str) -> None:
    """A plural ``tokens`` key is a count, not a secret.

    Redacting these destroyed the per-action cost evidence `PRODUCT.md` §25
    requires, which is over-redaction of exactly the kind this module's docstring
    warns about.
    """
    assert redact({key: 4096}).value == {key: 4096}


@pytest.mark.unit
@pytest.mark.parametrize("key", ["token", "access_token", "refresh_token", "TOKEN"])
def test_the_singular_token_is_still_a_credential(key: str) -> None:
    assert redact({key: "abc"}).value == {key: REDACTED}


@pytest.mark.unit
def test_lists_and_scalars_are_handled() -> None:
    assert redact([1, "two", None]).value == [1, "two", None]
    assert redact(7).value == 7
    assert redact(None).value is None


@pytest.mark.unit
def test_result_is_frozen() -> None:
    result = redact({"a": 1})
    with pytest.raises(AttributeError):
        result.value = {}  # type: ignore[misc]
