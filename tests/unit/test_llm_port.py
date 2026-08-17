"""The LLM port's contract — D8, `CLAUDE.md` §6.

These tests are about the boundary itself, not about any provider: the value
objects, the error hierarchy, and the fact that the protocol is satisfiable.
"""

from __future__ import annotations

import pytest

from adw.ports.llm import (
    CompletionRequest,
    CompletionResponse,
    LLMAuthenticationError,
    LLMError,
    LLMMalformedResponseError,
    LLMProvider,
    LLMTimeoutError,
    LLMTransportError,
    Message,
    MessageRole,
    TokenUsage,
)

pytestmark = pytest.mark.unit


def test_messages_are_immutable() -> None:
    """A prompt that can be edited after it is recorded is not evidence of anything."""
    message = Message(role=MessageRole.USER, content="summarise Q3")
    with pytest.raises(AttributeError):
        message.content = "summarise Q4"  # type: ignore[misc]


def test_last_user_content_returns_the_most_recent_user_turn() -> None:
    request = CompletionRequest(
        messages=(
            Message(role=MessageRole.SYSTEM, content="you are a commentary agent"),
            Message(role=MessageRole.USER, content="first"),
            Message(role=MessageRole.ASSISTANT, content="draft"),
            Message(role=MessageRole.USER, content="second"),
        )
    )
    assert request.last_user_content() == "second"


def test_last_user_content_is_empty_when_there_is_no_user_turn() -> None:
    request = CompletionRequest(
        messages=(Message(role=MessageRole.SYSTEM, content="instructions only"),)
    )
    assert request.last_user_content() == ""


def test_token_usage_totals() -> None:
    assert TokenUsage(prompt_tokens=120, completion_tokens=35).total_tokens == 155


def test_the_request_carries_no_tools() -> None:
    """I2: the runtime may propose a tool call, never carry one to a provider.

    The Tool Gateway that would honour a proposal does not exist until Phase 3,
    and a field here would be the first place that invariant quietly eroded.
    """
    assert "tools" not in CompletionRequest.__dataclass_fields__


def test_the_response_carries_no_credential_field() -> None:
    """Nothing the runtime records can contain a key, structurally."""
    forbidden = {"api_key", "key", "token", "authorization", "secret", "credential"}
    assert not forbidden & set(CompletionResponse.__dataclass_fields__)


@pytest.mark.parametrize(
    "error",
    [LLMTimeoutError, LLMTransportError, LLMAuthenticationError, LLMMalformedResponseError],
)
def test_every_failure_shares_one_base(error: type[LLMError]) -> None:
    """`PRODUCT.md` §22 pauses an execution on a provider outage; that policy
    needs a single thing to catch."""
    assert issubclass(error, LLMError)


def test_a_minimal_object_satisfies_the_protocol() -> None:
    """The protocol is checkable at runtime, so a broken adapter fails loudly."""

    class Minimal:
        @property
        def name(self) -> str:
            return "minimal"

        def complete(self, request: CompletionRequest) -> CompletionResponse:
            return CompletionResponse(
                content="",
                usage=TokenUsage(prompt_tokens=0, completion_tokens=0),
                model="none",
                finish_reason="stop",
                provider="minimal",
            )

    assert isinstance(Minimal(), LLMProvider)
