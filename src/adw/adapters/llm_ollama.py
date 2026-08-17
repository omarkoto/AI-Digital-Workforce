"""Ollama Cloud provider — D8.

Verified against the official documentation (docs.ollama.com, August 2026):

* Endpoint: ``POST https://ollama.com/api/chat``
* Authentication: ``Authorization: Bearer $OLLAMA_API_KEY``
* Keys are created at https://ollama.com/settings/keys
* Request: ``{"model": ..., "messages": [{"role", "content"}], "stream": false}``
* Response: ``{"model", "created_at", "message": {"role", "content"}, "done",
  "done_reason", "prompt_eval_count", "eval_count", ...}``

Cloud models only — nothing runs locally, so no model is ever pulled onto the
host. The model name is configuration, never a constant here: the cloud catalogue
changes, and a hard-coded model would make a vendor's roadmap into our migration.

The API key lives in a ``SecretStr`` and reaches exactly one place: the request
header. It is never logged, never returned, and never part of a response object,
so nothing the Agent Runtime records can contain it.
"""

from __future__ import annotations

from typing import Any, Final

import httpx

from adw.config import Settings, get_settings
from adw.ports.llm import (
    CompletionRequest,
    CompletionResponse,
    LLMAuthenticationError,
    LLMMalformedResponseError,
    LLMTimeoutError,
    LLMTransportError,
    TokenUsage,
)

PROVIDER_NAME: Final = "ollama-cloud"
CHAT_PATH: Final = "/api/chat"


class OllamaCloudProvider:
    """Completions from Ollama Cloud's hosted models.

    Non-streaming by choice: the platform records a completed call as one action
    with one piece of evidence, and a partial stream is not something the audit
    model has a shape for.
    """

    def __init__(
        self, settings: Settings | None = None, client: httpx.Client | None = None
    ) -> None:
        resolved = settings or get_settings()
        if resolved.ollama_api_key is None:
            msg = (
                "ADW_OLLAMA_API_KEY is not configured; create a key at "
                "https://ollama.com/settings/keys and set it in .env"
            )
            raise LLMAuthenticationError(msg)
        if not resolved.ollama_model:
            msg = (
                "ADW_OLLAMA_MODEL is not configured; choose a cloud model from "
                "https://ollama.com/search?c=cloud and set it in .env"
            )
            raise LLMTransportError(msg)

        self._model = resolved.ollama_model
        self._timeout = resolved.ollama_timeout_seconds
        self._base_url = str(resolved.ollama_base_url).rstrip("/")
        # get_secret_value() is called once, here, and the result never leaves
        # this object. It is not stored on any dataclass, returned, or logged.
        self._key = resolved.ollama_api_key.get_secret_value()
        self._client = client

    @property
    def name(self) -> str:
        return PROVIDER_NAME

    @property
    def model(self) -> str:
        return self._model

    def _post(self, payload: dict[str, Any]) -> httpx.Response:
        headers = {
            "Authorization": f"Bearer {self._key}",
            "Content-Type": "application/json",
        }
        url = f"{self._base_url}{CHAT_PATH}"
        if self._client is not None:
            return self._client.post(url, json=payload, headers=headers, timeout=self._timeout)
        with httpx.Client(timeout=self._timeout) as client:
            return client.post(url, json=payload, headers=headers)

    def complete(self, request: CompletionRequest) -> CompletionResponse:
        payload: dict[str, Any] = {
            "model": self._model,
            "messages": [
                {"role": message.role.value, "content": message.content}
                for message in request.messages
            ],
            "stream": False,
        }
        options: dict[str, Any] = {}
        if request.temperature is not None:
            options["temperature"] = request.temperature
        if request.max_output_tokens is not None:
            options["num_predict"] = request.max_output_tokens
        if request.stop:
            options["stop"] = list(request.stop)
        if options:
            payload["options"] = options

        try:
            response = self._post(payload)
        except httpx.TimeoutException as exc:
            msg = f"ollama cloud did not answer within {self._timeout}s"
            raise LLMTimeoutError(msg) from exc
        except httpx.HTTPError as exc:
            # The exception class, never its text: a transport error can echo the
            # request, and the request carries the Authorization header.
            msg = f"ollama cloud was unreachable ({exc.__class__.__name__})"
            raise LLMTransportError(msg) from exc

        if response.status_code in (401, 403):
            msg = "ollama cloud rejected the credential; check ADW_OLLAMA_API_KEY"
            raise LLMAuthenticationError(msg)
        if response.status_code >= 400:
            msg = f"ollama cloud returned HTTP {response.status_code}"
            raise LLMTransportError(msg)

        return self._normalise(response)

    def _normalise(self, response: httpx.Response) -> CompletionResponse:
        try:
            body = response.json()
        except ValueError as exc:
            msg = "ollama cloud returned a body that is not JSON"
            raise LLMMalformedResponseError(msg) from exc

        if not isinstance(body, dict):
            msg = f"expected a JSON object from ollama cloud, got {type(body).__name__}"
            raise LLMMalformedResponseError(msg)

        message = body.get("message")
        if not isinstance(message, dict) or not isinstance(message.get("content"), str):
            # Named without quoting the body: a malformed response may still
            # contain tenant content, and this message reaches logs.
            msg = "ollama cloud response has no message.content string"
            raise LLMMalformedResponseError(msg)

        return CompletionResponse(
            content=str(message["content"]),
            usage=TokenUsage(
                prompt_tokens=int(body.get("prompt_eval_count") or 0),
                completion_tokens=int(body.get("eval_count") or 0),
            ),
            model=str(body.get("model") or self._model),
            finish_reason=str(body.get("done_reason") or "unknown"),
            provider=PROVIDER_NAME,
        )
