"""Deprecation as an append-only record — D9.

D9 permits exactly one lifecycle event on a pinned version: deprecation. The
question these tests answer is whether that event can happen **without the
version row changing at all**, because the guarantee worth keeping absolute is
the simplest one to check: no UPDATE on a version table, by any role, ever.

Three claims, and all three must hold:

1. The version row stays byte-immutable, and the ``is_deprecated`` column is
   gone rather than left as dead state.
2. A deprecated version cannot be selected for a **new** task.
3. An execution that already pinned it keeps it, keeps reading it, and keeps
   reconstructing from it.
"""

from __future__ import annotations

from uuid import UUID, uuid4

import pytest
from sqlalchemy import Engine, inspect, select, text
from sqlalchemy.exc import DBAPIError, IntegrityError, ProgrammingError
from sqlalchemy.orm import Session

from adw.adapters.blobstore_local import LocalBlobStore
from adw.adapters.keystore_local import LocalKeyStore
from adw.adapters.llm_fake import FakeLLMProvider
from adw.models.definition import (
    AgentDefinitionVersion,
    DefinitionDeprecation,
    DefinitionKind,
)
from adw.models.task import Task
from adw.runtime import agent_runtime
from adw.runtime.agent_runtime import StopReason
from adw.runtime.context import UntrustedInput
from adw.services import definition_service, task_service
from adw.services.definition_service import DeprecationError, NoPublishableVersionError
from tests.security.conftest import TENANT_A

pytestmark = pytest.mark.security

CURATOR = "lena@platform"
AGENT_KEY = "commentary"
SKILL_KEY = "variance-narrative"

VERSION_TABLES = (
    "agent_definition_version",
    "skill_version",
    "artifact_definition_version",
    "gate_definition_version",
)


@pytest.fixture
def authored(chain_session: Session) -> Session:
    definition_service.create_agent_definition(chain_session, key=AGENT_KEY, name="Commentary")
    definition_service.publish_agent_version(
        chain_session, key=AGENT_KEY, instructions="Explain the variance."
    )
    definition_service.create_skill(chain_session, key=SKILL_KEY, name="Variance narrative")
    definition_service.publish_skill_version(
        chain_session, key=SKILL_KEY, content="Driver, then amount."
    )
    return chain_session


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


def retire(session: Session, version: AgentDefinitionVersion) -> DefinitionDeprecation:
    return definition_service.deprecate(
        session,
        kind=DefinitionKind.AGENT_DEFINITION,
        version_id=version.id,
        deprecated_by_identity=CURATOR,
        reason="cited a figure format the gate rejects",
    )


# --- 1. The version row never changes ---------------------------------------


@pytest.mark.parametrize("table", VERSION_TABLES)
def test_the_dead_flag_is_gone_from_every_version_table(
    owner_engine: Engine, migrated_schema: None, table: str
) -> None:
    """Removed rather than kept: a column that can never change from its default
    is state that lies about what the schema supports."""
    columns = {column["name"] for column in inspect(owner_engine).get_columns(table)}
    assert "is_deprecated" not in columns


@pytest.mark.parametrize("table", VERSION_TABLES)
def test_every_version_table_still_refuses_all_updates_unconditionally(
    owner_engine: Engine, migrated_schema: None, table: str
) -> None:
    """The guarantee stays absolute, which is the whole argument for this design.

    Asserted structurally: the trigger fires on **every** UPDATE and DELETE, with
    no ``WHEN`` clause carving out an exemption. That is the difference between
    "this row never changes" and "this row never changes except…", and a
    qualified invariant is the kind that acquires a second exemption later.

    A behavioural check needs a row for a row-level trigger to fire at all — see
    ``test_updating_a_version_row_is_refused`` below, and the pair in
    ``test_definition_authoring.py``.
    """
    with Session(owner_engine) as session:
        row = session.execute(
            text(
                "SELECT tgtype, tgqual IS NULL AS unconditional FROM pg_trigger "
                "WHERE tgrelid = cast(:t AS regclass) AND NOT tgisinternal"
            ),
            {"t": table},
        ).one()
    tgtype = int(row.tgtype)
    assert tgtype & 0b00000010, "must fire BEFORE the write"
    assert tgtype & 0b00000001, "must fire FOR EACH ROW"
    assert tgtype & 0b00010000, "must cover UPDATE"
    assert tgtype & 0b00001000, "must cover DELETE"
    assert row.unconditional, "no WHEN clause may exempt a column from immutability"


@pytest.mark.parametrize(
    ("table", "column"),
    [
        ("agent_definition_version", "instructions"),
        ("skill_version", "content"),
    ],
)
def test_updating_a_version_row_is_refused(authored: Session, table: str, column: str) -> None:
    """The behavioural half, on tables the fixture actually populates."""
    with pytest.raises(DBAPIError, match="immutable"):
        authored.execute(text(f"UPDATE {table} SET {column} = 'rewritten'"))
    authored.rollback()


def test_deprecating_leaves_the_version_row_untouched(authored: Session) -> None:
    version = definition_service.resolve_agent_version(authored, key=AGENT_KEY)
    before = authored.execute(
        text(
            "SELECT instructions, version_no, created_at FROM agent_definition_version "
            "WHERE id = :i"
        ),
        {"i": version.id},
    ).one()

    retire(authored, version)

    after = authored.execute(
        text(
            "SELECT instructions, version_no, created_at FROM agent_definition_version "
            "WHERE id = :i"
        ),
        {"i": version.id},
    ).one()
    assert before == after


# --- Auditability -----------------------------------------------------------


def test_the_record_names_who_when_and_why(authored: Session) -> None:
    """Deprecation is an act with an actor, a time, and a reason — the shape a
    boolean could not carry, and the reason this is a record at all."""
    version = definition_service.resolve_agent_version(authored, key=AGENT_KEY)
    record = retire(authored, version)

    assert record.deprecated_by_identity == CURATOR
    assert record.reason == "cited a figure format the gate rejects"
    assert record.created_at is not None
    assert record.kind is DefinitionKind.AGENT_DEFINITION
    assert record.subject_id == version.id


def test_a_deprecation_must_state_a_reason(authored: Session) -> None:
    """ "Why is this retired?" is the question an operator asks six months later."""
    version = definition_service.resolve_agent_version(authored, key=AGENT_KEY)
    with pytest.raises(DeprecationError, match="must state a reason"):
        definition_service.deprecate(
            authored,
            kind=DefinitionKind.AGENT_DEFINITION,
            version_id=version.id,
            deprecated_by_identity=CURATOR,
            reason="   ",
        )


def test_the_record_is_append_only(authored: Session) -> None:
    version = definition_service.resolve_agent_version(authored, key=AGENT_KEY)
    record = retire(authored, version)
    authored.flush()

    with pytest.raises(DBAPIError, match="append-only"):
        authored.execute(
            text("UPDATE definition_deprecation SET reason = 'rewritten' WHERE id = :i"),
            {"i": record.id},
        )
    authored.rollback()


def test_the_record_cannot_be_deleted(authored: Session) -> None:
    """Un-deprecating by deleting the record would make retirement reversible
    without a trace. Publishing a new version is the way forward."""
    version = definition_service.resolve_agent_version(authored, key=AGENT_KEY)
    record = retire(authored, version)
    authored.flush()

    with pytest.raises(DBAPIError, match="append-only"):
        authored.execute(text("DELETE FROM definition_deprecation WHERE id = :i"), {"i": record.id})
    authored.rollback()


def test_deprecating_twice_is_refused(authored: Session) -> None:
    """Deprecating twice is not a second fact."""
    version = definition_service.resolve_agent_version(authored, key=AGENT_KEY)
    retire(authored, version)
    with pytest.raises(DeprecationError, match="already deprecated"):
        retire(authored, version)


def test_the_uniqueness_is_enforced_by_the_database_not_only_the_service(
    authored: Session,
) -> None:
    version = definition_service.resolve_agent_version(authored, key=AGENT_KEY)
    retire(authored, version)
    authored.flush()
    authored.add(
        DefinitionDeprecation(
            agent_definition_version_id=version.id,
            deprecated_by_identity=CURATOR,
            reason="a second attempt",
        )
    )
    with pytest.raises(IntegrityError):
        authored.flush()
    authored.rollback()


def test_a_record_must_name_exactly_one_version(authored: Session) -> None:
    """Four real foreign keys rather than a kind-plus-id pair, so a deprecation
    of a version that does not exist is impossible."""
    version = definition_service.resolve_agent_version(authored, key=AGENT_KEY)
    skill = definition_service.resolve_skill_version(authored, key=SKILL_KEY)
    authored.add(
        DefinitionDeprecation(
            agent_definition_version_id=version.id,
            skill_version_id=skill.id,
            deprecated_by_identity=CURATOR,
            reason="two at once",
        )
    )
    with pytest.raises(IntegrityError):
        authored.flush()
    authored.rollback()


def test_an_unknown_version_cannot_be_deprecated(authored: Session) -> None:
    authored.add(
        DefinitionDeprecation(
            agent_definition_version_id=uuid4(),
            deprecated_by_identity=CURATOR,
            reason="nothing there",
        )
    )
    with pytest.raises(IntegrityError):
        authored.flush()
    authored.rollback()


def test_a_deprecated_version_cannot_be_deleted(authored: Session) -> None:
    """RESTRICT: a deprecated version must outlive its retirement."""
    version = definition_service.resolve_agent_version(authored, key=AGENT_KEY)
    retire(authored, version)
    authored.flush()
    with pytest.raises(DBAPIError):
        authored.execute(
            text("DELETE FROM agent_definition_version WHERE id = :i"), {"i": version.id}
        )
    authored.rollback()


# --- Privilege --------------------------------------------------------------


def test_the_runtime_role_cannot_deprecate(app_engine: Engine, migrated_schema: None) -> None:
    """A tenant runtime cannot retire a definition any more than it can publish
    one (D5/D30) — and an agent cannot be talked into it either."""
    with Session(app_engine) as session:
        session.execute(text("SELECT set_config('app.tenant_id', :t, true)"), {"t": str(TENANT_A)})
        with pytest.raises(ProgrammingError, match="permission denied"):
            session.execute(
                text(
                    "INSERT INTO definition_deprecation "
                    "(id, agent_definition_version_id, deprecated_by_identity, reason) "
                    "VALUES (:i, :v, 'agent:rogue', 'because I said so')"
                ),
                {"i": uuid4(), "v": uuid4()},
            )
        session.rollback()


def test_the_runtime_role_can_read_deprecations(app_engine: Engine, migrated_schema: None) -> None:
    """Resolution runs on the runtime connection and has to see them."""
    with Session(app_engine) as session:
        granted = session.execute(
            text(
                "SELECT has_table_privilege('adw_app', 'definition_deprecation', 'SELECT'), "
                "has_table_privilege('adw_app', 'definition_deprecation', 'INSERT')"
            )
        ).one()
    assert granted == (True, False)


# --- 2. New tasks cannot select a deprecated version ------------------------


def test_a_deprecated_version_is_not_selected_for_a_new_task(authored: Session) -> None:
    definition_service.publish_agent_version(authored, key=AGENT_KEY, instructions="v2")
    latest = definition_service.resolve_agent_version(authored, key=AGENT_KEY)
    assert latest.version_no == 2

    retire(authored, latest)
    assert definition_service.resolve_agent_version(authored, key=AGENT_KEY).version_no == 1


def test_deprecating_every_version_reports_no_publishable_version(authored: Session) -> None:
    """Distinct from "not found": a retired definition and a missing one are
    different problems for whoever has to fix them."""
    only = definition_service.resolve_agent_version(authored, key=AGENT_KEY)
    retire(authored, only)
    with pytest.raises(NoPublishableVersionError):
        definition_service.resolve_agent_version(authored, key=AGENT_KEY)


def test_deprecation_is_per_version_not_per_definition(authored: Session) -> None:
    v1 = definition_service.resolve_agent_version(authored, key=AGENT_KEY)
    definition_service.publish_agent_version(authored, key=AGENT_KEY, instructions="v2")
    retire(authored, v1)
    assert definition_service.resolve_agent_version(authored, key=AGENT_KEY).version_no == 2
    assert definition_service.is_deprecated(
        authored, kind=DefinitionKind.AGENT_DEFINITION, version_id=v1.id
    )


def test_deprecating_an_agent_version_does_not_retire_a_skill(authored: Session) -> None:
    version = definition_service.resolve_agent_version(authored, key=AGENT_KEY)
    retire(authored, version)
    assert definition_service.resolve_skill_version(authored, key=SKILL_KEY).version_no == 1


# --- 3. Existing pins keep working ------------------------------------------


def test_a_task_that_already_pinned_a_version_keeps_it(
    authored: Session, execution_id: UUID, dev_keystore: LocalKeyStore
) -> None:
    """The whole reason a version can be retired but never deleted."""
    pinned = definition_service.resolve_agent_version(authored, key=AGENT_KEY)
    skill = definition_service.resolve_skill_version(authored, key=SKILL_KEY)
    task = task_service.create_task(
        authored,
        tenant_id=TENANT_A,
        execution_id=execution_id,
        sequence=1,
        agent_version=pinned,
        skill_versions=[skill],
        keystore=dev_keystore,
        actor_id="platform:orchestrator",
    )

    retire(authored, pinned)
    definition_service.deprecate(
        authored,
        kind=DefinitionKind.SKILL,
        version_id=skill.id,
        deprecated_by_identity=CURATOR,
        reason="superseded",
    )

    reloaded = authored.execute(select(Task).where(Task.id == task.id)).scalar_one()
    assert reloaded.agent_definition_version_id == pinned.id

    still_readable = authored.execute(
        select(AgentDefinitionVersion).where(AgentDefinitionVersion.id == pinned.id)
    ).scalar_one()
    assert still_readable.instructions == "Explain the variance."


def test_an_exact_version_still_resolves_after_deprecation(authored: Session) -> None:
    """Reproducing a past execution must survive the retirement of its rules."""
    version = definition_service.resolve_agent_version(authored, key=AGENT_KEY)
    retire(authored, version)
    exact = definition_service.resolve_agent_version(authored, key=AGENT_KEY, version_no=1)
    assert exact.id == version.id
    assert exact.instructions == "Explain the variance."


def test_a_pinned_deprecated_version_still_drives_an_agent(
    authored: Session,
    execution_id: UUID,
    dev_keystore: LocalKeyStore,
    dev_blobstore: LocalBlobStore,
) -> None:
    """A retired definition must keep governing the executions that pinned it,
    or retiring one would silently change work already under way."""
    pinned = definition_service.resolve_agent_version(authored, key=AGENT_KEY)
    task = task_service.create_task(
        authored,
        tenant_id=TENANT_A,
        execution_id=execution_id,
        sequence=1,
        agent_version=pinned,
        keystore=dev_keystore,
        actor_id="platform:orchestrator",
    )
    retire(authored, pinned)

    provider = FakeLLMProvider(fallback="Variance explained.")
    result = agent_runtime.run_task(
        authored,
        task=task,
        agent_version=pinned,
        inputs=[UntrustedInput(label="requirement", content="explain")],
        provider=provider,
        keystore=dev_keystore,
        blobstore=dev_blobstore,
        actor_id="agent:commentary",
    )
    assert result.stop_reason is StopReason.COMPLETED
    assert "Explain the variance." in provider.calls[0].messages[0].content
