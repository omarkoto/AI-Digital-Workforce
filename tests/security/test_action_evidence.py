"""Action lifecycle and evidence — CLAUDE.md §3, D12, D29, I10.

The central claim of the platform is enforced here: an action cannot reach
``succeeded`` without linked evidence, and evidence is redacted before it is
persisted rather than hidden when it is read.
"""

from __future__ import annotations

from uuid import uuid4

import pytest
from sqlalchemy import Engine, text
from sqlalchemy.exc import DBAPIError, IntegrityError, ProgrammingError
from sqlalchemy.orm import Session

from adw.adapters.blobstore_local import LocalBlobStore
from adw.adapters.keystore_local import LocalKeyStore
from adw.domain.hashing import digest_content
from adw.domain.states import ActionState, TaskState
from adw.models.action import Action, Evidence
from adw.models.task import Task
from adw.ports.keystore import KeyUnavailableError
from adw.services import action_recorder, evidence_recorder
from adw.services.action_recorder import EvidenceRequiredError
from adw.services.evidence_recorder import INLINE_THRESHOLD_BYTES
from tests.security.conftest import TENANT_A

pytestmark = pytest.mark.security

ACTOR = "agent:data-preparation"


@pytest.fixture
def task(chain_session: Session) -> Task:
    agent_id, version_id, execution_id = uuid4(), uuid4(), uuid4()
    chain_session.execute(
        text("INSERT INTO agent_definition (id, key, name) VALUES (:i, 'prep', 'Prep')"),
        {"i": agent_id},
    )
    chain_session.execute(
        text(
            "INSERT INTO agent_definition_version "
            "(id, agent_definition_id, version_no, instructions) VALUES (:i, :d, 1, 'go')"
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
def action(chain_session: Session, task: Task) -> Action:
    return action_recorder.plan_action(
        chain_session, task=task, sequence=1, tool_name="spreadsheet.read"
    )


def record(
    session: Session,
    action: Action,
    keystore: LocalKeyStore,
    blobstore: LocalBlobStore,
    payload: object = None,
) -> Evidence:
    return evidence_recorder.record_for_action(
        session,
        action=action,
        kind="tool_result",
        payload=payload if payload is not None else {"rows": 1412, "sheets": ["Actuals"]},
        keystore=keystore,
        blobstore=blobstore,
    )


# --------------------------------------------------------------------------
# The central claim
# --------------------------------------------------------------------------


def test_succeeded_is_refused_without_evidence(
    chain_session: Session, action: Action, dev_keystore: LocalKeyStore
) -> None:
    """CLAUDE.md §3: an agent's assertion is not evidence."""
    with pytest.raises(EvidenceRequiredError, match="without linked evidence"):
        action_recorder.transition(
            chain_session, action, ActionState.SUCCEEDED, keystore=dev_keystore, actor_id=ACTOR
        )


def test_succeeded_is_permitted_once_evidence_exists(
    chain_session: Session,
    action: Action,
    dev_keystore: LocalKeyStore,
    dev_blobstore: LocalBlobStore,
) -> None:
    record(chain_session, action, dev_keystore, dev_blobstore)
    action_recorder.transition(
        chain_session, action, ActionState.SUCCEEDED, keystore=dev_keystore, actor_id=ACTOR
    )
    assert action.state.value == ActionState.SUCCEEDED.value


def test_the_database_refuses_success_without_evidence_even_bypassing_the_service(
    chain_session: Session, action: Action
) -> None:
    """A rule enforced only in a service is one any future caller can route around."""
    with pytest.raises(DBAPIError, match="without linked evidence"):
        chain_session.execute(
            text("UPDATE action SET state = 'succeeded' WHERE id = :i"), {"i": action.id}
        )


def test_unverified_is_available_for_a_reported_completion(
    chain_session: Session, action: Action, dev_keystore: LocalKeyStore
) -> None:
    """The state that exists so success never has to be faked."""
    action_recorder.transition(
        chain_session, action, ActionState.UNVERIFIED, keystore=dev_keystore, actor_id=ACTOR
    )
    assert action.state.value == ActionState.UNVERIFIED.value


def test_failed_needs_no_evidence(
    chain_session: Session, action: Action, dev_keystore: LocalKeyStore
) -> None:
    action_recorder.transition(
        chain_session,
        action,
        ActionState.FAILED,
        keystore=dev_keystore,
        actor_id=ACTOR,
        failure_detail="tool exited 1",
    )
    assert action.state.value == ActionState.FAILED.value


def test_each_transition_writes_one_audit_record(
    chain_session: Session, action: Action, dev_keystore: LocalKeyStore
) -> None:
    before = chain_session.execute(text("SELECT count(*) FROM chain_record")).scalar_one()
    for state in (ActionState.ATTEMPTED, ActionState.EXECUTED):
        action_recorder.transition(
            chain_session, action, state, keystore=dev_keystore, actor_id=ACTOR
        )
    after = chain_session.execute(text("SELECT count(*) FROM chain_record")).scalar_one()
    assert after - before == 2


# --------------------------------------------------------------------------
# Redaction before persistence
# --------------------------------------------------------------------------


def test_a_secret_never_reaches_the_database(
    chain_session: Session,
    action: Action,
    dev_keystore: LocalKeyStore,
    dev_blobstore: LocalBlobStore,
) -> None:
    """G12: redaction happens before the write, not at read time."""
    secret = "AKIAIOSFODNN7EXAMPLE"
    evidence = record(
        chain_session,
        action,
        dev_keystore,
        dev_blobstore,
        {"note": f"used {secret}", "password": "hunter2"},
    )
    assert evidence.redaction_count >= 2

    plaintext = evidence_recorder.read_payload(
        evidence, tenant_id=TENANT_A, keystore=dev_keystore, blobstore=dev_blobstore
    )
    assert secret.encode() not in plaintext
    assert b"hunter2" not in plaintext


def test_redaction_count_records_that_redaction_ran(
    chain_session: Session,
    action: Action,
    dev_keystore: LocalKeyStore,
    dev_blobstore: LocalBlobStore,
) -> None:
    clean = record(chain_session, action, dev_keystore, dev_blobstore, {"rows": 10})
    assert clean.redaction_count == 0


def test_payload_is_stored_encrypted(
    chain_session: Session,
    action: Action,
    dev_keystore: LocalKeyStore,
    dev_blobstore: LocalBlobStore,
) -> None:
    evidence = record(chain_session, action, dev_keystore, dev_blobstore, {"sheet": "MARCH-DATA"})
    assert evidence.inline_ciphertext is not None
    assert b"MARCH-DATA" not in evidence.inline_ciphertext
    assert evidence.key_id


def test_digest_is_over_the_raw_ciphertext(
    chain_session: Session,
    action: Action,
    dev_keystore: LocalKeyStore,
    dev_blobstore: LocalBlobStore,
) -> None:
    """D29: content is digested raw, never canonicalized first."""
    evidence = record(chain_session, action, dev_keystore, dev_blobstore)
    assert evidence.inline_ciphertext is not None
    assert evidence.content_digest == digest_content(evidence.inline_ciphertext)


# --------------------------------------------------------------------------
# Storage routing and erasure
# --------------------------------------------------------------------------


def test_small_evidence_is_inline(
    chain_session: Session,
    action: Action,
    dev_keystore: LocalKeyStore,
    dev_blobstore: LocalBlobStore,
) -> None:
    evidence = record(chain_session, action, dev_keystore, dev_blobstore, {"n": 1})
    assert evidence.inline_ciphertext is not None
    assert evidence.blob_key is None


def test_large_evidence_goes_to_the_blob_store(
    chain_session: Session,
    action: Action,
    dev_keystore: LocalKeyStore,
    dev_blobstore: LocalBlobStore,
) -> None:
    evidence = record(
        chain_session,
        action,
        dev_keystore,
        dev_blobstore,
        {"body": "x" * (INLINE_THRESHOLD_BYTES + 1)},
    )
    assert evidence.blob_key is not None
    assert evidence.inline_ciphertext is None
    assert evidence.size_bytes > INLINE_THRESHOLD_BYTES

    plaintext = evidence_recorder.read_payload(
        evidence, tenant_id=TENANT_A, keystore=dev_keystore, blobstore=dev_blobstore
    )
    assert b"x" * 100 in plaintext


def test_destroying_the_key_leaves_the_record_but_not_the_content(
    chain_session: Session,
    action: Action,
    dev_keystore: LocalKeyStore,
    dev_blobstore: LocalBlobStore,
) -> None:
    """D1: erasure removes readability, never the fact that evidence existed."""
    evidence = record(chain_session, action, dev_keystore, dev_blobstore)
    digest = evidence.content_digest
    dev_keystore.destroy(TENANT_A)

    with pytest.raises(KeyUnavailableError):
        evidence_recorder.read_payload(
            evidence, tenant_id=TENANT_A, keystore=dev_keystore, blobstore=dev_blobstore
        )
    still_there = chain_session.get(Evidence, evidence.id)
    assert still_there is not None
    assert still_there.content_digest == digest


# --------------------------------------------------------------------------
# Invariants in the schema
# --------------------------------------------------------------------------


def test_evidence_must_attach_to_exactly_one_subject(
    chain_session: Session, action: Action
) -> None:
    for action_id, gate_id in ((None, None), (action.id, uuid4())):
        # A savepoint, not a rollback: rolling the whole transaction back would
        # discard the fixture's own rows and make the next case vacuous.
        with (
            pytest.raises(IntegrityError, match="exactly_one_subject"),
            chain_session.begin_nested(),
        ):
            chain_session.execute(
                text(
                    "INSERT INTO evidence (id, tenant_id, action_id, gate_decision_id, kind, "
                    "inline_ciphertext, key_id, content_digest, size_bytes) "
                    "VALUES (:i, :t, :a, :g, 'k', :c, 'key', 'd', 1)"
                ),
                {"i": uuid4(), "t": TENANT_A, "a": action_id, "g": gate_id, "c": b"x"},
            )


def test_evidence_is_immutable(
    chain_session: Session,
    action: Action,
    dev_keystore: LocalKeyStore,
    dev_blobstore: LocalBlobStore,
) -> None:
    record(chain_session, action, dev_keystore, dev_blobstore)
    chain_session.flush()
    for statement in ("UPDATE evidence SET kind = 'forged'", "DELETE FROM evidence"):
        # Savepoints keep the evidence row alive between cases; a full rollback
        # would leave the second statement matching nothing, so a per-row trigger
        # would never fire and the test would pass for the wrong reason.
        with pytest.raises(DBAPIError, match="immutable"), chain_session.begin_nested():
            chain_session.execute(text(statement))


def test_action_and_evidence_are_tenant_isolated(app_engine: Engine, migrated_schema: None) -> None:
    with app_engine.begin() as conn:
        for table in ("action", "evidence"):
            assert conn.execute(text(f"SELECT count(*) FROM {table}")).scalar_one() == 0


def test_runtime_role_cannot_mutate_evidence(app_engine: Engine, migrated_schema: None) -> None:
    with pytest.raises(ProgrammingError, match="permission denied"), app_engine.begin() as conn:
        conn.execute(text("SELECT set_config('app.tenant_id', :t, true)"), {"t": str(TENANT_A)})
        conn.execute(text("DELETE FROM evidence"))
