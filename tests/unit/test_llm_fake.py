"""The deterministic fake — `CLAUDE.md` §6.

Determinism is the property under test. If any of these become flaky, the whole
argument for testing orchestration without a live model has collapsed.
"""

from __future__ import annotations

import pytest

from adw.adapters.llm_fake import DEFAULT_MODEL, PROVIDER_NAME, FakeLLMProvider, scripted
from adw.ports.llm import (
    CompletionRequest,
    LLMProvider,
    LLMTimeoutError,
    Message,
    MessageRole,
)

pytestmark = pytest.mark.unit


def ask(text: str) -> CompletionRequest:
    return CompletionRequest(
        messages=(
            Message(role=MessageRole.SYSTEM, content="you are a commentary agent"),
            Message(role=MessageRole.USER, content=text),
        )
    )


@pytest.fixture
def provider(env_settings: None) -> FakeLLMProvider:
    return FakeLLMProvider().register(
        trigger="revenue", response="Revenue rose 12% against a 9% plan."
    )


def test_the_fake_satisfies_the_port(provider: FakeLLMProvider) -> None:
    assert isinstance(provider, LLMProvider)
    assert provider.name == PROVIDER_NAME


def test_the_same_request_gives_the_same_answer_every_time(provider: FakeLLMProvider) -> None:
    """No clock, no network, no randomness — the point of the whole adapter."""
    first = provider.complete(ask("explain revenue"))
    second = provider.complete(ask("explain revenue"))
    assert first == second


def test_usage_is_computed_from_the_text_not_sampled(provider: FakeLLMProvider) -> None:
    response = provider.complete(ask("explain revenue"))
    assert response.usage.completion_tokens == len(response.content.split())
    assert response.usage.prompt_tokens > 0
    assert response.model == DEFAULT_MODEL
    assert response.provider == PROVIDER_NAME


def test_rules_match_in_registration_order(env_settings: None) -> None:
    fake = (
        FakeLLMProvider()
        .register(trigger="revenue variance", response="narrow")
        .register(trigger="revenue", response="broad")
    )
    assert fake.complete(ask("explain revenue variance")).content == "narrow"
    assert fake.complete(ask("explain revenue")).content == "broad"


def test_a_rule_can_script_a_failure(env_settings: None) -> None:
    """Timeout and outage handling has to be testable without unplugging anything."""
    fake = FakeLLMProvider().register(trigger="slow", error=LLMTimeoutError("provider timed out"))
    with pytest.raises(LLMTimeoutError):
        fake.complete(ask("slow request"))


def test_an_unmatched_request_raises_rather_than_inventing_an_answer(
    provider: FakeLLMProvider,
) -> None:
    """A test that silently receives a default is not asserting what its author thought."""
    with pytest.raises(LookupError):
        provider.complete(ask("something nobody scripted"))


def test_a_fallback_is_available_when_a_test_does_not_care(env_settings: None) -> None:
    fake = FakeLLMProvider(fallback="anything")
    assert fake.complete(ask("unscripted")).content == "anything"


def test_a_rule_must_specify_exactly_one_of_response_or_error(env_settings: None) -> None:
    fake = FakeLLMProvider()
    with pytest.raises(ValueError, match="exactly one"):
        fake.register(trigger="x")
    with pytest.raises(ValueError, match="exactly one"):
        fake.register(trigger="x", response="y", error=LLMTimeoutError("z"))


def test_every_request_is_recorded_so_a_test_can_assert_what_was_sent(
    provider: FakeLLMProvider,
) -> None:
    """Context assembly is checked by inspecting the prompt, not the answer."""
    provider.complete(ask("explain revenue"))
    assert len(provider.calls) == 1
    assert provider.calls[0].last_user_content() == "explain revenue"


def test_scripted_builds_a_provider_from_pairs(env_settings: None) -> None:
    fake = scripted([("alpha", "A"), ("beta", "B")])
    assert fake.complete(ask("alpha")).content == "A"
    assert fake.complete(ask("beta")).content == "B"


def test_the_fake_refuses_to_start_outside_dev_and_test(
    env_settings: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The same refusal the local key store and blob store already carry."""
    from adw import config

    monkeypatch.setenv("ADW_APP_ENV", "prod")
    config.get_settings.cache_clear()
    with pytest.raises(RuntimeError, match="refuses to start"):
        FakeLLMProvider()


def test_the_fake_makes_no_network_call(provider: FakeLLMProvider) -> None:
    """Belt and braces: httpx is unusable for the duration of this test."""
    import httpx

    class Forbidden(httpx.Client):
        def __init__(self, *args: object, **kwargs: object) -> None:
            raise AssertionError("the fake provider must never open a connection")

    original = httpx.Client
    httpx.Client = Forbidden  # type: ignore[misc]
    try:
        assert provider.complete(ask("explain revenue")).content
    finally:
        httpx.Client = original  # type: ignore[misc]
