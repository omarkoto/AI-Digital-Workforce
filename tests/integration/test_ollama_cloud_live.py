"""A single live call to Ollama Cloud — opt-in, and off by default.

This is the only test in the repository that touches the network. It exists
because an adapter verified solely against a mock proves that the *mock* matches
what the code expects, not that the provider does.

It runs only when `ADW_OLLAMA_API_KEY` and `ADW_OLLAMA_MODEL` are both set, so
CI, a clean checkout, and every other developer skip it. It is marked
``external``: deselect it explicitly with ``-m "not external"``.

Nothing here asserts on the *content* of the completion. A model's words are not
a deterministic fixture, and a test that pinned them would be flaky by design.
What is asserted is the contract: the response normalises into the port's types.
"""

from __future__ import annotations

import os

import pytest

from adw.adapters.llm_ollama import PROVIDER_NAME, OllamaCloudProvider
from adw.config import Settings
from adw.ports.llm import CompletionRequest, Message, MessageRole

pytestmark = [pytest.mark.integration, pytest.mark.external]


@pytest.fixture
def live_provider() -> OllamaCloudProvider:
    if not os.environ.get("ADW_OLLAMA_API_KEY") or not os.environ.get("ADW_OLLAMA_MODEL"):
        pytest.skip("ADW_OLLAMA_API_KEY and ADW_OLLAMA_MODEL are not set; skipping live call")
    return OllamaCloudProvider(settings=Settings())  # type: ignore[call-arg]


def test_a_live_completion_normalises_into_the_port(live_provider: OllamaCloudProvider) -> None:
    response = live_provider.complete(
        CompletionRequest(
            messages=(
                Message(
                    role=MessageRole.SYSTEM,
                    content="Answer in one short sentence.",
                ),
                Message(role=MessageRole.USER, content="What is a trial balance?"),
            ),
            max_output_tokens=64,
            temperature=0.0,
        )
    )

    assert response.content.strip()
    assert response.provider == PROVIDER_NAME
    assert response.model
    assert response.finish_reason
    assert response.usage.total_tokens > 0
