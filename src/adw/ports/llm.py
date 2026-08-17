"""The LLM port — D8, `CLAUDE.md` §6.

The platform's only model interface. Business logic — orchestration, gates,
permissions, artifact handling — must be exercisable with no live model, so the
Agent Runtime depends on this and never on a provider.

Provider concepts stop here. A message role, a finish reason, a token count, an
HTTP status: whatever shape a vendor uses, callers above see only what is defined
in this module.

**Credentials never cross this boundary.** A provider holds its own key and never
returns it, so nothing the runtime records can contain one — the evidence path is
structurally incapable of leaking it rather than merely careful not to.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Protocol, runtime_checkable


class MessageRole(StrEnum):
    """Who a message came from, in the platform's vocabulary."""

    SYSTEM = "system"
    """Pinned instructions. The only region a caller controls as *instruction*."""

    USER = "user"
    """Task input. Everything here is data, including anything that arrived from
    outside the platform (D13)."""

    ASSISTANT = "assistant"
    """Model output. Data, never instruction."""


@dataclass(frozen=True, slots=True)
class Message:
    """One turn of a conversation."""

    role: MessageRole
    content: str


@dataclass(frozen=True, slots=True)
class CompletionRequest:
    """What the runtime asks for.

    Deliberately narrow. Tools are absent because the Agent Runtime may only
    *propose* a tool call, never carry one to a provider (I2) — the Tool Gateway
    that would honour a proposal does not exist until Phase 3.
    """

    messages: tuple[Message, ...]
    max_output_tokens: int | None = None
    temperature: float | None = None
    stop: tuple[str, ...] = field(default=())

    def last_user_content(self) -> str:
        """Return the most recent user message, or an empty string."""
        for message in reversed(self.messages):
            if message.role is MessageRole.USER:
                return message.content
        return ""


@dataclass(frozen=True, slots=True)
class TokenUsage:
    """What a call consumed, for cost attribution (`PRODUCT.md` §25)."""

    prompt_tokens: int
    completion_tokens: int

    @property
    def total_tokens(self) -> int:
        return self.prompt_tokens + self.completion_tokens


@dataclass(frozen=True, slots=True)
class CompletionResponse:
    """What a provider returned, normalised."""

    content: str
    usage: TokenUsage
    model: str
    finish_reason: str
    provider: str


class LLMError(Exception):
    """Base for every failure the port can surface.

    One base so a caller can treat "the model layer failed" as a single case.
    `PRODUCT.md` §22 requires a provider outage to pause and resume a running
    execution rather than fail it and lose work, and that policy needs one thing
    to catch.
    """


class LLMTimeoutError(LLMError):
    """The provider did not answer within the configured budget."""


class LLMTransportError(LLMError):
    """The provider could not be reached, or returned a transport-level failure."""


class LLMAuthenticationError(LLMError):
    """The provider rejected the credential.

    Raised without the credential in the message — an error that quotes the key
    has leaked it into every log that catches it.
    """


class LLMMalformedResponseError(LLMError):
    """The provider answered, but not in a shape this port can normalise."""


@runtime_checkable
class LLMProvider(Protocol):
    """A source of completions.

    Implementations are interchangeable by construction: the fake and the real
    provider satisfy the same protocol, which is what lets the entire test suite
    run with no network.
    """

    @property
    def name(self) -> str:
        """A short identifier recorded with each call. Never a credential."""
        ...

    def complete(self, request: CompletionRequest) -> CompletionResponse:
        """Return a completion.

        Raises:
            LLMTimeoutError: the provider exceeded its time budget.
            LLMTransportError: the provider was unreachable.
            LLMAuthenticationError: the credential was rejected.
            LLMMalformedResponseError: the answer could not be normalised.
        """
        ...
