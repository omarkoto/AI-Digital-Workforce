"""Cost accounting and hard stops — `PRODUCT.md` §25.

The claim under test is narrow and important: a breach **pauses**, it never
truncates. A run that stopped because it ran out of budget must be
distinguishable, from the database alone, from a run that finished.
"""

from __future__ import annotations

from uuid import UUID, uuid4

import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session

from adw.adapters.blobstore_local import LocalBlobStore
from adw.adapters.keystore_local import LocalKeyStore
from adw.adapters.llm_fake import FakeLLMProvider
from adw.models.audit import AuditChainRecord
from adw.models.cost import ActionCost
from adw.models.definition import AgentDefinitionVersion, SkillVersion
from adw.models.task import Task
from adw.runtime import agent_runtime
from adw.runtime.agent_runtime import StopReason
from adw.runtime.context import UntrustedInput
from adw.services import cost_service, definition_service, task_service
from adw.services.cost_service import BudgetError, BudgetStatus
from tests.security.conftest import TENANT_A

pytestmark = pytest.mark.security

ACTOR = "agent:commentary"
CURATOR = "platform:curator"
ANSWER = "Revenue rose 12% against a 9% plan, driven by the enterprise renewal cohort."
INPUTS = (UntrustedInput(label="the requester's requirement", content="explain the Q3 variance"),)


@pytest.fixture
def execution_id(chain_session: Session) -> UUID:
    identifier = uuid4()
    chain_session.execute(
        text(
            "INSERT INTO execution (id, tenant_id, requester_identity, state) "
            "VALUES (:i, :t, 'amira@northwind', 'running')"
        ),
        {"i": identifier, "t": TENANT_A},
    )
    return identifier


@pytest.fixture
def agent_version(chain_session: Session) -> AgentDefinitionVersion:
    definition_service.create_agent_definition(chain_session, key="commentary", name="Commentary")
    return definition_service.publish_agent_version(
        chain_session, key="commentary", instructions="Explain the variance."
    )


@pytest.fixture
def task(
    chain_session: Session,
    execution_id: UUID,
    agent_version: AgentDefinitionVersion,
    dev_keystore: LocalKeyStore,
) -> Task:
    return task_service.create_task(
        chain_session,
        tenant_id=TENANT_A,
        execution_id=execution_id,
        sequence=1,
        agent_version=agent_version,
        keystore=dev_keystore,
        actor_id="platform:orchestrator",
    )


@pytest.fixture
def provider(dev_keystore: LocalKeyStore) -> FakeLLMProvider:
    return FakeLLMProvider(fallback=ANSWER)


def run(
    session: Session,
    task: Task,
    agent_version: AgentDefinitionVersion,
    provider: FakeLLMProvider,
    keystore: LocalKeyStore,
    blobstore: LocalBlobStore,
    skill_versions: list[SkillVersion] | None = None,
    **overrides: object,
) -> agent_runtime.AgentRun:
    return agent_runtime.run_task(
        session,
        task=task,
        agent_version=agent_version,
        skill_versions=skill_versions or [],
        inputs=INPUTS,
        provider=provider,
        keystore=keystore,
        blobstore=blobstore,
        actor_id=ACTOR,
        **overrides,  # type: ignore[arg-type]
    )


# --- Recording --------------------------------------------------------------


def test_usage_is_recorded_per_action_in_a_summable_form(
    chain_session: Session,
    task: Task,
    execution_id: UUID,
    agent_version: AgentDefinitionVersion,
    provider: FakeLLMProvider,
    dev_keystore: LocalKeyStore,
    dev_blobstore: LocalBlobStore,
) -> None:
    """The same numbers are inside the encrypted evidence; these are the ones a
    budget can actually add up."""
    result = run(chain_session, task, agent_version, provider, dev_keystore, dev_blobstore)

    cost = chain_session.execute(
        select(ActionCost).where(ActionCost.action_id == result.turns[0].action.id)
    ).scalar_one()
    assert cost.prompt_tokens + cost.completion_tokens == result.total_tokens
    assert cost.execution_id == execution_id
    assert cost.provider == "fake"


def test_the_cost_row_carries_attribution_but_no_content(
    chain_session: Session,
    task: Task,
    agent_version: AgentDefinitionVersion,
    provider: FakeLLMProvider,
    dev_keystore: LocalKeyStore,
    dev_blobstore: LocalBlobStore,
) -> None:
    """`PRODUCT.md` §25: a cost that cannot be attributed cannot be controlled.
    Attribution is the provider and model — never a prompt and never a key."""
    result = run(chain_session, task, agent_version, provider, dev_keystore, dev_blobstore)
    cost = chain_session.execute(
        select(ActionCost).where(ActionCost.action_id == result.turns[0].action.id)
    ).scalar_one()
    columns = set(ActionCost.__table__.columns.keys())
    assert {"provider", "model"} <= columns
    assert not columns & {"prompt", "content", "api_key", "messages"}
    assert cost.model


def test_recorded_cost_cannot_be_edited(
    chain_session: Session,
    task: Task,
    agent_version: AgentDefinitionVersion,
    provider: FakeLLMProvider,
    dev_keystore: LocalKeyStore,
    dev_blobstore: LocalBlobStore,
) -> None:
    """A spend figure that can be edited after the fact is not an accounting record."""
    result = run(chain_session, task, agent_version, provider, dev_keystore, dev_blobstore)
    cost = chain_session.execute(
        select(ActionCost).where(ActionCost.action_id == result.turns[0].action.id)
    ).scalar_one()
    with pytest.raises(DBAPIError, match="immutable"):
        chain_session.execute(
            text("UPDATE action_cost SET prompt_tokens = 0 WHERE id = :i"), {"i": cost.id}
        )
    chain_session.rollback()


def test_spend_accumulates_across_turns(
    chain_session: Session,
    task: Task,
    execution_id: UUID,
    agent_version: AgentDefinitionVersion,
    dev_keystore: LocalKeyStore,
    dev_blobstore: LocalBlobStore,
) -> None:
    proposing = FakeLLMProvider(fallback="TOOL_CALL: spreadsheet.read")
    result = run(
        chain_session,
        task,
        agent_version,
        proposing,
        dev_keystore,
        dev_blobstore,
        max_turns=3,
    )
    assert result.stop_reason is StopReason.TURN_LIMIT
    assert cost_service.spend_for_execution(chain_session, execution_id) == result.total_tokens


# --- Reading a budget -------------------------------------------------------


def test_an_execution_without_a_budget_reads_as_unlimited(
    chain_session: Session, execution_id: UUID
) -> None:
    """Explicit rather than implied: unbudgeted is a choice, not "comfortably OK"."""
    reading = cost_service.read_budget(chain_session, execution_id)
    assert reading.status is BudgetStatus.UNLIMITED
    assert reading.limit_tokens is None
    assert reading.remaining_tokens is None
    assert reading.may_continue


def test_a_fresh_budget_reads_as_ok(
    chain_session: Session, execution_id: UUID, dev_keystore: LocalKeyStore
) -> None:
    cost_service.set_budget(
        chain_session,
        tenant_id=TENANT_A,
        execution_id=execution_id,
        max_total_tokens=1000,
        keystore=dev_keystore,
        actor_id=CURATOR,
    )
    reading = cost_service.read_budget(chain_session, execution_id)
    assert reading.status is BudgetStatus.OK
    assert reading.remaining_tokens == 1000


def test_a_budget_must_be_positive(
    chain_session: Session, execution_id: UUID, dev_keystore: LocalKeyStore
) -> None:
    with pytest.raises(BudgetError, match="must be positive"):
        cost_service.set_budget(
            chain_session,
            tenant_id=TENANT_A,
            execution_id=execution_id,
            max_total_tokens=0,
            keystore=dev_keystore,
            actor_id=CURATOR,
        )


def test_a_second_budget_is_refused_in_favour_of_an_authorization(
    chain_session: Session, execution_id: UUID, dev_keystore: LocalKeyStore
) -> None:
    """Raising a ceiling must name who did it; replacing one would not."""
    cost_service.set_budget(
        chain_session,
        tenant_id=TENANT_A,
        execution_id=execution_id,
        max_total_tokens=100,
        keystore=dev_keystore,
        actor_id=CURATOR,
    )
    with pytest.raises(BudgetError, match="authorize_additional"):
        cost_service.set_budget(
            chain_session,
            tenant_id=TENANT_A,
            execution_id=execution_id,
            max_total_tokens=200,
            keystore=dev_keystore,
            actor_id=CURATOR,
        )


# --- The hard stop ----------------------------------------------------------


def test_an_exhausted_budget_stops_the_run_before_any_call(
    chain_session: Session,
    task: Task,
    execution_id: UUID,
    agent_version: AgentDefinitionVersion,
    provider: FakeLLMProvider,
    dev_keystore: LocalKeyStore,
    dev_blobstore: LocalBlobStore,
) -> None:
    """The stop happens before the request, so nothing is half-produced."""
    cost_service.set_budget(
        chain_session,
        tenant_id=TENANT_A,
        execution_id=execution_id,
        max_total_tokens=1,
        keystore=dev_keystore,
        actor_id=CURATOR,
    )
    # Spend the whole budget on one turn.
    first = run(chain_session, task, agent_version, provider, dev_keystore, dev_blobstore)
    assert first.stop_reason is StopReason.COMPLETED

    second_task = task_service.create_task(
        chain_session,
        tenant_id=TENANT_A,
        execution_id=execution_id,
        sequence=2,
        agent_version=agent_version,
        keystore=dev_keystore,
        actor_id="platform:orchestrator",
    )
    calls_before = len(provider.calls)
    result = run(chain_session, second_task, agent_version, provider, dev_keystore, dev_blobstore)

    assert result.stop_reason is StopReason.BUDGET_EXHAUSTED
    assert not result.succeeded
    assert result.output is None
    assert result.turns == ()
    assert len(provider.calls) == calls_before, "no request may be made once the budget is gone"


def test_exhaustion_is_an_audit_event(
    chain_session: Session,
    task: Task,
    execution_id: UUID,
    agent_version: AgentDefinitionVersion,
    provider: FakeLLMProvider,
    dev_keystore: LocalKeyStore,
    dev_blobstore: LocalBlobStore,
) -> None:
    """A limit that fired and left no record is indistinguishable from one that
    was never configured."""
    cost_service.set_budget(
        chain_session,
        tenant_id=TENANT_A,
        execution_id=execution_id,
        max_total_tokens=1,
        keystore=dev_keystore,
        actor_id=CURATOR,
    )
    run(chain_session, task, agent_version, provider, dev_keystore, dev_blobstore)
    second_task = task_service.create_task(
        chain_session,
        tenant_id=TENANT_A,
        execution_id=execution_id,
        sequence=2,
        agent_version=agent_version,
        keystore=dev_keystore,
        actor_id="platform:orchestrator",
    )
    run(chain_session, second_task, agent_version, provider, dev_keystore, dev_blobstore)

    events = [
        record.event_type
        for record in chain_session.execute(select(AuditChainRecord)).scalars().all()
    ]
    assert cost_service.EVENT_BUDGET_SET in events
    assert cost_service.EVENT_BUDGET_EXHAUSTED in events


def test_the_warning_threshold_fires_before_exhaustion(
    chain_session: Session, task: Task, execution_id: UUID, dev_keystore: LocalKeyStore
) -> None:
    """`PRODUCT.md` §25: warn at 80%, pause at 100%. Work continues at a warning."""
    cost_service.set_budget(
        chain_session,
        tenant_id=TENANT_A,
        execution_id=execution_id,
        max_total_tokens=100,
        keystore=dev_keystore,
        actor_id=CURATOR,
    )
    chain_session.add(
        ActionCost(
            tenant_id=TENANT_A,
            action_id=_orphan_action(chain_session, execution_id),
            execution_id=execution_id,
            provider="fake",
            model="fake-deterministic-v1",
            prompt_tokens=80,
            completion_tokens=0,
        )
    )
    chain_session.flush()

    reading = cost_service.check_before_spending(
        chain_session,
        tenant_id=TENANT_A,
        execution_id=execution_id,
        keystore=dev_keystore,
        actor_id=ACTOR,
    )
    assert reading.status is BudgetStatus.WARNING
    assert reading.may_continue
    events = [
        record.event_type
        for record in chain_session.execute(select(AuditChainRecord)).scalars().all()
    ]
    assert cost_service.EVENT_BUDGET_WARNING in events


def _orphan_action(session: Session, execution_id: UUID) -> UUID:
    """An action row to hang a cost on, without running an agent."""
    from adw.models.action import Action
    from adw.models.task import Task as TaskModel

    task_id = session.execute(
        select(TaskModel.id).where(TaskModel.execution_id == execution_id).limit(1)
    ).scalar_one_or_none()
    if task_id is None:
        raise AssertionError("the fixture should have created a task")
    action = Action(tenant_id=TENANT_A, task_id=task_id, sequence=99, tool_name="llm.complete")
    session.add(action)
    session.flush()
    return action.id


# --- Human authorization ----------------------------------------------------


def test_authorization_raises_the_ceiling_and_names_who_did_it(
    chain_session: Session, execution_id: UUID, dev_keystore: LocalKeyStore
) -> None:
    """The budget row is mutable and action_cost is not: the ceiling is a
    decision someone makes, the spend is a fact that happened."""
    cost_service.set_budget(
        chain_session,
        tenant_id=TENANT_A,
        execution_id=execution_id,
        max_total_tokens=100,
        keystore=dev_keystore,
        actor_id=CURATOR,
    )
    budget = cost_service.authorize_additional(
        chain_session,
        tenant_id=TENANT_A,
        execution_id=execution_id,
        additional_tokens=400,
        authorized_by_identity="lena@northwind",
        keystore=dev_keystore,
        actor_id=CURATOR,
    )
    assert budget.max_total_tokens == 500
    assert budget.authorized_by_identity == "lena@northwind"

    events = [
        record.event_type
        for record in chain_session.execute(select(AuditChainRecord)).scalars().all()
    ]
    assert cost_service.EVENT_BUDGET_AUTHORIZED in events


def test_a_reduction_is_not_an_authorization(
    chain_session: Session, execution_id: UUID, dev_keystore: LocalKeyStore
) -> None:
    cost_service.set_budget(
        chain_session,
        tenant_id=TENANT_A,
        execution_id=execution_id,
        max_total_tokens=100,
        keystore=dev_keystore,
        actor_id=CURATOR,
    )
    with pytest.raises(BudgetError, match="must add tokens"):
        cost_service.authorize_additional(
            chain_session,
            tenant_id=TENANT_A,
            execution_id=execution_id,
            additional_tokens=-50,
            authorized_by_identity="lena@northwind",
            keystore=dev_keystore,
            actor_id=CURATOR,
        )


def test_authorizing_an_execution_with_no_budget_is_refused(
    chain_session: Session, execution_id: UUID, dev_keystore: LocalKeyStore
) -> None:
    with pytest.raises(BudgetError, match="no budget"):
        cost_service.authorize_additional(
            chain_session,
            tenant_id=TENANT_A,
            execution_id=execution_id,
            additional_tokens=100,
            authorized_by_identity="lena@northwind",
            keystore=dev_keystore,
            actor_id=CURATOR,
        )


def test_work_resumes_after_authorization(
    chain_session: Session,
    task: Task,
    execution_id: UUID,
    agent_version: AgentDefinitionVersion,
    provider: FakeLLMProvider,
    dev_keystore: LocalKeyStore,
    dev_blobstore: LocalBlobStore,
) -> None:
    """Continuing is an explicit act that raises the ceiling, not a retry that
    quietly succeeds because a counter reset."""
    cost_service.set_budget(
        chain_session,
        tenant_id=TENANT_A,
        execution_id=execution_id,
        max_total_tokens=1,
        keystore=dev_keystore,
        actor_id=CURATOR,
    )
    run(chain_session, task, agent_version, provider, dev_keystore, dev_blobstore)

    blocked_task = task_service.create_task(
        chain_session,
        tenant_id=TENANT_A,
        execution_id=execution_id,
        sequence=2,
        agent_version=agent_version,
        keystore=dev_keystore,
        actor_id="platform:orchestrator",
    )
    blocked = run(chain_session, blocked_task, agent_version, provider, dev_keystore, dev_blobstore)
    assert blocked.stop_reason is StopReason.BUDGET_EXHAUSTED

    cost_service.authorize_additional(
        chain_session,
        tenant_id=TENANT_A,
        execution_id=execution_id,
        additional_tokens=100_000,
        authorized_by_identity="lena@northwind",
        keystore=dev_keystore,
        actor_id=CURATOR,
    )
    resumed_task = task_service.create_task(
        chain_session,
        tenant_id=TENANT_A,
        execution_id=execution_id,
        sequence=3,
        agent_version=agent_version,
        keystore=dev_keystore,
        actor_id="platform:orchestrator",
    )
    resumed = run(chain_session, resumed_task, agent_version, provider, dev_keystore, dev_blobstore)
    assert resumed.stop_reason is StopReason.COMPLETED
    assert resumed.output == ANSWER
