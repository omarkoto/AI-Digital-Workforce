"""A model call, recorded — `CLAUDE.md` §3, `PHASE-2-IMPLEMENTATION-PLAN.md` §2.5.

A call to a model is a tool invocation like any other, and gets the same
treatment: an Action moving through the six-state truth model, with evidence for
what was sent and what came back. Nothing here is special-cased because the tool
happens to be an LLM.

**This module imports the port and never a provider.** That is the whole point of
D8 — swapping providers, or running the entire suite on the deterministic fake,
must not touch a line of this file.

Two ordering choices are load-bearing:

* **The prompt is recorded before the call, not after.** If the provider hangs,
  times out, or the process dies mid-flight, the record still shows what was
  attempted. Recording afterwards would leave a failed call with no evidence of
  its input, which is exactly the gap `CLAUDE.md` §3 exists to close.
* **A provider failure is returned, not raised.** The Action's transition to
  ``failed`` and its evidence are written to the caller's session; an exception
  escaping here would very likely take that session down with it and destroy the
  record of the failure. The caller decides what to do about a failure — it does
  not get to be unaware one happened.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from sqlalchemy.orm import Session

from adw.domain.states import ActionState
from adw.models.action import Action
from adw.models.task import Task
from adw.ports.blobstore import BlobStore
from adw.ports.keystore import KeyStore
from adw.ports.llm import (
    CompletionRequest,
    CompletionResponse,
    LLMError,
    LLMProvider,
)
from adw.services import action_recorder, evidence_recorder

TOOL_NAME = "llm.complete"
"""Recorded as the tool name for every model call, whatever the provider. The
provider is recorded in the evidence; the *capability* being exercised is the
same one either way."""

EVIDENCE_REQUEST = "llm.request"
EVIDENCE_RESPONSE = "llm.response"
EVIDENCE_FAILURE = "llm.failure"


@dataclass(frozen=True, slots=True)
class RecordedCompletion:
    """The outcome of one recorded model call.

    Exactly one of ``response`` and ``error`` is set. There is no third case:
    a call either produced a completion or did not, and "probably worked" is not
    a state this platform persists.
    """

    action: Action
    response: CompletionResponse | None = None
    error: LLMError | None = None

    @property
    def succeeded(self) -> bool:
        return self.response is not None

    @property
    def truncated(self) -> bool:
        """Whether the provider stopped for a reason other than finishing.

        Not treated as a failure — the call did complete — but recorded, so a
        Control Gate can catch a half-written artifact rather than the platform
        silently shipping one (`PRODUCT.md` §25).
        """
        return self.response is not None and self.response.finish_reason not in ("stop", "")


def _request_payload(request: CompletionRequest) -> dict[str, Any]:
    """What was sent, as evidence.

    Messages only. Not the provider's base URL, not its headers, not its
    settings object — the credential lives on those and never on this.
    """
    return {
        "messages": [
            {"role": message.role.value, "content": message.content} for message in request.messages
        ],
        "max_output_tokens": request.max_output_tokens,
        "temperature": request.temperature,
        "stop": list(request.stop),
    }


def _response_payload(response: CompletionResponse) -> dict[str, Any]:
    return {
        "provider": response.provider,
        "model": response.model,
        "content": response.content,
        "finish_reason": response.finish_reason,
        "usage": {
            "prompt_tokens": response.usage.prompt_tokens,
            "completion_tokens": response.usage.completion_tokens,
            "total_tokens": response.usage.total_tokens,
        },
    }


def invoke(
    session: Session,
    *,
    task: Task,
    sequence: int,
    provider: LLMProvider,
    request: CompletionRequest,
    keystore: KeyStore,
    blobstore: BlobStore,
    actor_id: str,
) -> RecordedCompletion:
    """Call ``provider`` for ``task``, recording the attempt and its outcome.

    Must be called inside a transaction already scoped to the task's tenant.
    Returns the outcome; it does not raise on a provider failure.
    """
    action = action_recorder.plan_action(session, task=task, sequence=sequence, tool_name=TOOL_NAME)
    action_recorder.transition(
        session, action, ActionState.ATTEMPTED, keystore=keystore, actor_id=actor_id
    )

    # Before the call — see the module docstring.
    evidence_recorder.record_for_action(
        session,
        action=action,
        kind=EVIDENCE_REQUEST,
        payload=_request_payload(request),
        keystore=keystore,
        blobstore=blobstore,
    )

    try:
        response = provider.complete(request)
    except LLMError as exc:
        # The class and its message. A provider is required to raise without the
        # credential in the message (see adw.ports.llm), and this is the point
        # that depends on it: whatever is here is about to be persisted.
        evidence_recorder.record_for_action(
            session,
            action=action,
            kind=EVIDENCE_FAILURE,
            payload={"provider": provider.name, "error": type(exc).__name__, "detail": str(exc)},
            keystore=keystore,
            blobstore=blobstore,
        )
        action_recorder.transition(
            session,
            action,
            ActionState.FAILED,
            keystore=keystore,
            actor_id=actor_id,
            failure_detail=f"{type(exc).__name__}: {exc}",
        )
        return RecordedCompletion(action=action, error=exc)

    # Executed first, then succeeded. They are different claims: the tool ran,
    # and the tool ran and met its criteria. Collapsing them would lose the
    # distinction CLAUDE.md §3 exists to preserve.
    action_recorder.transition(
        session, action, ActionState.EXECUTED, keystore=keystore, actor_id=actor_id
    )
    evidence_recorder.record_for_action(
        session,
        action=action,
        kind=EVIDENCE_RESPONSE,
        payload=_response_payload(response),
        keystore=keystore,
        blobstore=blobstore,
    )
    action_recorder.transition(
        session, action, ActionState.SUCCEEDED, keystore=keystore, actor_id=actor_id
    )
    return RecordedCompletion(action=action, response=response)
