"""A deterministic provider for tests — `CLAUDE.md` §6.

Same output for the same input, every time, with no network. This is what keeps
the suite fast, reproducible, and independent of a vendor, and it is what
`CLAUDE.md` §6 means by business logic being testable with no live model.

It is **not** a lesser sibling of the real provider. A second implementation of
the port is the only evidence that the port is implementable twice — D8 notes
that an abstraction validated against exactly one provider is a hypothesis, and
this is the mitigation.

Determinism has one rule: **nothing here may consult the clock, the network, or a
random source.** Token counts are computed from the text, not sampled.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field

from adw.config import AppEnv, get_settings
from adw.ports.llm import (
    CompletionRequest,
    CompletionResponse,
    LLMError,
    MessageRole,
    TokenUsage,
)

PROVIDER_NAME = "fake"
DEFAULT_MODEL = "fake-deterministic-v1"


@dataclass(frozen=True, slots=True)
class Rule:
    """A scripted response, or a scripted failure.

    ``trigger`` is matched as a substring of the request's last user message.
    Substring rather than exact match so a test can key on the one detail it
    cares about without restating the whole prompt.
    """

    trigger: str
    response: str | None = None
    error: LLMError | None = None
    finish_reason: str = "stop"


@dataclass
class FakeLLMProvider:
    """A provider that answers from a script.

    Rules are matched in registration order, so a later, narrower rule can be
    registered first and win. An unmatched request raises rather than inventing
    an answer: a test that silently gets a default is a test that is not
    asserting what its author thought.
    """

    model: str = DEFAULT_MODEL
    rules: list[Rule] = field(default_factory=list)
    fallback: str | None = None
    calls: list[CompletionRequest] = field(default_factory=list)
    """Every request received, in order. Lets a test assert what was *sent* —
    which is how the injection-separation tests check context assembly."""

    def __post_init__(self) -> None:
        settings = get_settings()
        if settings.app_env not in (AppEnv.DEV, AppEnv.TEST):
            msg = (
                f"FakeLLMProvider is for development and tests and refuses to start in "
                f"{settings.app_env.value!r}; a scripted model must never serve real work"
            )
            raise RuntimeError(msg)

    @property
    def name(self) -> str:
        return PROVIDER_NAME

    def register(
        self,
        *,
        trigger: str,
        response: str | None = None,
        error: LLMError | None = None,
        finish_reason: str = "stop",
    ) -> FakeLLMProvider:
        """Add a rule. Returns self so rules can be chained at construction."""
        if (response is None) == (error is None):
            msg = "a rule must specify exactly one of response or error"
            raise ValueError(msg)
        self.rules.append(
            Rule(trigger=trigger, response=response, error=error, finish_reason=finish_reason)
        )
        return self

    @staticmethod
    def count_tokens(text: str) -> int:
        """A deterministic stand-in for tokenisation.

        Whitespace-delimited words. Not accurate against any real tokeniser, and
        not trying to be — its only job is to be the same number every run, so
        cost-accounting assertions are stable.
        """
        return len(text.split())

    def complete(self, request: CompletionRequest) -> CompletionResponse:
        self.calls.append(request)
        probe = request.last_user_content()

        for rule in self.rules:
            if rule.trigger in probe:
                if rule.error is not None:
                    raise rule.error
                assert rule.response is not None
                return self._respond(request, rule.response, rule.finish_reason)

        if self.fallback is not None:
            return self._respond(request, self.fallback, "stop")

        msg = (
            "FakeLLMProvider has no rule matching this request and no fallback; "
            "register one rather than letting a test pass on an invented answer"
        )
        raise LookupError(msg)

    def _respond(
        self, request: CompletionRequest, content: str, finish_reason: str
    ) -> CompletionResponse:
        prompt_text = " ".join(
            message.content
            for message in request.messages
            if message.role is not MessageRole.ASSISTANT
        )
        return CompletionResponse(
            content=content,
            usage=TokenUsage(
                prompt_tokens=self.count_tokens(prompt_text),
                completion_tokens=self.count_tokens(content),
            ),
            model=self.model,
            finish_reason=finish_reason,
            provider=PROVIDER_NAME,
        )


def scripted(pairs: Sequence[tuple[str, str]], *, model: str = DEFAULT_MODEL) -> FakeLLMProvider:
    """Build a provider from ``(trigger, response)`` pairs."""
    provider = FakeLLMProvider(model=model)
    for trigger, response in pairs:
        provider.register(trigger=trigger, response=response)
    return provider
