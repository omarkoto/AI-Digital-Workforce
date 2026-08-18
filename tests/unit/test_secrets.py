"""The secret store port and its development adapter — `CLAUDE.md` §4.

The absolute prohibition under test: **never expose a secret to an LLM.** These
tests check the mechanics that make it hard to break by accident — a value that
will not render itself, a reference syntax narrow enough to be safe in content,
and an error that names the reference rather than the secret.
"""

from __future__ import annotations

import pytest

from adw.adapters.secrets_env import EnvironmentSecretStore, environment_variable_for
from adw.ports.secrets import (
    InvalidSecretReferenceError,
    SecretNotFoundError,
    SecretStore,
    SecretValue,
    validate_reference,
)

pytestmark = pytest.mark.unit

REFERENCE = "secret://ollama/api-key"
VALUE = "sk-not-a-real-credential-000"


@pytest.fixture
def store(env_settings: None, monkeypatch: pytest.MonkeyPatch) -> EnvironmentSecretStore:
    from adw import config

    monkeypatch.setenv("ADW_APP_ENV", "dev")
    monkeypatch.setenv("ADW_SECRET_OLLAMA_API_KEY", VALUE)
    config.get_settings.cache_clear()
    return EnvironmentSecretStore()


# --- SecretValue refuses to render ------------------------------------------


def test_a_secret_never_renders_itself() -> None:
    """An accidental f-string, log line, or traceback must yield nothing useful."""
    secret = SecretValue(REFERENCE, VALUE)
    assert VALUE not in repr(secret)
    assert VALUE not in str(secret)
    assert VALUE not in f"{secret}"
    assert VALUE not in "{}".format(secret)  # noqa: UP032 — the point is the old form too


def test_a_secret_in_a_container_still_does_not_render() -> None:
    """Dicts and lists render their members with repr, which is how a secret
    reaches evidence by accident."""
    secret = SecretValue(REFERENCE, VALUE)
    assert VALUE not in repr({"credential": secret})
    assert VALUE not in repr([secret])


def test_the_reference_is_safe_to_show() -> None:
    """The name is what goes in a descriptor, a log, and evidence."""
    secret = SecretValue(REFERENCE, VALUE)
    assert secret.reference == REFERENCE
    assert REFERENCE in repr(secret)


def test_revealing_takes_an_explicit_call() -> None:
    """Greppable in review, which is the whole point of not using an attribute."""
    assert SecretValue(REFERENCE, VALUE).reveal() == VALUE


def test_a_secret_has_no_dict_to_dump() -> None:
    """__slots__, so a generic serializer finds nothing to walk."""
    with pytest.raises(AttributeError):
        SecretValue(REFERENCE, VALUE).__dict__  # noqa: B018


# --- Reference syntax -------------------------------------------------------


@pytest.mark.parametrize(
    "reference",
    ["secret://ollama/api-key", "secret://db", "secret://a/b/c", "secret://x_1/y-2"],
)
def test_well_formed_references_are_accepted(reference: str) -> None:
    assert validate_reference(reference) == reference


@pytest.mark.parametrize(
    "reference",
    [
        "ollama/api-key",
        "https://evil.example/api-key",
        "secret://../../etc/passwd",
        "secret://Ollama/API-KEY",
        "secret://ollama/api key",
        "secret://",
        "",
        "secret://ollama/api-key\nsecret://other",
    ],
)
def test_malformed_references_are_refused(reference: str) -> None:
    """A reference is the one part of the secret path a descriptor carries, and a
    descriptor is content — so the syntax has to be too narrow to smuggle a path
    traversal, a URL, or a second reference."""
    with pytest.raises(InvalidSecretReferenceError):
        validate_reference(reference)


def test_a_reference_error_does_not_leak_a_value() -> None:
    with pytest.raises(InvalidSecretReferenceError) as raised:
        validate_reference("not-a-reference")
    assert VALUE not in str(raised.value)


# --- The development adapter ------------------------------------------------


def test_the_adapter_satisfies_the_port(store: EnvironmentSecretStore) -> None:
    assert isinstance(store, SecretStore)


def test_a_configured_secret_resolves(store: EnvironmentSecretStore) -> None:
    resolved = store.resolve(REFERENCE)
    assert resolved.reveal() == VALUE
    assert resolved.reference == REFERENCE


def test_presence_can_be_checked_without_resolving(store: EnvironmentSecretStore) -> None:
    """Lets the gateway fail before execution when a descriptor names a secret
    nobody configured, rather than part-way through."""
    assert store.has(REFERENCE)
    assert not store.has("secret://nobody/at-all")


def test_a_missing_secret_names_the_reference_and_the_variable(
    store: EnvironmentSecretStore,
) -> None:
    """Actionable for an operator, and there is no value to leak."""
    with pytest.raises(SecretNotFoundError) as raised:
        store.resolve("secret://nobody/at-all")
    message = str(raised.value)
    assert "secret://nobody/at-all" in message
    assert "ADW_SECRET_NOBODY_AT_ALL" in message


def test_a_malformed_reference_is_refused_before_any_lookup(
    store: EnvironmentSecretStore,
) -> None:
    with pytest.raises(InvalidSecretReferenceError):
        store.resolve("../../etc/passwd")


@pytest.mark.parametrize(
    ("reference", "variable"),
    [
        ("secret://ollama/api-key", "ADW_SECRET_OLLAMA_API_KEY"),
        ("secret://db", "ADW_SECRET_DB"),
        ("secret://a/b/c", "ADW_SECRET_A_B_C"),
    ],
)
def test_the_variable_mapping_is_stated_not_hidden(reference: str, variable: str) -> None:
    """An operator needs to know what to set, and a mapping that lives only
    inside a resolver is one nobody can configure against."""
    assert environment_variable_for(reference) == variable


def test_secrets_use_their_own_prefix_outside_the_settings_namespace() -> None:
    """`Settings` uses extra="forbid" and would reject these — and a secret has no
    business being a validated application setting logged with the rest of the
    configuration."""
    assert environment_variable_for(REFERENCE).startswith("ADW_SECRET_")

    from adw.config import Settings

    declared = {f"ADW_{name.upper()}" for name in Settings.model_fields}
    assert environment_variable_for(REFERENCE) not in declared


def test_the_adapter_refuses_to_start_outside_dev(
    env_settings: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The same refusal the local key store and blob store already carry."""
    from adw import config

    monkeypatch.setenv("ADW_APP_ENV", "prod")
    config.get_settings.cache_clear()
    with pytest.raises(RuntimeError, match="development-only"):
        EnvironmentSecretStore()
