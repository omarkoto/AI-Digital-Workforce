"""The Ollama Cloud adapter — D8.

Every test here runs against an in-process transport. Nothing reaches the
network, so the suite stays runnable with no credential and no connectivity.
The live smoke test is separate, opt-in, and skipped by default.

The API shape asserted here was verified against the official documentation at
docs.ollama.com: ``POST https://ollama.com/api/chat``, bearer authentication,
and a ``message.content`` response body.
"""

from __future__ import annotations

import json
from typing import Any

import httpx
import pytest
from pydantic import SecretStr

from adw.adapters.llm_ollama import PROVIDER_NAME, OllamaCloudProvider
from adw.config import Settings
from adw.ports.llm import (
    CompletionRequest,
    LLMAuthenticationError,
    LLMMalformedResponseError,
    LLMProvider,
    LLMTimeoutError,
    LLMTransportError,
    Message,
    MessageRole,
)

pytestmark = pytest.mark.unit

API_KEY = "ollama-test-key-do-not-use"
MODEL = "gpt-oss:120b"

CHAT_BODY: dict[str, Any] = {
    "model": MODEL,
    "created_at": "2026-08-18T09:12:00.000Z",
    "message": {"role": "assistant", "content": "Revenue rose 12% against a 9% plan."},
    "done": True,
    "done_reason": "stop",
    "prompt_eval_count": 42,
    "eval_count": 9,
}


def build_settings(**overrides: Any) -> Settings:
    values: dict[str, Any] = {
        "database_url": "postgresql+psycopg://adw_app:x@localhost:5432/adw_test",
        "migration_database_url": "postgresql+psycopg://adw_owner:x@localhost:5432/adw_test",
        "ollama_model": MODEL,
        "ollama_api_key": SecretStr(API_KEY),
    }
    values.update(overrides)
    return Settings(**values)


def provider_over(handler: Any, **overrides: Any) -> OllamaCloudProvider:
    """An adapter wired to an in-process transport. No socket is ever opened."""
    client = httpx.Client(transport=httpx.MockTransport(handler))
    return OllamaCloudProvider(settings=build_settings(**overrides), client=client)


def ask(text: str = "explain revenue") -> CompletionRequest:
    return CompletionRequest(
        messages=(
            Message(role=MessageRole.SYSTEM, content="you are a commentary agent"),
            Message(role=MessageRole.USER, content=text),
        )
    )


def ok(request: httpx.Request) -> httpx.Response:
    return httpx.Response(200, json=CHAT_BODY)


# --- The happy path ---------------------------------------------------------


def test_the_adapter_satisfies_the_port(env_settings: None) -> None:
    assert isinstance(provider_over(ok), LLMProvider)


def test_a_completion_is_normalised_into_the_port_type(env_settings: None) -> None:
    response = provider_over(ok).complete(ask())
    assert response.content == "Revenue rose 12% against a 9% plan."
    assert response.model == MODEL
    assert response.finish_reason == "stop"
    assert response.provider == PROVIDER_NAME
    assert response.usage.prompt_tokens == 42
    assert response.usage.completion_tokens == 9
    assert response.usage.total_tokens == 51


def test_the_request_matches_the_documented_endpoint_and_shape(env_settings: None) -> None:
    seen: dict[str, Any] = {}

    def capture(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["method"] = request.method
        seen["body"] = json.loads(request.content)
        return httpx.Response(200, json=CHAT_BODY)

    provider_over(capture).complete(ask())

    assert seen["method"] == "POST"
    assert seen["url"] == "https://ollama.com/api/chat"
    assert seen["body"]["model"] == MODEL
    assert seen["body"]["stream"] is False
    assert seen["body"]["messages"] == [
        {"role": "system", "content": "you are a commentary agent"},
        {"role": "user", "content": "explain revenue"},
    ]


def test_generation_parameters_are_passed_as_options(env_settings: None) -> None:
    seen: dict[str, Any] = {}

    def capture(request: httpx.Request) -> httpx.Response:
        seen.update(json.loads(request.content))
        return httpx.Response(200, json=CHAT_BODY)

    provider_over(capture).complete(
        CompletionRequest(
            messages=(Message(role=MessageRole.USER, content="x"),),
            max_output_tokens=256,
            temperature=0.0,
            stop=("END",),
        )
    )
    assert seen["options"] == {"temperature": 0.0, "num_predict": 256, "stop": ["END"]}


def test_no_options_key_is_sent_when_nothing_was_requested(env_settings: None) -> None:
    seen: dict[str, Any] = {}

    def capture(request: httpx.Request) -> httpx.Response:
        seen.update(json.loads(request.content))
        return httpx.Response(200, json=CHAT_BODY)

    provider_over(capture).complete(ask())
    assert "options" not in seen


# --- Configuration ----------------------------------------------------------


def test_the_model_is_configuration_and_has_no_default(env_settings: None) -> None:
    """A model pinned in code turns a vendor catalogue change into a code change."""
    assert Settings.model_fields["ollama_model"].default is None
    with pytest.raises(LLMTransportError, match="ADW_OLLAMA_MODEL"):
        provider_over(ok, ollama_model=None)


def test_a_missing_key_fails_before_any_request(env_settings: None) -> None:
    with pytest.raises(LLMAuthenticationError, match="ADW_OLLAMA_API_KEY"):
        provider_over(ok, ollama_api_key=None)


def test_the_base_url_is_configurable(env_settings: None) -> None:
    seen: dict[str, str] = {}

    def capture(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        return httpx.Response(200, json=CHAT_BODY)

    provider_over(capture, ollama_base_url="https://proxy.internal/").complete(ask())
    assert seen["url"] == "https://proxy.internal/api/chat"


# --- The credential ---------------------------------------------------------


def test_the_key_travels_only_in_the_authorization_header(env_settings: None) -> None:
    seen: dict[str, Any] = {}

    def capture(request: httpx.Request) -> httpx.Response:
        seen["auth"] = request.headers.get("authorization")
        seen["body"] = request.content.decode()
        seen["url"] = str(request.url)
        return httpx.Response(200, json=CHAT_BODY)

    provider_over(capture).complete(ask())
    assert seen["auth"] == f"Bearer {API_KEY}"
    assert API_KEY not in seen["body"]
    assert API_KEY not in seen["url"]


def test_the_key_never_appears_in_a_response_object(env_settings: None) -> None:
    response = provider_over(ok).complete(ask())
    assert API_KEY not in repr(response)


def test_the_key_never_appears_in_any_error(env_settings: None) -> None:
    """Whatever an adapter raises is about to be persisted as evidence."""

    def reject(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, json={"error": "unauthorized"})

    with pytest.raises(LLMAuthenticationError) as raised:
        provider_over(reject).complete(ask())
    assert API_KEY not in str(raised.value)


def test_settings_hides_the_key_from_a_repr(env_settings: None) -> None:
    assert API_KEY not in repr(build_settings())


# --- Failures ---------------------------------------------------------------


def test_a_timeout_becomes_a_timeout_error(env_settings: None) -> None:
    def slow(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("too slow", request=request)

    with pytest.raises(LLMTimeoutError, match="did not answer"):
        provider_over(slow).complete(ask())


def test_an_unreachable_host_becomes_a_transport_error(env_settings: None) -> None:
    def unreachable(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("no route to host", request=request)

    with pytest.raises(LLMTransportError, match="unreachable"):
        provider_over(unreachable).complete(ask())


@pytest.mark.parametrize("status", [401, 403])
def test_a_rejected_credential_becomes_an_authentication_error(
    env_settings: None, status: int
) -> None:
    def reject(request: httpx.Request) -> httpx.Response:
        return httpx.Response(status, json={"error": "unauthorized"})

    with pytest.raises(LLMAuthenticationError):
        provider_over(reject).complete(ask())


@pytest.mark.parametrize("status", [429, 500, 503])
def test_other_http_failures_become_transport_errors(env_settings: None, status: int) -> None:
    def fail(request: httpx.Request) -> httpx.Response:
        return httpx.Response(status, json={"error": "nope"})

    with pytest.raises(LLMTransportError, match=str(status)):
        provider_over(fail).complete(ask())


def test_a_non_json_body_becomes_a_malformed_response_error(env_settings: None) -> None:
    def html(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text="<html>gateway</html>")

    with pytest.raises(LLMMalformedResponseError, match="not JSON"):
        provider_over(html).complete(ask())


@pytest.mark.parametrize(
    "body",
    [
        {"done": True},
        {"message": {"role": "assistant"}},
        {"message": {"role": "assistant", "content": None}},
        {"message": "a string, not an object"},
        ["a list, not an object"],
    ],
)
def test_an_unexpected_shape_becomes_a_malformed_response_error(
    env_settings: None, body: object
) -> None:
    """Never a silent empty completion — an agent that "said nothing" and an
    agent whose provider misbehaved are different facts."""

    def odd(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=body)

    with pytest.raises(LLMMalformedResponseError):
        provider_over(odd).complete(ask())


def test_a_malformed_response_error_does_not_quote_the_body(env_settings: None) -> None:
    """A bad body may still hold tenant content, and this message reaches logs."""

    def leaky(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"unexpected": "SALARY 184000 GBP"})

    with pytest.raises(LLMMalformedResponseError) as raised:
        provider_over(leaky).complete(ask())
    assert "184000" not in str(raised.value)


def test_a_missing_done_reason_is_reported_as_unknown_not_as_stop(env_settings: None) -> None:
    """ "Finished normally" is a claim, and it needs the provider to have made it."""

    def terse(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"message": {"role": "assistant", "content": "hi"}})

    assert provider_over(terse).complete(ask()).finish_reason == "unknown"
