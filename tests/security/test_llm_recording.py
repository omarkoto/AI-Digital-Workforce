"""A model call is recorded like any other action — `CLAUDE.md` ?�3, I10, D12.

The point of these tests is that nothing about the Agent Runtime's model calls
is exempt from the Execution Record Core. A completion is a tool result; a
provider outage is a failed action; and neither is allowed to reach the record
as a bare assertion.
"""

from __future__ import annotations

import json
from uuid import uuid4

import pytest
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from adw.adapters.blobstore_local import LocalBlobStore
from adw.adapters.keystore_local import LocalKeyStore
from adw.adapters.llm_fake import FakeLLMProvider
from adw.domain.states import ActionState, TaskState
from adw.models.action import Action, Evidence
from adw.models.audit import AuditChainRecord
from adw.models.task import Task
from adw.ports.llm import (
    CompletionRequest,
    LLMTimeoutError,
    Message,
    MessageRole,
)
from adw.runtime import model_call
from adw.services import evidence_recorder
from tests.security.conftest import TENANT_A

pytestmark = pytest.mark.security

ACTOR = "agent:commentary"
ANSWER = "Revenue rose 12% against a 9% plan."


@pytest.fixture
def task(chain_session: Session) -> Task:
    agent_id, version_id, execution_id = uuid4(), uuid4(), uuid4()
    chain_session.execute(
        text(
            "INSERT INTO agent_definition (id, key, name) VALUES (:i, 'commentary', 'Commentary')"
        ),
        {"i": agent_id},
    )
    chain_session.execute(
        text(
            "INSERT INTO agent_definition_version "
            "(id, agent_definition_id, version_no, instructions) VALUES (:i, :d, 1, 'explain')"
        ),
        {"i": version_id, "d": agent_id},
    )
    chain_session.execute(
        text(
            "INSERT INTO execution (id, tenant_id, requester_identity, state) "
            "VALUES (:i, :t, 'amira@northwind', 'running')"
        ),
        {"i": execution_id, "t": TENANT_A},
    )
    row = Task(
        tenant_id=TENANT_A,
        execution_id=execution_id,
        sequence=1,
        agent_definition_version_id=version_id,
        state=TaskState.RUNNING,
        attempt_no=1,
    )
    chain_session.add(row)
    chain_session.flush()
    return row


@pytest.fixture
def provider(dev_keystore: LocalKeyStore) -> FakeLLMProvider:
    """Depends on dev_keystore so the dev environment is established first."""
    return FakeLLMProvider().register(trigger="revenue", response=ANSWER)


def ask(text_: str = "explain the revenue variance") -> CompletionRequest:
    return CompletionRequest(
        messages=(
            Message(role=MessageRole.SYSTEM, content="you are a commentary agent"),
            Message(role=MessageRole.USER, content=text_),
        )
    )


def call(
    session: Session,
    task: Task,
    provider: FakeLLMProvider,
    keystore: LocalKeyStore,
    blobstore: LocalBlobStore,
    request: CompletionRequest | None = None,
) -> model_call.RecordedCompletion:
    return model_call.invoke(
        session,
        task=task,
        sequence=1,
        provider=provider,
        request=request if request is not None else ask(),
        keystore=keystore,
        blobstore=blobstore,
        actor_id=ACTOR,
    )


def evidence_of(session: Session, action: Action, kind: str) -> Evidence:
    return session.execute(
        select(Evidence).where(Evidence.action_id == action.id, Evidence.kind == kind)
    ).scalar_one()


def payload_of(
    session: Session, action: Action, kind: str, keystore: LocalKeyStore, blobstore: LocalBlobStore
) -> dict[str, object]:
    raw = evidence_recorder.read_payload(
        evidence_of(session, action, kind),
        tenant_id=TENANT_A,
        keystore=keystore,
        blobstore=blobstore,
    )
    decoded: dict[str, object] = json.loads(raw)
    return decoded


# --- A successful call ------------------------------------------------------


def test_a_successful_call_reaches_succeeded_with_evidence(
    chain_session: Session,
    task: Task,
    provider: FakeLLMProvider,
    dev_keystore: LocalKeyStore,
    dev_blobstore: LocalBlobStore,
) -> None:
    outcome = call(chain_session, task, provider, dev_keystore, dev_blobstore)

    assert outcome.succeeded
    assert outcome.action.state is ActionState.SUCCEEDED
    assert outcome.action.tool_name == model_call.TOOL_NAME
    kinds = {
        row.kind
        for row in chain_session.execute(
            select(Evidence).where(Evidence.action_id == outcome.action.id)
        ).scalars()
    }
    assert kinds == {model_call.EVIDENCE_REQUEST, model_call.EVIDENCE_RESPONSE}


def test_the_response_evidence_holds_the_completion_and_its_usage(
    chain_session: Session,
    task: Task,
    provider: FakeLLMProvider,
    dev_keystore: LocalKeyStore,
    dev_blobstore: LocalBlobStore,
) -> None:
    outcome = call(chain_session, task, provider, dev_keystore, dev_blobstore)
    recorded = payload_of(
        chain_session, outcome.action, model_call.EVIDENCE_RESPONSE, dev_keystore, dev_blobstore
    )
    assert recorded["content"] == ANSWER
    assert recorded["provider"] == "fake"
    # Nine prompt words, seven completion words � the fake counts deterministically.
    assert recorded["usage"] == {
        "prompt_tokens": 9,
        "completion_tokens": 7,
        "total_tokens": 16,
    }


def test_the_prompt_is_recorded_as_evidence_too(
    chain_session: Session,
    task: Task,
    provider: FakeLLMProvider,
    dev_keystore: LocalKeyStore,
    dev_blobstore: LocalBlobStore,
) -> None:
    """Step 10 re-checks what happened. Without the input, "what happened" is half a record."""
    outcome = call(chain_session, task, provider, dev_keystore, dev_blobstore)
    recorded = payload_of(
        chain_session, outcome.action, model_call.EVIDENCE_REQUEST, dev_keystore, dev_blobstore
    )
    assert recorded["messages"] == [
        {"role": "system", "content": "you are a commentary agent"},
        {"role": "user", "content": "explain the revenue variance"},
    ]


def test_every_transition_lands_in_the_audit_chain(
    chain_session: Session,
    task: Task,
    provider: FakeLLMProvider,
    dev_keystore: LocalKeyStore,
    dev_blobstore: LocalBlobStore,
) -> None:
    before = chain_session.execute(select(AuditChainRecord)).scalars().all()
    call(chain_session, task, provider, dev_keystore, dev_blobstore)
    after = chain_session.execute(select(AuditChainRecord)).scalars().all()
    # attempted, executed, succeeded.
    assert len(after) - len(before) == 3


# --- A failing call ---------------------------------------------------------


def test_a_provider_failure_is_recorded_as_a_failed_action_not_lost(
    chain_session: Session,
    task: Task,
    dev_keystore: LocalKeyStore,
    dev_blobstore: LocalBlobStore,
) -> None:
    provider = FakeLLMProvider().register(
        trigger="revenue", error=LLMTimeoutError("provider did not answer within 60.0s")
    )
    outcome = call(chain_session, task, provider, dev_keystore, dev_blobstore)

    assert not outcome.succeeded
    assert isinstance(outcome.error, LLMTimeoutError)
    assert outcome.action.state is ActionState.FAILED
    assert outcome.action.failure_detail is not None
    assert "LLMTimeoutError" in outcome.action.failure_detail


def test_the_prompt_survives_a_failure(
    chain_session: Session,
    task: Task,
    dev_keystore: LocalKeyStore,
    dev_blobstore: LocalBlobStore,
) -> None:
    """Recorded before the call, precisely so a timeout leaves proof of the attempt."""
    provider = FakeLLMProvider().register(trigger="revenue", error=LLMTimeoutError("timed out"))
    outcome = call(chain_session, task, provider, dev_keystore, dev_blobstore)
    assert evidence_of(chain_session, outcome.action, model_call.EVIDENCE_REQUEST) is not None
    assert evidence_of(chain_session, outcome.action, model_call.EVIDENCE_FAILURE) is not None


def test_a_failed_action_never_reaches_succeeded(
    chain_session: Session,
    task: Task,
    dev_keystore: LocalKeyStore,
    dev_blobstore: LocalBlobStore,
) -> None:
    provider = FakeLLMProvider().register(trigger="revenue", error=LLMTimeoutError("timed out"))
    outcome = call(chain_session, task, provider, dev_keystore, dev_blobstore)
    reloaded = chain_session.execute(
        select(Action).where(Action.id == outcome.action.id)
    ).scalar_one()
    assert reloaded.state is ActionState.FAILED


# --- Truncation and redaction ----------------------------------------------


def test_a_truncated_completion_is_flagged_rather_than_shipped_silently(
    chain_session: Session,
    task: Task,
    dev_keystore: LocalKeyStore,
    dev_blobstore: LocalBlobStore,
) -> None:
    """`PRODUCT.md` ?�25: never silently truncate work."""
    provider = FakeLLMProvider().register(
        trigger="revenue", response="Revenue rose 12% against", finish_reason="length"
    )
    outcome = call(chain_session, task, provider, dev_keystore, dev_blobstore)
    assert outcome.succeeded
    assert outcome.truncated
    recorded = payload_of(
        chain_session, outcome.action, model_call.EVIDENCE_RESPONSE, dev_keystore, dev_blobstore
    )
    assert recorded["finish_reason"] == "length"


def test_redaction_runs_over_a_prompt_before_it_is_persisted(
    chain_session: Session,
    task: Task,
    provider: FakeLLMProvider,
    dev_keystore: LocalKeyStore,
    dev_blobstore: LocalBlobStore,
) -> None:
    """D12: prompts are payloads like any other, and get redacted at write time.

    A credential can reach a prompt by accident � pasted into a requirement,
    quoted from an error, carried in a prior artifact. The prompt is persisted,
    so it goes through the same redactor as everything else, before the write.
    """
    outcome = call(
        chain_session,
        task,
        provider,
        dev_keystore,
        dev_blobstore,
        request=CompletionRequest(
            messages=(
                Message(
                    role=MessageRole.USER,
                    content=(
                        "explain revenue; the loader read "
                        "postgresql://svc_finance:hunter2-correct-horse@db.internal/ledger"
                    ),
                ),
            )
        ),
    )
    evidence = evidence_of(chain_session, outcome.action, model_call.EVIDENCE_REQUEST)
    assert evidence.redaction_count > 0
    raw = evidence_recorder.read_payload(
        evidence, tenant_id=TENANT_A, keystore=dev_keystore, blobstore=dev_blobstore
    )
    assert b"hunter2-correct-horse" not in raw
    # The record still says which system was reached and as whom.
    assert b"svc_finance" in raw
    assert b"explain revenue" in raw


# --- Provider independence --------------------------------------------------


def test_the_runtime_records_the_provider_it_used(
    chain_session: Session,
    task: Task,
    provider: FakeLLMProvider,
    dev_keystore: LocalKeyStore,
    dev_blobstore: LocalBlobStore,
) -> None:
    """The tool name is the capability; the provider is evidence. Swapping
    providers must not rewrite history's vocabulary."""
    outcome = call(chain_session, task, provider, dev_keystore, dev_blobstore)
    assert outcome.action.tool_name == "llm.complete"
    recorded = payload_of(
        chain_session, outcome.action, model_call.EVIDENCE_RESPONSE, dev_keystore, dev_blobstore
    )
    assert recorded["provider"] == "fake"
