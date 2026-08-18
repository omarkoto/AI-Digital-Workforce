"""E-1042 with a real agent — `PHASE-2-IMPLEMENTATION-PLAN.md` §3.

The Phase 1 scenario hard-codes the wrong figure and then the right one. This
one hands the Commentary Agent a dataset and a pinned instruction, and the
**agent writes the narrative itself**. Everything downstream is untouched: G4
catches the unsourced figure, rework opens, v2 passes, a human signs, both
chains verify, and the execution reconstructs from the database alone.

The Phase 1 scenario is not modified and does not need to be. Both run.

**No network.** The agent runs on the deterministic fake, scripted to produce an
unsourced figure on the first attempt and a sourced one after rework — which is
the characteristic language-model failure the deterministic gate exists to
catch, reproduced without a language model.

Why the Commentary Agent: it is the one agent in the Finance plan whose work is
pure reasoning over data it is given. No spreadsheet, no chart, no PDF, and so
no tools — which is what makes it the right first agent while the Tool Gateway
is still ahead of us.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from uuid import UUID, uuid4

import pytest
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from adw.adapters.blobstore_local import LocalBlobStore
from adw.adapters.keystore_local import LocalKeyStore
from adw.adapters.llm_fake import FakeLLMProvider
from adw.domain.states import ActionState, GateVerdict, TaskState
from adw.models.artifact import ArtifactDefinitionVersion, ArtifactVersion
from adw.models.cost import ActionCost
from adw.models.definition import AgentDefinitionVersion, SkillVersion
from adw.models.gate import GateDecision, GateDefinitionVersion
from adw.models.task import Task
from adw.runtime import agent_runtime
from adw.runtime.agent_runtime import StopReason
from adw.runtime.context import UntrustedInput
from adw.services import (
    anchor_writer,
    approval_service,
    artifact_service,
    cost_service,
    definition_service,
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
from tests.security.conftest import TENANT_A

pytestmark = pytest.mark.scenario

REQUESTER = "human:amira@northwind"
CONTROLLER = "human:khaled@northwind"
ORCHESTRATOR = "platform:engagement-lead"
COMMENTARY = "agent:commentary"

DATASET: list[dict[str, str]] = [{"cost_centre": "MKT-01", "variance": "1243880"}]

UNSOURCED = "Marketing overspend of 1.2m against budget."
"""A plausible figure with no source — the characteristic failure of a model
asked to write about numbers, and mechanically detectable, which is the whole
argument for deterministic gates."""

SOURCED = "Marketing overspend of 1243880 against budget."

INSTRUCTIONS = (
    "You are the Commentary Agent. Write one sentence explaining the variance "
    "in the data you are given. Every figure you state must appear in the data."
)
SKILL_CONTENT = "State the driver, then the amount, exactly as it appears in the source."


@dataclass(frozen=True, slots=True)
class Outcome:
    """What one agent-driven run of E-1042 produced."""

    v1: ArtifactVersion
    v2: ArtifactVersion
    failed: GateDecision
    passed: GateDecision
    approval: GateDecision
    first_run: agent_runtime.AgentRun
    second_run: agent_runtime.AgentRun


@pytest.fixture
def commentary_provider(dev_keystore: LocalKeyStore) -> FakeLLMProvider:
    """The agent's two answers, keyed on what it is shown.

    Registration order matters: the rework rule is narrower and is registered
    first, so the second attempt — which sees the gate's reason as well as the
    dataset — matches it rather than the broad first-attempt rule.
    """
    return (
        FakeLLMProvider()
        .register(trigger="figures_traceable", response=SOURCED)
        .register(trigger="MKT-01", response=UNSOURCED)
    )


@pytest.fixture
def e1042(
    chain_session: Session, dev_keystore: LocalKeyStore, dev_blobstore: LocalBlobStore
) -> dict[str, object]:
    """Seed the platform catalogue and the execution, then create the task.

    The agent definition and skill are published through the authoring service
    rather than inserted, so the scenario exercises the same path an operator
    would use.
    """
    session = chain_session

    definition_service.create_agent_definition(session, key="commentary", name="Commentary Agent")
    agent_version = definition_service.publish_agent_version(
        session, key="commentary", instructions=INSTRUCTIONS
    )
    definition_service.create_skill(session, key="variance-narrative", name="Variance narrative")
    skill_version = definition_service.publish_skill_version(
        session, key="variance-narrative", content=SKILL_CONTENT
    )

    execution_id, artdef_id, artdef_version_id = uuid4(), uuid4(), uuid4()
    session.execute(
        text(
            "INSERT INTO execution (id, tenant_id, requester_identity, state) "
            "VALUES (:i, :t, :r, 'running')"
        ),
        {"i": execution_id, "t": TENANT_A, "r": REQUESTER},
    )
    session.execute(
        text("INSERT INTO artifact_definition (id, key, name) VALUES (:i, 'comm', 'Commentary')"),
        {"i": artdef_id},
    )
    session.execute(
        text(
            "INSERT INTO artifact_definition_version "
            "(id, artifact_definition_id, version_no, content_type, schema_json) "
            "VALUES (:i, :d, 1, 'application/json', '{}')"
        ),
        {"i": artdef_version_id, "d": artdef_id},
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

    task = task_service.create_task(
        session,
        tenant_id=TENANT_A,
        execution_id=execution_id,
        sequence=4,
        agent_version=agent_version,
        skill_versions=[skill_version],
        keystore=dev_keystore,
        actor_id=ORCHESTRATOR,
    )

    artdef_version = session.get(ArtifactDefinitionVersion, artdef_version_id)
    assert artdef_version is not None

    return {
        "task": task,
        "agent_version": agent_version,
        "skill_version": skill_version,
        "artifact": artifact_service.create_artifact(
            session,
            tenant_id=TENANT_A,
            execution_id=execution_id,
            artifact_definition_id=artdef_id,
            name="variance-commentary",
        ),
        "artdef_version": artdef_version,
        "gates": gates,
        "execution_id": execution_id,
    }


def _agent_writes(
    session: Session,
    world: dict[str, object],
    provider: FakeLLMProvider,
    keystore: LocalKeyStore,
    blobstore: LocalBlobStore,
    inputs: list[UntrustedInput],
) -> tuple[agent_runtime.AgentRun, ArtifactVersion]:
    """Run the agent, then write what it produced as an artifact version.

    The agent produces; it does not judge. Whether the narrative is *good* is the
    gate's decision, and an agent judging its own output would be the
    self-approval D4 forbids.
    """
    task = world["task"]
    assert isinstance(task, Task)
    agent_version = world["agent_version"]
    assert isinstance(agent_version, AgentDefinitionVersion)
    skill_version = world["skill_version"]
    assert isinstance(skill_version, SkillVersion)

    run = agent_runtime.run_task(
        session,
        task=task,
        agent_version=agent_version,
        skill_versions=[skill_version],
        inputs=inputs,
        provider=provider,
        keystore=keystore,
        blobstore=blobstore,
        actor_id=COMMENTARY,
    )
    assert run.stop_reason is StopReason.COMPLETED
    narrative = run.output
    assert narrative is not None, "a run with no answer must not become an artifact"

    version = artifact_service.append_version(
        session,
        artifact=world["artifact"],  # type: ignore[arg-type]
        content=json.dumps({"narrative": narrative, "dataset": DATASET}).encode("utf-8"),
        content_type="application/json",
        producing_task=task,
        producing_agent_identity=COMMENTARY,
        definition_version=world["artdef_version"],  # type: ignore[arg-type]
        keystore=keystore,
        blobstore=blobstore,
        actor_id=COMMENTARY,
    )
    return run, version


def drive(
    session: Session,
    world: dict[str, object],
    provider: FakeLLMProvider,
    keystore: LocalKeyStore,
    blobstore: LocalBlobStore,
) -> Outcome:
    """Run E-1042 to a signed approval, with the agent writing both narratives."""
    task = world["task"]
    assert isinstance(task, Task)
    gates = world["gates"]
    assert isinstance(gates, dict)

    def move(*states: TaskState) -> None:
        for state in states:
            task_service.transition(session, task, state, keystore=keystore, actor_id=ORCHESTRATOR)

    dataset_input = UntrustedInput(label="output of tabular.compute", content=json.dumps(DATASET))

    # --- Attempt 1: the agent writes a plausible figure with no source -----
    move(TaskState.QUEUED, TaskState.RUNNING)
    first_run, v1 = _agent_writes(session, world, provider, keystore, blobstore, [dataset_input])
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

    # --- Attempt 2: the gate's reason goes back as data, and the agent fixes it
    # The reason is a fact about the world, not a new instruction, so it enters
    # the data region exactly like a tool result would.
    move(TaskState.RUNNING)
    second_run, v2 = _agent_writes(
        session,
        world,
        provider,
        keystore,
        blobstore,
        [
            dataset_input,
            UntrustedInput(
                label="gate g4-traceability, previous attempt",
                content=f"{gates['g4-traceability'].rule_id}: {failed.failure_detail}",
            ),
        ],
    )
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
    return Outcome(
        v1=v1,
        v2=v2,
        failed=failed,
        passed=passed,
        approval=approved,
        first_run=first_run,
        second_run=second_run,
    )


# --------------------------------------------------------------------------
# The agent actually wrote it
# --------------------------------------------------------------------------


def test_the_agent_writes_the_narrative_and_the_run_completes(
    chain_session: Session,
    e1042: dict[str, object],
    commentary_provider: FakeLLMProvider,
    dev_keystore: LocalKeyStore,
    dev_blobstore: LocalBlobStore,
) -> None:
    outcome = drive(chain_session, e1042, commentary_provider, dev_keystore, dev_blobstore)

    assert outcome.first_run.output == UNSOURCED
    assert outcome.second_run.output == SOURCED
    assert outcome.approval.verdict is GateVerdict.PASS
    assert outcome.approval.decided_by_identity == CONTROLLER


def test_the_pinned_instructions_governed_both_attempts(
    chain_session: Session,
    e1042: dict[str, object],
    commentary_provider: FakeLLMProvider,
    dev_keystore: LocalKeyStore,
    dev_blobstore: LocalBlobStore,
) -> None:
    """D9/I4: the versions the record names are the ones that ran."""
    drive(chain_session, e1042, commentary_provider, dev_keystore, dev_blobstore)
    for call in commentary_provider.calls:
        assert INSTRUCTIONS in call.messages[0].content
        assert SKILL_CONTENT in call.messages[0].content


def test_the_dataset_reached_the_agent_as_data_not_as_instruction(
    chain_session: Session,
    e1042: dict[str, object],
    commentary_provider: FakeLLMProvider,
    dev_keystore: LocalKeyStore,
    dev_blobstore: LocalBlobStore,
) -> None:
    """D13 on the real path: tool output is data, and so is a gate's reason."""
    drive(chain_session, e1042, commentary_provider, dev_keystore, dev_blobstore)
    first, second = commentary_provider.calls[0], commentary_provider.calls[1]
    assert "MKT-01" in first.messages[1].content
    assert "MKT-01" not in first.messages[0].content
    assert "figures_traceable" in second.messages[1].content
    assert "figures_traceable" not in second.messages[0].content
    assert first.messages[0].content == second.messages[0].content


def test_the_gate_caught_the_model_not_the_fixture(
    chain_session: Session,
    e1042: dict[str, object],
    commentary_provider: FakeLLMProvider,
    dev_keystore: LocalKeyStore,
    dev_blobstore: LocalBlobStore,
) -> None:
    """The figure the gate rejected came out of the agent, not out of a literal
    written into the artifact by the test."""
    outcome = drive(chain_session, e1042, commentary_provider, dev_keystore, dev_blobstore)
    assert outcome.failed.failure_detail is not None
    assert "1.2" in outcome.failed.failure_detail
    content = artifact_service.read_content(
        outcome.v1, keystore=dev_keystore, blobstore=dev_blobstore
    )
    assert json.loads(content)["narrative"] == outcome.first_run.output


def test_every_model_call_is_an_action_with_evidence(
    chain_session: Session,
    e1042: dict[str, object],
    commentary_provider: FakeLLMProvider,
    dev_keystore: LocalKeyStore,
    dev_blobstore: LocalBlobStore,
) -> None:
    """I10 over an agent-driven run: nothing succeeded on an assertion alone."""
    outcome = drive(chain_session, e1042, commentary_provider, dev_keystore, dev_blobstore)
    for run in (outcome.first_run, outcome.second_run):
        assert run.turns[-1].action.state is ActionState.SUCCEEDED

    unproven = chain_session.execute(
        text(
            "SELECT count(*) FROM action a WHERE a.state = 'succeeded' "
            "AND NOT EXISTS (SELECT 1 FROM evidence e WHERE e.action_id = a.id)"
        )
    ).scalar_one()
    assert unproven == 0


def test_the_spend_is_attributable_to_the_execution(
    chain_session: Session,
    e1042: dict[str, object],
    commentary_provider: FakeLLMProvider,
    dev_keystore: LocalKeyStore,
    dev_blobstore: LocalBlobStore,
) -> None:
    """`PRODUCT.md` §25: cost is attributable per execution and per agent."""
    outcome = drive(chain_session, e1042, commentary_provider, dev_keystore, dev_blobstore)
    execution_id = e1042["execution_id"]
    assert isinstance(execution_id, UUID)

    spent = cost_service.spend_for_execution(chain_session, execution_id)
    assert spent == outcome.first_run.total_tokens + outcome.second_run.total_tokens

    rows = (
        chain_session.execute(select(ActionCost).where(ActionCost.execution_id == execution_id))
        .scalars()
        .all()
    )
    assert len(rows) == 2
    assert {row.provider for row in rows} == {"fake"}


def test_no_tool_was_executed(
    chain_session: Session,
    e1042: dict[str, object],
    commentary_provider: FakeLLMProvider,
    dev_keystore: LocalKeyStore,
    dev_blobstore: LocalBlobStore,
) -> None:
    """I2. The only tool name in the record is the model call itself."""
    drive(chain_session, e1042, commentary_provider, dev_keystore, dev_blobstore)
    tools = {
        row[0] for row in chain_session.execute(text("SELECT DISTINCT tool_name FROM action")).all()
    }
    assert tools == {"llm.complete"}


# --------------------------------------------------------------------------
# Everything downstream is untouched
# --------------------------------------------------------------------------


def test_both_narratives_survive(
    chain_session: Session,
    e1042: dict[str, object],
    commentary_provider: FakeLLMProvider,
    dev_keystore: LocalKeyStore,
    dev_blobstore: LocalBlobStore,
) -> None:
    """The wrong figure is not erased by its correction — it is superseded."""
    outcome = drive(chain_session, e1042, commentary_provider, dev_keystore, dev_blobstore)
    first = artifact_service.read_content(
        outcome.v1, keystore=dev_keystore, blobstore=dev_blobstore
    )
    assert b"1.2m" in first
    assert outcome.v2.version_no == outcome.v1.version_no + 1


def test_the_approver_is_neither_the_requester_nor_the_agent(
    chain_session: Session,
    e1042: dict[str, object],
    commentary_provider: FakeLLMProvider,
    dev_keystore: LocalKeyStore,
    dev_blobstore: LocalBlobStore,
) -> None:
    """D4/I5 at the moment that matters most, now that a model produced the work."""
    outcome = drive(chain_session, e1042, commentary_provider, dev_keystore, dev_blobstore)
    assert outcome.approval.decided_by_identity not in (REQUESTER, COMMENTARY)
    assert outcome.approval.producer_identity == COMMENTARY


def test_the_agent_driven_execution_reconstructs_from_persisted_state(
    chain_session: Session,
    e1042: dict[str, object],
    commentary_provider: FakeLLMProvider,
    dev_keystore: LocalKeyStore,
    dev_blobstore: LocalBlobStore,
) -> None:
    """`CLAUDE.md` §1, with a model in the loop: if it cannot be reconstructed
    from the database alone, it did not happen."""
    drive(chain_session, e1042, commentary_provider, dev_keystore, dev_blobstore)

    narrative = reconstruct(chain_session, tenant_id=TENANT_A, keystore=dev_keystore)
    events = event_sequence(narrative)

    assert "task.created" in events
    assert "task.transitioned" in events
    assert "action.transitioned" in events
    assert "artifact.version_created" in events
    assert "gate.decided" in events
    assert "task.rework_opened" in events
    assert "approval.decided" in events

    story = render(narrative)
    assert "llm.complete" in story, "the model calls should be visible in the record"
    assert "1.2" in story, "the rejected figure should be recoverable"
    assert "figures_traceable" in story, "the rule that caught it should be named"
    assert CONTROLLER in story, "the approver should be nameable from the record alone"


def test_both_chains_verify_for_an_agent_driven_execution(
    chain_session: Session,
    e1042: dict[str, object],
    commentary_provider: FakeLLMProvider,
    dev_keystore: LocalKeyStore,
    dev_blobstore: LocalBlobStore,
) -> None:
    drive(chain_session, e1042, commentary_provider, dev_keystore, dev_blobstore)
    chain_session.flush()

    length = verify_tenant_chain(chain_session, TENANT_A)
    assert length > 10
    anchor_writer.run_anchoring_pass(chain_session)
    assert verify_anchor_chain_integrity(chain_session) == 1
    assert verify_tenant_against_anchors(chain_session, TENANT_A) == 1


def test_the_record_survives_erasure(
    chain_session: Session,
    e1042: dict[str, object],
    commentary_provider: FakeLLMProvider,
    dev_keystore: LocalKeyStore,
    dev_blobstore: LocalBlobStore,
) -> None:
    """D1/I12: prompts and completions are payloads like any other, so key
    destruction removes them and leaves the fact that they happened."""
    drive(chain_session, e1042, commentary_provider, dev_keystore, dev_blobstore)
    before = len(reconstruct(chain_session, tenant_id=TENANT_A, keystore=dev_keystore))

    dev_keystore.destroy(TENANT_A)
    after = reconstruct(chain_session, tenant_id=TENANT_A, keystore=dev_keystore)

    assert len(after) == before
    assert all("unreadable" in entry.detail for entry in after)
    assert verify_tenant_chain(chain_session, TENANT_A) == before
