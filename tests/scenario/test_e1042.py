"""The Phase 1 proof criterion — PHASE-1-IMPLEMENTATION-PLAN §31c and §37.

Three parts, and all three must hold:

1. Drive execution ``E-1042`` end to end with a scripted agent and canned tools,
   including a deliberate gate failure that triggers rework and a human approval
   by someone who is neither the requester nor any producer.
2. Reconstruct it **from the database alone** — no running service, no original
   inputs, no model.
3. Verify both chains, then deliberately alter a record and confirm verification
   fails. A tamper-detection test that does not detect tampering proves nothing.

No LLM, no real tools, no orchestrator. This proves the *record*, which is what
Phase 1 is for.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import timedelta
from uuid import UUID, uuid4

import pytest
from sqlalchemy import Engine, text
from sqlalchemy.orm import Session

from adw.adapters.blobstore_local import LocalBlobStore
from adw.adapters.keystore_local import LocalKeyStore
from adw.domain.errors import ChainIntegrityError
from adw.domain.states import ActionState, GateVerdict, TaskState
from adw.models.artifact import ArtifactDefinitionVersion, ArtifactVersion
from adw.models.gate import GateDecision, GateDefinitionVersion
from adw.models.queue import DispatchJob
from adw.models.task import Task
from adw.services import (
    action_recorder,
    anchor_writer,
    approval_service,
    artifact_service,
    evidence_recorder,
    gate_engine,
    rework_controller,
    task_service,
)
from adw.verification.anchor_verifier import (
    verify_anchor_chain_integrity,
    verify_tenant_against_anchors,
)
from adw.verification.chain_verifier import verify_tenant_chain
from adw.verification.reconstructor import event_sequence, reconstruct, render
from adw.workers import dispatcher
from tests.security.conftest import TENANT_A

pytestmark = pytest.mark.scenario

REQUESTER = "human:amira@northwind"
CONTROLLER = "human:khaled@northwind"
ORCHESTRATOR = "platform:engagement-lead"

PREP = "agent:data-preparation"
COMMENTARY = "agent:commentary"


@dataclass(frozen=True, slots=True)
class Outcome:
    """What one run of E-1042 produced, typed so assertions need no casts."""

    v1: ArtifactVersion
    v2: ArtifactVersion
    failed: GateDecision
    passed: GateDecision
    approval: GateDecision


DATASET: list[dict[str, str]] = [{"cost_centre": "MKT-01", "variance": "1243880"}]
WRONG: dict[str, object] = {
    "narrative": "Marketing overspend of 1.2m against budget.",
    "dataset": DATASET,
}
CORRECTED: dict[str, object] = {
    "narrative": "Marketing overspend of 1243880 against budget.",
    "dataset": DATASET,
}


@pytest.fixture
def e1042(
    chain_session: Session, dev_keystore: LocalKeyStore, dev_blobstore: LocalBlobStore
) -> dict[str, object]:
    """Seed the definitions and execution the scenario runs against."""
    session = chain_session
    ids = {name: uuid4() for name in ("agent", "agent_v1", "execution", "artdef", "artdef_v1")}

    session.execute(
        text(
            "INSERT INTO agent_definition (id, key, name) VALUES (:i, 'commentary', 'Commentary')"
        ),
        {"i": ids["agent"]},
    )
    session.execute(
        text(
            "INSERT INTO agent_definition_version "
            "(id, agent_definition_id, version_no, instructions) VALUES (:i, :d, 1, 'explain')"
        ),
        {"i": ids["agent_v1"], "d": ids["agent"]},
    )
    session.execute(
        text(
            "INSERT INTO execution (id, tenant_id, requester_identity, state) "
            "VALUES (:i, :t, :r, 'running')"
        ),
        {"i": ids["execution"], "t": TENANT_A, "r": REQUESTER},
    )
    session.execute(
        text("INSERT INTO artifact_definition (id, key, name) VALUES (:i, 'comm', 'Commentary')"),
        {"i": ids["artdef"]},
    )
    session.execute(
        text(
            "INSERT INTO artifact_definition_version "
            "(id, artifact_definition_id, version_no, content_type, schema_json) "
            "VALUES (:i, :d, 1, 'application/json', '{}')"
        ),
        {"i": ids["artdef_v1"], "d": ids["artdef"]},
    )

    gates: dict[str, GateDefinitionVersion] = {}
    for key, rule_id, requires_human in (
        ("g4-traceability", "figures_traceable", False),
        ("g5-final-review", "human_review", True),
    ):
        definition_id, version_id = uuid4(), uuid4()
        session.execute(
            text("INSERT INTO gate_definition (id, key, name) VALUES (:i, :k, :n)"),
            {"i": definition_id, "k": key, "n": key},
        )
        session.execute(
            text(
                "INSERT INTO gate_definition_version (id, gate_definition_id, version_no, "
                "rule_id, evaluation_kind, requires_human, config_json) "
                "VALUES (:i, :d, 1, :r, 'deterministic', :h, '{}')"
            ),
            {"i": version_id, "d": definition_id, "r": rule_id, "h": requires_human},
        )
        session.flush()
        version = session.get(GateDefinitionVersion, version_id)
        assert version is not None
        gates[key] = version

    task = Task(
        tenant_id=TENANT_A,
        execution_id=ids["execution"],
        sequence=4,
        agent_definition_version_id=ids["agent_v1"],
        state=TaskState.PLANNED,
        attempt_no=1,
    )
    session.add(task)
    session.flush()

    artdef_version = session.get(ArtifactDefinitionVersion, ids["artdef_v1"])
    assert artdef_version is not None
    artifact = artifact_service.create_artifact(
        session,
        tenant_id=TENANT_A,
        execution_id=ids["execution"],
        artifact_definition_id=ids["artdef"],
        name="variance-commentary",
    )
    return {
        "task": task,
        "artifact": artifact,
        "artdef_version": artdef_version,
        "gates": gates,
        "execution_id": ids["execution"],
    }


def produce(
    session: Session,
    world: dict[str, object],
    keystore: LocalKeyStore,
    blobstore: LocalBlobStore,
    payload: dict[str, object],
) -> ArtifactVersion:
    """The scripted agent's whole job: run a canned tool, then write an artifact."""
    task = world["task"]
    assert isinstance(task, Task)

    action = action_recorder.plan_action(
        session, task=task, sequence=int(task.attempt_no), tool_name="tabular.compute"
    )
    action_recorder.transition(
        session, action, ActionState.ATTEMPTED, keystore=keystore, actor_id=COMMENTARY
    )
    action_recorder.transition(
        session, action, ActionState.EXECUTED, keystore=keystore, actor_id=COMMENTARY
    )
    evidence_recorder.record_for_action(
        session,
        action=action,
        kind="tool_result",
        payload={"rows": len(DATASET), "duration_ms": 840, "exit_status": 0},
        keystore=keystore,
        blobstore=blobstore,
    )
    action_recorder.transition(
        session, action, ActionState.SUCCEEDED, keystore=keystore, actor_id=COMMENTARY
    )

    return artifact_service.append_version(
        session,
        artifact=world["artifact"],  # type: ignore[arg-type]
        content=json.dumps(payload).encode("utf-8"),
        content_type="application/json",
        producing_task=task,
        producing_agent_identity=COMMENTARY,
        definition_version=world["artdef_version"],  # type: ignore[arg-type]
        keystore=keystore,
        blobstore=blobstore,
        actor_id=COMMENTARY,
    )


def drive_e1042(
    session: Session,
    world: dict[str, object],
    keystore: LocalKeyStore,
    blobstore: LocalBlobStore,
) -> Outcome:
    """Run the execution to a signed approval, through one rework loop."""
    task = world["task"]
    assert isinstance(task, Task)
    gates = world["gates"]
    assert isinstance(gates, dict)

    def move(*states: TaskState) -> None:
        for state in states:
            task_service.transition(session, task, state, keystore=keystore, actor_id=ORCHESTRATOR)

    # --- Attempt 1: a plausible figure with no source ----------------------
    move(TaskState.QUEUED, TaskState.RUNNING)
    v1 = produce(session, world, keystore, blobstore, WRONG)
    move(TaskState.PRODUCING, TaskState.AWAITING_GATE)

    failed = gate_engine.evaluate(
        session,
        artifact_version=v1,
        gate_definition_version=gates["g4-traceability"],
        task_id=task.id,
        decided_by_identity=ORCHESTRATOR,
        keystore=keystore,
        blobstore=blobstore,
        actor_id=ORCHESTRATOR,
    )
    assert failed.verdict is GateVerdict.FAIL

    attempt = rework_controller.open_rework(
        session, task=task, decision=failed, keystore=keystore, actor_id=ORCHESTRATOR
    )
    assert attempt is not None
    assert attempt.attempt_no == 1

    # --- Attempt 2: corrected, and it passes -------------------------------
    move(TaskState.RUNNING)
    v2 = produce(session, world, keystore, blobstore, CORRECTED)
    move(TaskState.PRODUCING, TaskState.AWAITING_GATE)

    passed = gate_engine.evaluate(
        session,
        artifact_version=v2,
        gate_definition_version=gates["g4-traceability"],
        task_id=task.id,
        decided_by_identity=ORCHESTRATOR,
        keystore=keystore,
        blobstore=blobstore,
        actor_id=ORCHESTRATOR,
    )
    assert passed.verdict is GateVerdict.PASS
    move(TaskState.PASSED)

    # --- G5: the human gate every execution must end in (D6) ---------------
    item = approval_service.request_approval(
        session,
        artifact_version=v2,
        gate_definition_version=gates["g5-final-review"],
        task_id=task.id,
        requester_identity=REQUESTER,
        keystore=keystore,
        actor_id=ORCHESTRATOR,
    )
    approved = approval_service.decide(
        session,
        item=item,
        approved=True,
        decided_by_identity=CONTROLLER,
        keystore=keystore,
        actor_id=CONTROLLER,
    )
    session.flush()
    return Outcome(v1=v1, v2=v2, failed=failed, passed=passed, approval=approved)


# --------------------------------------------------------------------------
# Part 1 — drive it end to end
# --------------------------------------------------------------------------


def test_e1042_runs_to_a_signed_approval(
    chain_session: Session,
    e1042: dict[str, object],
    dev_keystore: LocalKeyStore,
    dev_blobstore: LocalBlobStore,
) -> None:
    outcome = drive_e1042(chain_session, e1042, dev_keystore, dev_blobstore)
    approval = outcome.approval
    assert approval.verdict is GateVerdict.PASS
    assert approval.decided_by_identity == CONTROLLER


def test_the_approver_is_neither_the_requester_nor_a_producer(
    chain_session: Session,
    e1042: dict[str, object],
    dev_keystore: LocalKeyStore,
    dev_blobstore: LocalBlobStore,
) -> None:
    """D4/I5, at the moment that matters most: the final signature."""
    outcome = drive_e1042(chain_session, e1042, dev_keystore, dev_blobstore)
    approval = outcome.approval
    assert approval.decided_by_identity not in (REQUESTER, COMMENTARY)
    assert approval.producer_identity == COMMENTARY


def test_both_commentary_versions_survive(
    chain_session: Session,
    e1042: dict[str, object],
    dev_keystore: LocalKeyStore,
    dev_blobstore: LocalBlobStore,
) -> None:
    """The wrong figure is not erased by its correction — it is superseded."""
    outcome = drive_e1042(chain_session, e1042, dev_keystore, dev_blobstore)
    first = artifact_service.read_content(
        outcome.v1,
        keystore=dev_keystore,
        blobstore=dev_blobstore,
    )
    assert b"1.2m" in first
    assert json.loads(first)["narrative"] != CORRECTED["narrative"]


def test_no_action_reached_success_without_evidence(
    chain_session: Session,
    e1042: dict[str, object],
    dev_keystore: LocalKeyStore,
    dev_blobstore: LocalBlobStore,
) -> None:
    """I10 across the whole run, not just at one call site."""
    drive_e1042(chain_session, e1042, dev_keystore, dev_blobstore)
    unproven = chain_session.execute(
        text(
            "SELECT count(*) FROM action a WHERE a.state = 'succeeded' "
            "AND NOT EXISTS (SELECT 1 FROM evidence e WHERE e.action_id = a.id)"
        )
    ).scalar_one()
    assert unproven == 0


# --------------------------------------------------------------------------
# Part 2 — reconstruct from the database alone
# --------------------------------------------------------------------------


def test_the_execution_reconstructs_from_persisted_state(
    chain_session: Session,
    e1042: dict[str, object],
    dev_keystore: LocalKeyStore,
    dev_blobstore: LocalBlobStore,
) -> None:
    """CLAUDE.md §1: if it cannot be reconstructed, it did not happen."""
    drive_e1042(chain_session, e1042, dev_keystore, dev_blobstore)

    narrative = reconstruct(chain_session, tenant_id=TENANT_A, keystore=dev_keystore)
    events = event_sequence(narrative)

    assert "task.transitioned" in events
    assert "action.transitioned" in events
    assert "artifact.version_created" in events
    assert "gate.decided" in events
    assert "task.rework_opened" in events
    assert "approval.requested" in events
    assert "approval.decided" in events

    story = render(narrative)
    # The record carries the figure the gate rejected — "1.2", since the number
    # pattern matches the numeral and not the "m" suffix — together with the rule
    # that caught it. Someone reading the record later can see *why* it failed.
    assert "1.2" in story, "the rejected figure should be recoverable from the record"
    assert "figures_traceable" in story, "the rule that caught it should be named"
    assert CONTROLLER in story, "the approver should be nameable from the record alone"
    assert "rework" in story.lower()


def test_the_narrative_is_ordered_by_sequence_not_by_time(
    chain_session: Session,
    e1042: dict[str, object],
    dev_keystore: LocalKeyStore,
    dev_blobstore: LocalBlobStore,
) -> None:
    """I11: the sequence is the authoritative order; time is evidence of when."""
    drive_e1042(chain_session, e1042, dev_keystore, dev_blobstore)
    narrative = reconstruct(chain_session, tenant_id=TENANT_A, keystore=dev_keystore)
    sequences = [entry.seq for entry in narrative]
    assert sequences == sorted(sequences)
    assert sequences == list(range(1, len(sequences) + 1))


def test_the_record_survives_erasure_even_though_the_content_does_not(
    chain_session: Session,
    e1042: dict[str, object],
    dev_keystore: LocalKeyStore,
    dev_blobstore: LocalBlobStore,
) -> None:
    """D1: erasure removes readability, never the fact that something happened."""
    drive_e1042(chain_session, e1042, dev_keystore, dev_blobstore)
    before = len(reconstruct(chain_session, tenant_id=TENANT_A, keystore=dev_keystore))

    dev_keystore.destroy(TENANT_A)
    after = reconstruct(chain_session, tenant_id=TENANT_A, keystore=dev_keystore)

    assert len(after) == before
    assert all(entry.event_type for entry in after)
    assert all("unreadable" in entry.detail for entry in after)
    # And the chain still verifies without any key at all (I12).
    assert verify_tenant_chain(chain_session, TENANT_A) == before


# --------------------------------------------------------------------------
# Part 3 — verify, then tamper, and confirm detection
# --------------------------------------------------------------------------


def test_both_chains_verify_then_tampering_is_detected(
    chain_session: Session,
    e1042: dict[str, object],
    dev_keystore: LocalKeyStore,
    dev_blobstore: LocalBlobStore,
) -> None:
    """A tamper-detection test that does not detect tampering proves nothing."""
    drive_e1042(chain_session, e1042, dev_keystore, dev_blobstore)
    chain_session.flush()

    length = verify_tenant_chain(chain_session, TENANT_A)
    assert length > 10
    anchor_writer.run_anchoring_pass(chain_session)
    assert verify_anchor_chain_integrity(chain_session) == 1
    assert verify_tenant_against_anchors(chain_session, TENANT_A) == 1

    # Now alter a record the way an operator with database access would.
    chain_session.execute(text("ALTER TABLE chain_record DISABLE TRIGGER chain_record_append_only"))
    chain_session.execute(text("UPDATE chain_record SET actor_id = 'agent:forged' WHERE seq = 3"))
    chain_session.execute(text("ALTER TABLE chain_record ENABLE TRIGGER chain_record_append_only"))

    with pytest.raises(ChainIntegrityError, match="seq 3"):
        verify_tenant_chain(chain_session, TENANT_A)


def test_a_rewritten_chain_is_caught_by_the_anchors(
    chain_session: Session,
    e1042: dict[str, object],
    dev_keystore: LocalKeyStore,
    dev_blobstore: LocalBlobStore,
) -> None:
    """The scenario a chain alone cannot catch, on the real execution."""
    from adw.domain.chain import ChainRecordHeader, seal

    drive_e1042(chain_session, e1042, dev_keystore, dev_blobstore)
    chain_session.flush()
    anchor_writer.run_anchoring_pass(chain_session)

    chain_session.execute(text("ALTER TABLE chain_record DISABLE TRIGGER chain_record_append_only"))
    rows = chain_session.execute(
        text(
            "SELECT seq, prev_hash, event_type, actor_id, event_time, payload_digest, "
            "key_id, hash_algorithm FROM chain_record ORDER BY seq"
        )
    ).all()
    prev = rows[0].prev_hash
    for row in rows:
        actor = "agent:forged" if row.seq >= 3 else row.actor_id
        sealed = seal(
            ChainRecordHeader(
                tenant_id=TENANT_A,
                seq=row.seq,
                prev_hash=prev,
                event_type=row.event_type,
                actor_id=actor,
                event_time=row.event_time,
                payload_digest=row.payload_digest,
                key_id=row.key_id,
                hash_algorithm=row.hash_algorithm,
            )
        )
        chain_session.execute(
            text(
                "UPDATE chain_record SET prev_hash = :p, actor_id = :a, record_hash = :h "
                "WHERE seq = :s"
            ),
            {"p": prev, "a": actor, "h": sealed.record_hash, "s": row.seq},
        )
        prev = sealed.record_hash
    chain_session.execute(text("UPDATE chain_head SET head_hash = :h"), {"h": prev})
    chain_session.execute(text("ALTER TABLE chain_record ENABLE TRIGGER chain_record_append_only"))

    # Internally consistent — and still caught.
    verify_tenant_chain(chain_session, TENANT_A)
    with pytest.raises(ChainIntegrityError, match="rewritten"):
        verify_tenant_against_anchors(chain_session, TENANT_A)


# --------------------------------------------------------------------------
# The queue and the worker loop
# --------------------------------------------------------------------------


def test_a_job_runs_once_however_often_it_is_delivered(
    owner_engine: Engine, migrated_schema: None
) -> None:
    """D17: at-least-once delivery is the only delivery a database queue gives."""
    calls: list[UUID] = []

    def handler(session: Session, job: DispatchJob) -> dispatcher.HandlerResult:
        calls.append(job.target_id)
        return dispatcher.HandlerResult(outcome="ok")

    target = uuid4()
    with Session(owner_engine) as session:
        session.execute(text("SELECT set_config('app.tenant_id', :t, true)"), {"t": str(TENANT_A)})
        session.execute(
            text("INSERT INTO tenant (id, slug, name) VALUES (:i, 'northwind', 'Northwind')"),
            {"i": TENANT_A},
        )
        for _ in range(3):
            with session.begin_nested():
                try:
                    dispatcher.enqueue(
                        session,
                        tenant_id=TENANT_A,
                        job_type="task.run",
                        target_id=target,
                        idempotency_key="task:abc:attempt:1:step:run",
                    )
                except Exception:  # noqa: S110
                    pass
        session.commit()

    handlers: dict[str, dispatcher.Handler] = {"task.run": handler}
    for _ in range(3):
        dispatcher.run_once(owner_engine, worker_id="w1", handlers=handlers, limit=5)

    assert len(calls) == 1, "a redelivered job must produce no second effect"


def test_the_queue_carries_no_business_content(owner_engine: Engine, migrated_schema: None) -> None:
    """I13, asserted rather than trusted: a payload column fails the build."""
    from adw.models.queue import QUEUE_COLUMNS

    with owner_engine.begin() as connection:
        columns = {
            str(row[0])
            for row in connection.execute(
                text(
                    "SELECT column_name FROM information_schema.columns "
                    "WHERE table_name = 'dispatch_queue'"
                )
            )
        }
    assert columns == set(QUEUE_COLUMNS)


def test_only_one_scheduler_leader_at_a_time(owner_engine: Engine, migrated_schema: None) -> None:
    """P5's advisory lock: a second would double every scheduled pass."""
    from adw.workers import scheduler

    with Session(owner_engine) as first, Session(owner_engine) as second:
        assert scheduler.try_become_leader(first) is True
        assert scheduler.try_become_leader(second) is False
        scheduler.release_leadership(first)
        assert scheduler.try_become_leader(second) is True
        scheduler.release_leadership(second)


def test_sla_expiry_is_deterministic_under_the_scheduler(
    chain_session: Session,
    e1042: dict[str, object],
    dev_keystore: LocalKeyStore,
    dev_blobstore: LocalBlobStore,
) -> None:
    """D7 through the scheduler's own path: expiry yields no verdict."""
    task = e1042["task"]
    assert isinstance(task, Task)
    gates = e1042["gates"]
    assert isinstance(gates, dict)

    task_service.transition(
        chain_session, task, TaskState.QUEUED, keystore=dev_keystore, actor_id=ORCHESTRATOR
    )
    task_service.transition(
        chain_session, task, TaskState.RUNNING, keystore=dev_keystore, actor_id=ORCHESTRATOR
    )
    version = produce(chain_session, e1042, dev_keystore, dev_blobstore, CORRECTED)

    item = approval_service.request_approval(
        chain_session,
        artifact_version=version,
        gate_definition_version=gates["g5-final-review"],
        task_id=task.id,
        requester_identity=REQUESTER,
        keystore=dev_keystore,
        actor_id=ORCHESTRATOR,
        sla_hours=0,
    )
    chain_session.flush()

    before = chain_session.execute(text("SELECT count(*) FROM gate_decision")).scalar_one()
    expired = approval_service.run_expiry_pass(
        chain_session,
        keystore=dev_keystore,
        actor_id="platform:scheduler",
        now=item.sla_deadline + timedelta(seconds=1),
    )
    after = chain_session.execute(text("SELECT count(*) FROM gate_decision")).scalar_one()

    assert expired == 1
    assert after == before
    assert item.gate_decision_id is None
