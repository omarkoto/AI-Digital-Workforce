"""A state transition and its audit record share one transaction — G2.

Either both are durable or neither happened. This is the property that stops the
record and the state from drifting apart, and it is only provable against a real
database with a real rollback.
"""

from __future__ import annotations

from uuid import uuid4

import pytest
from sqlalchemy import Engine, text
from sqlalchemy.orm import Session

from adw.adapters.keystore_local import LocalKeyStore
from adw.domain.errors import IllegalTransitionError
from adw.domain.states import TaskState
from adw.models.task import Task
from adw.services import task_service
from adw.verification.chain_verifier import verify_tenant_chain
from tests.security.conftest import TENANT_A

pytestmark = pytest.mark.security

ACTOR = "agent:data-preparation"


@pytest.fixture
def task(chain_session: Session) -> Task:
    """A planned task, with the definitions it pins."""
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
        state=TaskState.PLANNED,
        attempt_no=1,
    )
    chain_session.add(row)
    chain_session.flush()
    return row


def state_of(task: Task) -> str:
    """Read the task's state opaquely.

    The type checker cannot see that a service call mutated the task, so a direct
    comparison narrows to a stale literal and is then reported as unreachable.
    """
    return str(task.state.value)


def chain_length(session: Session) -> int:
    return int(session.execute(text("SELECT count(*) FROM chain_record")).scalar_one())


def test_a_transition_writes_exactly_one_audit_record(
    chain_session: Session, dev_keystore: LocalKeyStore, task: Task
) -> None:
    before = chain_length(chain_session)
    task_service.transition(
        chain_session, task, TaskState.QUEUED, keystore=dev_keystore, actor_id=ACTOR
    )
    assert chain_length(chain_session) == before + 1
    assert task.state is TaskState.QUEUED


def test_a_refused_transition_writes_nothing(
    chain_session: Session, dev_keystore: LocalKeyStore, task: Task
) -> None:
    """The record describes what happened, and a rejected move did not happen."""
    before = chain_length(chain_session)
    with pytest.raises(IllegalTransitionError):
        task_service.transition(
            chain_session, task, TaskState.PASSED, keystore=dev_keystore, actor_id=ACTOR
        )
    assert chain_length(chain_session) == before
    assert task.state is TaskState.PLANNED


def test_the_chain_verifies_after_a_sequence_of_transitions(
    chain_session: Session, dev_keystore: LocalKeyStore, task: Task
) -> None:
    for target in (TaskState.QUEUED, TaskState.RUNNING, TaskState.PRODUCING):
        task_service.transition(chain_session, task, target, keystore=dev_keystore, actor_id=ACTOR)
    assert verify_tenant_chain(chain_session, TENANT_A) == 3


def test_rework_limit_refuses_a_fourth_attempt(
    chain_session: Session, dev_keystore: LocalKeyStore, task: Task
) -> None:
    """Both REWORKING edges are legal shapes; the machine does not choose.

    The rework budget is **not** enforced here. D11 is owned solely by the rework
    controller, whose append-only attempt rows are the single authority — see
    ``test_gate_rework_approval.py``. Guarding it in two places produced two
    counters for one budget that disagreed at the boundary.

    What this asserts is the machine's own shape: REWORKING may reach either
    QUEUED or BLOCKED, and both are permitted transitions.
    """

    def move(*targets: TaskState) -> None:
        for target in targets:
            task_service.transition(
                chain_session, task, target, keystore=dev_keystore, actor_id=ACTOR
            )

    move(TaskState.QUEUED, TaskState.RUNNING, TaskState.PRODUCING, TaskState.AWAITING_GATE)
    move(TaskState.REWORKING)
    # Compared by value rather than identity: `move` mutates the task, which the
    # type checker cannot see, so an `is` check here narrows to a stale literal.
    assert state_of(task) == TaskState.REWORKING.value

    move(TaskState.QUEUED)
    assert state_of(task) == TaskState.QUEUED.value

    move(TaskState.RUNNING, TaskState.PRODUCING, TaskState.AWAITING_GATE, TaskState.REWORKING)
    move(TaskState.BLOCKED)
    assert state_of(task) == TaskState.BLOCKED.value


def test_rollback_discards_both_the_transition_and_its_record(
    owner_engine: Engine, migrated_schema: None, dev_keystore: LocalKeyStore
) -> None:
    """The heart of G2: a rolled-back transaction leaves neither behind."""
    with Session(owner_engine) as session:
        session.execute(text("SELECT set_config('app.tenant_id', :t, true)"), {"t": str(TENANT_A)})
        session.execute(
            text("INSERT INTO tenant (id, slug, name) VALUES (:i, 'northwind', 'Northwind')"),
            {"i": TENANT_A},
        )
        session.commit()

    with Session(owner_engine) as session:
        session.execute(text("SELECT set_config('app.tenant_id', :t, true)"), {"t": str(TENANT_A)})
        agent_id, version_id, execution_id = uuid4(), uuid4(), uuid4()
        session.execute(
            text("INSERT INTO agent_definition (id, key, name) VALUES (:i, 'p', 'P')"),
            {"i": agent_id},
        )
        session.execute(
            text(
                "INSERT INTO agent_definition_version "
                "(id, agent_definition_id, version_no, instructions) VALUES (:i, :d, 1, 'g')"
            ),
            {"i": version_id, "d": agent_id},
        )
        session.execute(
            text(
                "INSERT INTO execution (id, tenant_id, requester_identity, state) "
                "VALUES (:i, :t, 'a', 'running')"
            ),
            {"i": execution_id, "t": TENANT_A},
        )
        row = Task(
            tenant_id=TENANT_A,
            execution_id=execution_id,
            sequence=1,
            agent_definition_version_id=version_id,
            state=TaskState.PLANNED,
            attempt_no=1,
        )
        session.add(row)
        session.flush()
        task_service.transition(
            session, row, TaskState.QUEUED, keystore=dev_keystore, actor_id=ACTOR
        )
        assert chain_length(session) == 1
        session.rollback()

    with Session(owner_engine) as session:
        session.execute(text("SELECT set_config('app.tenant_id', :t, true)"), {"t": str(TENANT_A)})
        assert chain_length(session) == 0
        assert session.execute(text("SELECT count(*) FROM task")).scalar_one() == 0
