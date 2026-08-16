"""Control gates, rework, and human approval — D4, D6, D7, D11, D13, I5.

Three claims the product is sold on are proved here:

* the producer can never approve their own work,
* rework is bounded and visible rather than an invisible retry,
* an approval that times out never becomes an approval.
"""

from __future__ import annotations

import json
from datetime import timedelta
from uuid import uuid4

import pytest
from sqlalchemy import Engine, text
from sqlalchemy.exc import DBAPIError, IntegrityError, ProgrammingError
from sqlalchemy.orm import Session

from adw.adapters.blobstore_local import LocalBlobStore
from adw.adapters.keystore_local import LocalKeyStore
from adw.domain.states import ApprovalState, GateEvaluationKind, GateVerdict, TaskState
from adw.models.artifact import Artifact, ArtifactDefinitionVersion, ArtifactVersion
from adw.models.gate import ApprovalItem, GateDecision, GateDefinitionVersion, ReworkAttempt
from adw.models.task import Task
from adw.services import approval_service, artifact_service, gate_engine, rework_controller
from adw.services.approval_service import ApprovalNotPendingError, IneligibleApproverError
from adw.services.gate_engine import SelfApprovalError, UnknownRuleError
from adw.services.rework_controller import NotAFailureError
from tests.security.conftest import TENANT_A

pytestmark = pytest.mark.security

PRODUCER = "agent:commentary"
REVIEWER = "human:khaled@northwind"
REQUESTER = "human:amira@northwind"
ACTOR = "platform:orchestrator"

TRACEABLE: dict[str, object] = {
    "narrative": "Marketing overspend of 1243880 against budget.",
    "dataset": [{"cost_centre": "MKT-01", "variance": "1243880"}],
}
UNTRACEABLE: dict[str, object] = {
    "narrative": "Marketing overspend of 1.2m against budget.",
    "dataset": [{"cost_centre": "MKT-01", "variance": "1243880"}],
}


@pytest.fixture
def world(
    chain_session: Session, dev_keystore: LocalKeyStore, dev_blobstore: LocalBlobStore
) -> dict[str, object]:
    """An execution with a task, an artifact, and gate definitions."""
    agent_id, agent_version_id, execution_id = uuid4(), uuid4(), uuid4()
    chain_session.execute(
        text("INSERT INTO agent_definition (id, key, name) VALUES (:i, 'c', 'Commentary')"),
        {"i": agent_id},
    )
    chain_session.execute(
        text(
            "INSERT INTO agent_definition_version "
            "(id, agent_definition_id, version_no, instructions) VALUES (:i, :d, 1, 'write')"
        ),
        {"i": agent_version_id, "d": agent_id},
    )
    chain_session.execute(
        text(
            "INSERT INTO execution (id, tenant_id, requester_identity, state) "
            "VALUES (:i, :t, :r, 'running')"
        ),
        {"i": execution_id, "t": TENANT_A, "r": REQUESTER},
    )
    task = Task(
        tenant_id=TENANT_A,
        execution_id=execution_id,
        sequence=1,
        agent_definition_version_id=agent_version_id,
        state=TaskState.AWAITING_GATE,
        attempt_no=1,
    )
    chain_session.add(task)

    artifact_definition_id, artifact_definition_version_id = uuid4(), uuid4()
    chain_session.execute(
        text("INSERT INTO artifact_definition (id, key, name) VALUES (:i, 'comm', 'Commentary')"),
        {"i": artifact_definition_id},
    )
    chain_session.execute(
        text(
            "INSERT INTO artifact_definition_version "
            "(id, artifact_definition_id, version_no, content_type, schema_json) "
            "VALUES (:i, :d, 1, 'application/json', '{}')"
        ),
        {"i": artifact_definition_version_id, "d": artifact_definition_id},
    )

    gates: dict[str, GateDefinitionVersion] = {}
    specs = (
        ("traceability", "figures_traceable", GateEvaluationKind.DETERMINISTIC, False, "{}"),
        (
            "completeness",
            "required_fields_present",
            GateEvaluationKind.DETERMINISTIC,
            False,
            json.dumps({"required_fields": ["narrative"]}),
        ),
        ("final-review", "human", GateEvaluationKind.DETERMINISTIC, True, "{}"),
        ("model-check", "figures_traceable", GateEvaluationKind.MODEL_ASSESSED, False, "{}"),
    )
    for key, rule_id, kind, requires_human, config in specs:
        definition_id, version_id = uuid4(), uuid4()
        chain_session.execute(
            text("INSERT INTO gate_definition (id, key, name) VALUES (:i, :k, :n)"),
            {"i": definition_id, "k": key, "n": key.title()},
        )
        chain_session.execute(
            text(
                "INSERT INTO gate_definition_version (id, gate_definition_id, version_no, "
                "rule_id, evaluation_kind, requires_human, config_json) "
                "VALUES (:i, :d, 1, :r, :e, :h, :c)"
            ),
            {
                "i": version_id,
                "d": definition_id,
                "r": rule_id,
                "e": kind.value,
                "h": requires_human,
                "c": config,
            },
        )
        chain_session.flush()
        version = chain_session.get(GateDefinitionVersion, version_id)
        assert version is not None
        gates[key] = version

    artifact = artifact_service.create_artifact(
        chain_session,
        tenant_id=TENANT_A,
        execution_id=execution_id,
        artifact_definition_id=artifact_definition_id,
        name="variance-commentary",
    )
    definition_version = chain_session.get(
        ArtifactDefinitionVersion, artifact_definition_version_id
    )
    assert definition_version is not None

    return {
        "task": task,
        "artifact": artifact,
        "artifact_definition_version": definition_version,
        "gates": gates,
        "execution_id": execution_id,
    }


def make_version(
    session: Session,
    world: dict[str, object],
    keystore: LocalKeyStore,
    blobstore: LocalBlobStore,
    payload: dict[str, object],
    producer: str = PRODUCER,
) -> ArtifactVersion:
    artifact = world["artifact"]
    assert isinstance(artifact, Artifact)
    task = world["task"]
    assert isinstance(task, Task)
    definition_version = world["artifact_definition_version"]
    assert isinstance(definition_version, ArtifactDefinitionVersion)
    return artifact_service.append_version(
        session,
        artifact=artifact,
        content=json.dumps(payload).encode("utf-8"),
        content_type="application/json",
        producing_task=task,
        producing_agent_identity=producer,
        definition_version=definition_version,
        keystore=keystore,
        blobstore=blobstore,
        actor_id=ACTOR,
    )


def gate(world: dict[str, object], key: str) -> GateDefinitionVersion:
    gates = world["gates"]
    assert isinstance(gates, dict)
    version = gates[key]
    assert isinstance(version, GateDefinitionVersion)
    return version


def run_gate(
    session: Session,
    world: dict[str, object],
    version: ArtifactVersion,
    keystore: LocalKeyStore,
    blobstore: LocalBlobStore,
    key: str = "traceability",
    decided_by: str = REVIEWER,
) -> GateDecision:
    task = world["task"]
    assert isinstance(task, Task)
    return gate_engine.evaluate(
        session,
        artifact_version=version,
        gate_definition_version=gate(world, key),
        task_id=task.id,
        decided_by_identity=decided_by,
        keystore=keystore,
        blobstore=blobstore,
        actor_id=ACTOR,
    )


# --------------------------------------------------------------------------
# Deterministic evaluation
# --------------------------------------------------------------------------


def test_traceable_narrative_passes(
    chain_session: Session,
    world: dict[str, object],
    dev_keystore: LocalKeyStore,
    dev_blobstore: LocalBlobStore,
) -> None:
    version = make_version(chain_session, world, dev_keystore, dev_blobstore, TRACEABLE)
    decision = run_gate(chain_session, world, version, dev_keystore, dev_blobstore)
    assert decision.verdict is GateVerdict.PASS


def test_a_figure_with_no_source_fails(
    chain_session: Session,
    world: dict[str, object],
    dev_keystore: LocalKeyStore,
    dev_blobstore: LocalBlobStore,
) -> None:
    """The characteristic failure of a model writing about numbers.

    An injected instruction cannot talk a deterministic check into passing —
    which is why D13 leans on gates as the compensating control.
    """
    version = make_version(chain_session, world, dev_keystore, dev_blobstore, UNTRACEABLE)
    decision = run_gate(chain_session, world, version, dev_keystore, dev_blobstore)
    assert decision.verdict is GateVerdict.FAIL
    assert "1.2" in str(decision.failure_detail)


def test_missing_required_field_fails(
    chain_session: Session,
    world: dict[str, object],
    dev_keystore: LocalKeyStore,
    dev_blobstore: LocalBlobStore,
) -> None:
    version = make_version(
        chain_session, world, dev_keystore, dev_blobstore, {"narrative": "", "dataset": []}
    )
    decision = run_gate(
        chain_session, world, version, dev_keystore, dev_blobstore, key="completeness"
    )
    assert decision.verdict is GateVerdict.FAIL


def test_a_verdict_records_everything_needed_to_defend_it(
    chain_session: Session,
    world: dict[str, object],
    dev_keystore: LocalKeyStore,
    dev_blobstore: LocalBlobStore,
) -> None:
    """DESIGN.md §11.5: approver, timestamp, artifact version, and rule."""
    version = make_version(chain_session, world, dev_keystore, dev_blobstore, TRACEABLE)
    decision = run_gate(chain_session, world, version, dev_keystore, dev_blobstore)
    assert decision.decided_by_identity == REVIEWER
    assert decision.producer_identity == PRODUCER
    assert decision.decided_at is not None
    assert decision.artifact_version_id == version.id
    assert decision.rule_id == "figures_traceable"


def test_model_assessed_verdicts_are_distinguishable(
    chain_session: Session,
    world: dict[str, object],
    dev_keystore: LocalKeyStore,
    dev_blobstore: LocalBlobStore,
) -> None:
    """A model-assessed verdict is never presented with deterministic finality."""
    version = make_version(chain_session, world, dev_keystore, dev_blobstore, TRACEABLE)
    deterministic = run_gate(chain_session, world, version, dev_keystore, dev_blobstore)
    assessed = run_gate(
        chain_session, world, version, dev_keystore, dev_blobstore, key="model-check"
    )
    assert gate_engine.is_deterministic(deterministic) is True
    assert gate_engine.is_deterministic(assessed) is False


def test_an_unregistered_rule_is_refused(
    chain_session: Session,
    world: dict[str, object],
    dev_keystore: LocalKeyStore,
    dev_blobstore: LocalBlobStore,
) -> None:
    version = make_version(chain_session, world, dev_keystore, dev_blobstore, TRACEABLE)
    with pytest.raises(UnknownRuleError):
        run_gate(chain_session, world, version, dev_keystore, dev_blobstore, key="final-review")


# --------------------------------------------------------------------------
# The producer can never approve their own work
# --------------------------------------------------------------------------


def test_the_producer_cannot_decide_the_gate(
    chain_session: Session,
    world: dict[str, object],
    dev_keystore: LocalKeyStore,
    dev_blobstore: LocalBlobStore,
) -> None:
    """D4/I5 — the platform's second commitment."""
    version = make_version(chain_session, world, dev_keystore, dev_blobstore, TRACEABLE)
    with pytest.raises(SelfApprovalError, match="cannot decide"):
        run_gate(chain_session, world, version, dev_keystore, dev_blobstore, decided_by=PRODUCER)


def test_the_database_refuses_self_approval_even_bypassing_the_service(
    chain_session: Session,
    world: dict[str, object],
    dev_keystore: LocalKeyStore,
    dev_blobstore: LocalBlobStore,
) -> None:
    """CLAUDE.md §3: enforce in code, not by prompt instruction."""
    version = make_version(chain_session, world, dev_keystore, dev_blobstore, TRACEABLE)
    task = world["task"]
    assert isinstance(task, Task)
    with (
        pytest.raises(IntegrityError, match="producer_is_not_the_approver"),
        chain_session.begin_nested(),
    ):
        chain_session.execute(
            text(
                "INSERT INTO gate_decision (id, tenant_id, gate_definition_version_id, "
                "artifact_version_id, task_id, verdict, decided_by_identity, producer_identity, "
                "decided_at, rule_id, evaluation_kind) "
                "VALUES (:i, :t, :g, :a, :k, 'pass', :who, :who, "
                "transaction_timestamp(), 'r', 'deterministic')"
            ),
            {
                "i": uuid4(),
                "t": TENANT_A,
                "g": gate(world, "traceability").id,
                "a": version.id,
                "k": task.id,
                "who": PRODUCER,
            },
        )


# --------------------------------------------------------------------------
# Rework
# --------------------------------------------------------------------------


def test_a_failed_gate_opens_rework_and_requeues(
    chain_session: Session,
    world: dict[str, object],
    dev_keystore: LocalKeyStore,
    dev_blobstore: LocalBlobStore,
) -> None:
    version = make_version(chain_session, world, dev_keystore, dev_blobstore, UNTRACEABLE)
    decision = run_gate(chain_session, world, version, dev_keystore, dev_blobstore)
    task = world["task"]
    assert isinstance(task, Task)

    attempt = rework_controller.open_rework(
        chain_session,
        task=task,
        decision=decision,
        keystore=dev_keystore,
        actor_id=ACTOR,
    )
    assert attempt is not None
    assert attempt.attempt_no == 1
    assert attempt.failure_detail
    assert str(task.state.value) == TaskState.QUEUED.value


def test_rework_stops_at_three_and_blocks_for_a_human(
    chain_session: Session,
    world: dict[str, object],
    dev_keystore: LocalKeyStore,
    dev_blobstore: LocalBlobStore,
) -> None:
    """D11: a task failing three times is a signal, not a retry problem."""
    task = world["task"]
    assert isinstance(task, Task)

    for expected in (1, 2, 3):
        version = make_version(chain_session, world, dev_keystore, dev_blobstore, UNTRACEABLE)
        decision = run_gate(chain_session, world, version, dev_keystore, dev_blobstore)
        attempt = rework_controller.open_rework(
            chain_session,
            task=task,
            decision=decision,
            keystore=dev_keystore,
            actor_id=ACTOR,
        )
        assert attempt is not None
        assert attempt.attempt_no == expected
        task.state = TaskState.AWAITING_GATE

    version = make_version(chain_session, world, dev_keystore, dev_blobstore, UNTRACEABLE)
    decision = run_gate(chain_session, world, version, dev_keystore, dev_blobstore)
    assert (
        rework_controller.open_rework(
            chain_session,
            task=task,
            decision=decision,
            keystore=dev_keystore,
            actor_id=ACTOR,
        )
        is None
    )
    assert str(task.state.value) == TaskState.BLOCKED.value


def test_a_fourth_attempt_row_is_refused_by_the_database(
    chain_session: Session, world: dict[str, object]
) -> None:
    task = world["task"]
    assert isinstance(task, Task)
    with pytest.raises(IntegrityError, match="within_rework_limit"), chain_session.begin_nested():
        chain_session.add(
            ReworkAttempt(
                tenant_id=TENANT_A,
                task_id=task.id,
                attempt_no=4,
                triggering_gate_decision_id=uuid4(),
                failure_detail="x",
            )
        )
        chain_session.flush()


def test_rework_cannot_be_opened_for_a_passing_verdict(
    chain_session: Session,
    world: dict[str, object],
    dev_keystore: LocalKeyStore,
    dev_blobstore: LocalBlobStore,
) -> None:
    version = make_version(chain_session, world, dev_keystore, dev_blobstore, TRACEABLE)
    decision = run_gate(chain_session, world, version, dev_keystore, dev_blobstore)
    task = world["task"]
    assert isinstance(task, Task)
    with pytest.raises(NotAFailureError):
        rework_controller.open_rework(
            chain_session,
            task=task,
            decision=decision,
            keystore=dev_keystore,
            actor_id=ACTOR,
        )


# --------------------------------------------------------------------------
# Human approval and the SLA
# --------------------------------------------------------------------------


def request(
    session: Session,
    world: dict[str, object],
    version: ArtifactVersion,
    keystore: LocalKeyStore,
    sla_hours: int = approval_service.DEFAULT_SLA_HOURS,
) -> ApprovalItem:
    task = world["task"]
    assert isinstance(task, Task)
    return approval_service.request_approval(
        session,
        artifact_version=version,
        gate_definition_version=gate(world, "final-review"),
        task_id=task.id,
        requester_identity=REQUESTER,
        keystore=keystore,
        actor_id=ACTOR,
        sla_hours=sla_hours,
    )


def test_approval_starts_pending_with_a_deadline(
    chain_session: Session,
    world: dict[str, object],
    dev_keystore: LocalKeyStore,
    dev_blobstore: LocalBlobStore,
) -> None:
    version = make_version(chain_session, world, dev_keystore, dev_blobstore, TRACEABLE)
    item = request(chain_session, world, version, dev_keystore)
    assert item.state is ApprovalState.PENDING
    assert item.sla_deadline > item.created_at
    assert (item.sla_deadline - item.created_at) >= timedelta(hours=71)


def test_a_reviewer_can_approve(
    chain_session: Session,
    world: dict[str, object],
    dev_keystore: LocalKeyStore,
    dev_blobstore: LocalBlobStore,
) -> None:
    version = make_version(chain_session, world, dev_keystore, dev_blobstore, TRACEABLE)
    item = request(chain_session, world, version, dev_keystore)
    decision = approval_service.decide(
        chain_session,
        item=item,
        approved=True,
        decided_by_identity=REVIEWER,
        keystore=dev_keystore,
        actor_id=ACTOR,
    )
    assert item.state is ApprovalState.APPROVED
    assert item.gate_decision_id == decision.id
    assert decision.verdict is GateVerdict.PASS


@pytest.mark.parametrize("identity", [PRODUCER, REQUESTER])
def test_neither_producer_nor_requester_may_approve(
    chain_session: Session,
    world: dict[str, object],
    dev_keystore: LocalKeyStore,
    dev_blobstore: LocalBlobStore,
    identity: str,
) -> None:
    """D4 bars the producer; PRODUCT.md §18 bars the requester."""
    version = make_version(chain_session, world, dev_keystore, dev_blobstore, TRACEABLE)
    item = request(chain_session, world, version, dev_keystore)
    assert approval_service.is_eligible(item, identity) is False
    with pytest.raises(IneligibleApproverError):
        approval_service.decide(
            chain_session,
            item=item,
            approved=True,
            decided_by_identity=identity,
            keystore=dev_keystore,
            actor_id=ACTOR,
        )


def test_expiry_never_approves(
    chain_session: Session,
    world: dict[str, object],
    dev_keystore: LocalKeyStore,
    dev_blobstore: LocalBlobStore,
) -> None:
    """D7, the sharpest rule in the approval model.

    A hung execution is bad; one that approves itself because nobody looked is
    catastrophic. Expiry produces no verdict at all.
    """
    version = make_version(chain_session, world, dev_keystore, dev_blobstore, TRACEABLE)
    item = request(chain_session, world, version, dev_keystore, sla_hours=0)
    chain_session.flush()

    # transaction_timestamp() is constant within a transaction, so time cannot
    # pass inside one. The explicit `now` exists precisely so the scheduler is
    # testable deterministically rather than by waiting.
    later = item.sla_deadline + timedelta(seconds=1)

    before = chain_session.execute(text("SELECT count(*) FROM gate_decision")).scalar_one()
    assert (
        approval_service.run_expiry_pass(
            chain_session, keystore=dev_keystore, actor_id=ACTOR, now=later
        )
        == 1
    )
    after = chain_session.execute(text("SELECT count(*) FROM gate_decision")).scalar_one()

    assert item.state is ApprovalState.EXPIRED
    assert item.decided_by_identity is None
    assert item.gate_decision_id is None
    assert after == before, "expiry must produce no verdict"


def test_an_expired_item_cannot_then_be_decided(
    chain_session: Session,
    world: dict[str, object],
    dev_keystore: LocalKeyStore,
    dev_blobstore: LocalBlobStore,
) -> None:
    """It requires explicit human action, not a late click on a stale item."""
    version = make_version(chain_session, world, dev_keystore, dev_blobstore, TRACEABLE)
    item = request(chain_session, world, version, dev_keystore, sla_hours=0)
    approval_service.run_expiry_pass(
        chain_session,
        keystore=dev_keystore,
        actor_id=ACTOR,
        now=item.sla_deadline + timedelta(seconds=1),
    )
    with pytest.raises(ApprovalNotPendingError):
        approval_service.decide(
            chain_session,
            item=item,
            approved=True,
            decided_by_identity=REVIEWER,
            keystore=dev_keystore,
            actor_id=ACTOR,
        )


def test_a_pending_item_is_not_expired_early(
    chain_session: Session,
    world: dict[str, object],
    dev_keystore: LocalKeyStore,
    dev_blobstore: LocalBlobStore,
) -> None:
    version = make_version(chain_session, world, dev_keystore, dev_blobstore, TRACEABLE)
    request(chain_session, world, version, dev_keystore)
    chain_session.flush()
    assert (
        approval_service.run_expiry_pass(chain_session, keystore=dev_keystore, actor_id=ACTOR) == 0
    )


def test_escalation_is_explicit_and_recorded(
    chain_session: Session,
    world: dict[str, object],
    dev_keystore: LocalKeyStore,
    dev_blobstore: LocalBlobStore,
) -> None:
    """D7: never an implicit consequence of time passing."""
    version = make_version(chain_session, world, dev_keystore, dev_blobstore, TRACEABLE)
    item = request(chain_session, world, version, dev_keystore, sla_hours=0)
    approval_service.run_expiry_pass(
        chain_session,
        keystore=dev_keystore,
        actor_id=ACTOR,
        now=item.sla_deadline + timedelta(seconds=1),
    )
    assert item.escalated_at is None

    escalated = approval_service.escalate(
        chain_session,
        item=item,
        escalated_to="human:cfo@northwind",
        keystore=dev_keystore,
        actor_id=ACTOR,
    )
    # Read through the returned row: the type checker cannot see that escalate
    # mutated `item`, so asserting on it directly narrows to a stale None.
    assert escalated.escalated_at is not None
    assert escalated.escalated_to == "human:cfo@northwind"


# --------------------------------------------------------------------------
# The record
# --------------------------------------------------------------------------


def test_decisions_and_attempts_are_append_only(
    chain_session: Session,
    world: dict[str, object],
    dev_keystore: LocalKeyStore,
    dev_blobstore: LocalBlobStore,
) -> None:
    """A gate that changed its mind after the fact is not a control."""
    version = make_version(chain_session, world, dev_keystore, dev_blobstore, TRACEABLE)
    run_gate(chain_session, world, version, dev_keystore, dev_blobstore)
    chain_session.flush()
    for statement in (
        "UPDATE gate_decision SET verdict = 'fail'",
        "DELETE FROM gate_decision",
    ):
        with pytest.raises(DBAPIError, match="append-only"), chain_session.begin_nested():
            chain_session.execute(text(statement))


def test_every_gate_decision_writes_an_audit_record(
    chain_session: Session,
    world: dict[str, object],
    dev_keystore: LocalKeyStore,
    dev_blobstore: LocalBlobStore,
) -> None:
    version = make_version(chain_session, world, dev_keystore, dev_blobstore, TRACEABLE)
    before = chain_session.execute(text("SELECT count(*) FROM chain_record")).scalar_one()
    run_gate(chain_session, world, version, dev_keystore, dev_blobstore)
    after = chain_session.execute(text("SELECT count(*) FROM chain_record")).scalar_one()
    assert after - before == 1


def test_gate_tables_are_tenant_isolated(app_engine: Engine, migrated_schema: None) -> None:
    with app_engine.begin() as conn:
        for table in ("gate_decision", "rework_attempt", "approval_item"):
            assert conn.execute(text(f"SELECT count(*) FROM {table}")).scalar_one() == 0


def test_runtime_role_cannot_write_gate_definitions(
    app_engine: Engine, migrated_schema: None
) -> None:
    with pytest.raises(ProgrammingError, match="permission denied"), app_engine.begin() as conn:
        conn.execute(
            text("INSERT INTO gate_definition (id, key, name) VALUES (:i, 'x', 'X')"),
            {"i": uuid4()},
        )
