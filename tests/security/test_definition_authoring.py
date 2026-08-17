"""Definition authoring, resolution, and pinning — D5, D9, D10, D30, I4.

Open decision F is settled in favour of database-backed definitions, so the
question these tests answer is whether "database-backed" still means what D9
requires: a version an execution pinned can never change, and only the platform
can publish one.

The privilege split is the load-bearing part. It is asserted against the real
``adw_app`` role, not against a service that could be called differently
tomorrow.
"""

from __future__ import annotations

from uuid import UUID, uuid4

import pytest
from sqlalchemy import Engine, select, text
from sqlalchemy.exc import DBAPIError, ProgrammingError
from sqlalchemy.orm import Session

from adw.adapters.keystore_local import LocalKeyStore
from adw.domain.states import TaskState
from adw.models.definition import AgentDefinitionVersion, SkillVersion
from adw.models.task import Task, TaskSkillPin
from adw.services import definition_service, task_service
from adw.services.definition_service import (
    DefinitionNotFoundError,
    DuplicateDefinitionError,
    NoPublishableVersionError,
)
from tests.security.conftest import TENANT_A

pytestmark = pytest.mark.security

ACTOR = "platform:curator"
AGENT_KEY = "commentary"
SKILL_KEY = "variance-narrative"


@pytest.fixture
def authored(chain_session: Session) -> Session:
    """An owner session with one agent definition and one skill, each at v1."""
    definition_service.create_agent_definition(
        chain_session, key=AGENT_KEY, name="Commentary Agent"
    )
    definition_service.publish_agent_version(
        chain_session, key=AGENT_KEY, instructions="Explain the variance. Cite every figure."
    )
    definition_service.create_skill(chain_session, key=SKILL_KEY, name="Variance narrative")
    definition_service.publish_skill_version(
        chain_session, key=SKILL_KEY, content="State the driver, then the amount, then the source."
    )
    return chain_session


# --- Authoring --------------------------------------------------------------


def test_publishing_starts_at_version_one(authored: Session) -> None:
    version = definition_service.resolve_agent_version(authored, key=AGENT_KEY)
    assert version.version_no == 1


def test_each_publish_appends_a_new_version(authored: Session) -> None:
    """A correction is a new version, never an edit."""
    second = definition_service.publish_agent_version(
        authored, key=AGENT_KEY, instructions="Explain the variance. Cite every figure and period."
    )
    assert second.version_no == 2

    first = definition_service.resolve_agent_version(authored, key=AGENT_KEY, version_no=1)
    assert first.instructions == "Explain the variance. Cite every figure."
    assert first.id != second.id


def test_skill_versions_append_independently(authored: Session) -> None:
    second = definition_service.publish_skill_version(
        authored, key=SKILL_KEY, content="Name the source system too."
    )
    assert second.version_no == 2
    assert definition_service.resolve_skill_version(authored, key=SKILL_KEY).version_no == 2


def test_a_duplicate_key_is_refused(authored: Session) -> None:
    with pytest.raises(DuplicateDefinitionError):
        definition_service.create_agent_definition(authored, key=AGENT_KEY, name="Another")
    with pytest.raises(DuplicateDefinitionError):
        definition_service.create_skill(authored, key=SKILL_KEY, name="Another")


def test_publishing_against_an_unknown_key_is_refused(authored: Session) -> None:
    with pytest.raises(DefinitionNotFoundError):
        definition_service.publish_agent_version(authored, key="nobody", instructions="x")
    with pytest.raises(DefinitionNotFoundError):
        definition_service.publish_skill_version(authored, key="nobody", content="x")


# --- Immutability -----------------------------------------------------------


def test_a_published_version_cannot_be_edited(authored: Session) -> None:
    """D9, enforced by trigger. Every role, including the owner."""
    version = definition_service.resolve_agent_version(authored, key=AGENT_KEY)
    with pytest.raises(DBAPIError, match="immutable"):
        authored.execute(
            text("UPDATE agent_definition_version SET instructions = 'rewritten' WHERE id = :i"),
            {"i": version.id},
        )
    authored.rollback()


def test_a_published_version_cannot_be_deleted(chain_session: Session) -> None:
    definition_service.create_agent_definition(chain_session, key="throwaway", name="Throwaway")
    version = definition_service.publish_agent_version(
        chain_session, key="throwaway", instructions="temporary"
    )
    with pytest.raises(DBAPIError, match="immutable"):
        chain_session.execute(
            text("DELETE FROM agent_definition_version WHERE id = :i"), {"i": version.id}
        )
    chain_session.rollback()


# --- Privilege: D5, platform-curated ---------------------------------------


def test_the_runtime_role_cannot_author_a_definition(
    app_engine: Engine, migrated_schema: None
) -> None:
    """D5 made structural: a tenant runtime cannot publish instructions,
    however the call is made and whatever an agent is persuaded to attempt."""
    with Session(app_engine) as session:
        session.execute(text("SELECT set_config('app.tenant_id', :t, true)"), {"t": str(TENANT_A)})
        with pytest.raises(ProgrammingError, match="permission denied"):
            session.execute(
                text("INSERT INTO agent_definition (id, key, name) VALUES (:i, 'x', 'X')"),
                {"i": uuid4()},
            )
        session.rollback()


def test_the_runtime_role_cannot_publish_a_version(
    app_engine: Engine, migrated_schema: None
) -> None:
    with Session(app_engine) as session:
        session.execute(text("SELECT set_config('app.tenant_id', :t, true)"), {"t": str(TENANT_A)})
        with pytest.raises(ProgrammingError, match="permission denied"):
            session.execute(
                text(
                    "INSERT INTO agent_definition_version "
                    "(id, agent_definition_id, version_no, instructions) "
                    "VALUES (:i, :d, 1, 'mine now')"
                ),
                {"i": uuid4(), "d": uuid4()},
            )
        session.rollback()


@pytest.mark.parametrize(
    "table", ["agent_definition", "agent_definition_version", "skill", "skill_version"]
)
def test_the_runtime_role_may_read_but_not_write_any_definition_table(
    app_engine: Engine, migrated_schema: None, table: str
) -> None:
    """Resolution is a read, and every tenant shares the platform catalogue (D30).

    Asserted as a privilege rather than by attempting each verb, so a table added
    to the catalogue later cannot quietly arrive writable.
    """
    with Session(app_engine) as session:
        granted = session.execute(
            text(
                "SELECT has_table_privilege('adw_app', :t, 'SELECT'), "
                "has_table_privilege('adw_app', :t, 'INSERT'), "
                "has_table_privilege('adw_app', :t, 'UPDATE'), "
                "has_table_privilege('adw_app', :t, 'DELETE')"
            ),
            {"t": table},
        ).one()
    assert granted == (True, False, False, False)


# --- Resolution -------------------------------------------------------------


def test_resolution_returns_the_highest_version(authored: Session) -> None:
    definition_service.publish_agent_version(authored, key=AGENT_KEY, instructions="v2")
    definition_service.publish_agent_version(authored, key=AGENT_KEY, instructions="v3")
    assert definition_service.resolve_agent_version(authored, key=AGENT_KEY).version_no == 3


def test_resolution_skips_a_deprecated_version(authored: Session) -> None:
    """Deprecation retires a version from *new* pins without stranding old ones."""
    definition_service.publish_agent_version(authored, key=AGENT_KEY, instructions="v2")
    # Set at insert time: the immutability trigger blocks UPDATE on this table
    # for every role, so deprecation cannot currently be applied after the fact.
    # See the finding reported with this task.
    authored.add(
        AgentDefinitionVersion(
            agent_definition_id=definition_service.resolve_agent_version(
                authored, key=AGENT_KEY
            ).agent_definition_id,
            version_no=3,
            instructions="retired",
            is_deprecated=True,
        )
    )
    authored.flush()
    assert definition_service.resolve_agent_version(authored, key=AGENT_KEY).version_no == 2


def test_an_exact_version_resolves_even_when_deprecated(authored: Session) -> None:
    """Reproducing a past execution must survive the retirement of its rules."""
    skill = definition_service.resolve_skill_version(authored, key=SKILL_KEY)
    authored.add(
        SkillVersion(skill_id=skill.skill_id, version_no=2, content="retired", is_deprecated=True)
    )
    authored.flush()
    exact = definition_service.resolve_skill_version(authored, key=SKILL_KEY, version_no=2)
    assert exact.content == "retired"
    assert definition_service.resolve_skill_version(authored, key=SKILL_KEY).version_no == 1


def test_an_unpublished_definition_reports_no_publishable_version(chain_session: Session) -> None:
    """Distinct from "not found": a missing definition and a retired one are
    different problems for whoever has to fix them."""
    definition_service.create_agent_definition(chain_session, key="empty", name="Empty")
    with pytest.raises(NoPublishableVersionError):
        definition_service.resolve_agent_version(chain_session, key="empty")


def test_an_unknown_key_is_not_found(chain_session: Session) -> None:
    with pytest.raises(DefinitionNotFoundError):
        definition_service.resolve_agent_version(chain_session, key="nobody")
    with pytest.raises(DefinitionNotFoundError):
        definition_service.resolve_skill_version(chain_session, key="nobody")


def test_an_unknown_version_number_is_not_found(authored: Session) -> None:
    with pytest.raises(DefinitionNotFoundError):
        definition_service.resolve_agent_version(authored, key=AGENT_KEY, version_no=99)


def test_resolving_several_skills_is_all_or_nothing(authored: Session) -> None:
    """A task never starts with a partial instruction set it does not know is partial."""
    with pytest.raises(DefinitionNotFoundError):
        definition_service.resolve_skill_versions(authored, keys=(SKILL_KEY, "nobody"))


# --- Pinning ----------------------------------------------------------------


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


def test_a_task_pins_the_versions_that_governed_it(
    authored: Session, execution_id: UUID, dev_keystore: LocalKeyStore
) -> None:
    agent = definition_service.resolve_agent_version(authored, key=AGENT_KEY)
    skills = definition_service.resolve_skill_versions(authored, keys=(SKILL_KEY,))

    task = task_service.create_task(
        authored,
        tenant_id=TENANT_A,
        execution_id=execution_id,
        sequence=1,
        agent_version=agent,
        skill_versions=skills,
        keystore=dev_keystore,
        actor_id=ACTOR,
    )

    assert task.state is TaskState.PLANNED
    assert task.agent_definition_version_id == agent.id
    pins = (
        authored.execute(select(TaskSkillPin).where(TaskSkillPin.task_id == task.id))
        .scalars()
        .all()
    )
    assert [pin.skill_version_id for pin in pins] == [skills[0].id]


def test_publishing_a_newer_version_does_not_move_an_existing_pin(
    authored: Session, execution_id: UUID, dev_keystore: LocalKeyStore
) -> None:
    """I4. A task that picked up "the current instructions" at run time could
    never answer what its instructions *were*."""
    agent = definition_service.resolve_agent_version(authored, key=AGENT_KEY)
    task = task_service.create_task(
        authored,
        tenant_id=TENANT_A,
        execution_id=execution_id,
        sequence=1,
        agent_version=agent,
        keystore=dev_keystore,
        actor_id=ACTOR,
    )

    definition_service.publish_agent_version(authored, key=AGENT_KEY, instructions="rewritten")

    reloaded = authored.execute(select(Task).where(Task.id == task.id)).scalar_one()
    assert reloaded.agent_definition_version_id == agent.id
    pinned = authored.execute(
        select(AgentDefinitionVersion).where(
            AgentDefinitionVersion.id == reloaded.agent_definition_version_id
        )
    ).scalar_one()
    assert pinned.instructions == "Explain the variance. Cite every figure."


def test_a_pinned_version_cannot_be_dropped(
    authored: Session, execution_id: UUID, dev_keystore: LocalKeyStore
) -> None:
    """RESTRICT, not a convention: the database refuses to strand an execution."""
    agent = definition_service.resolve_agent_version(authored, key=AGENT_KEY)
    task_service.create_task(
        authored,
        tenant_id=TENANT_A,
        execution_id=execution_id,
        sequence=1,
        agent_version=agent,
        keystore=dev_keystore,
        actor_id=ACTOR,
    )
    with pytest.raises(DBAPIError):
        authored.execute(
            text("DELETE FROM agent_definition_version WHERE id = :i"), {"i": agent.id}
        )
    authored.rollback()


def test_task_creation_is_recorded_in_the_audit_chain(
    authored: Session, execution_id: UUID, dev_keystore: LocalKeyStore
) -> None:
    """The record names the pinned versions, so reconstruction can report which
    rules governed the task without joining through mutable state."""
    from adw.models.audit import AuditChainRecord

    agent = definition_service.resolve_agent_version(authored, key=AGENT_KEY)
    before = len(authored.execute(select(AuditChainRecord)).scalars().all())
    task_service.create_task(
        authored,
        tenant_id=TENANT_A,
        execution_id=execution_id,
        sequence=1,
        agent_version=agent,
        keystore=dev_keystore,
        actor_id=ACTOR,
    )
    after = authored.execute(select(AuditChainRecord)).scalars().all()
    assert len(after) - before == 1
    assert after[-1].event_type == task_service.EVENT_TASK_CREATED
