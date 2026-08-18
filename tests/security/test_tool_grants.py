"""Pre-declared tool permission grants — D10, I9, B3, B4.

The claim under test is B3 in its strong form: **a running agent cannot acquire
a capability it did not start with, by any path.** That is not a property of a
prompt or a service convention — it has to hold against direct SQL, which is
what most of this file checks.

No gateway exists yet. Nothing here executes a tool; these tests are about what
the gateway will be able to rely on.
"""

from __future__ import annotations

from datetime import timedelta
from uuid import UUID, uuid4

import pytest
from sqlalchemy import Engine, func, select, text
from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlalchemy.orm import Session

from adw.adapters.keystore_local import LocalKeyStore
from adw.models.audit import AuditChainRecord
from adw.models.definition import AgentDefinitionVersion
from adw.models.grant import DEFAULT_GRANT_TTL_SECONDS, ToolGrant
from adw.models.task import Task
from adw.models.tool import ToolDefinitionVersion
from adw.services import definition_service, grant_service, task_service, tool_registry
from adw.services.grant_service import GrantError, GrantRequest
from tests.security.conftest import TENANT_A

pytestmark = pytest.mark.security

ORCHESTRATOR = "platform:engagement-lead"
CONTROLLER = "human:khaled@northwind"
READ_KEY = "spreadsheet.read"
COMPUTE_KEY = "tabular.compute"


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
def read_tool(chain_session: Session) -> ToolDefinitionVersion:
    tool_registry.register_tool(
        chain_session, key=READ_KEY, name="Spreadsheet read", description="Read rows."
    )
    return tool_registry.publish_tool_version(
        chain_session,
        key=READ_KEY,
        input_schema={"type": "object"},
        output_schema={"type": "object"},
        required_scopes=["blob:read"],
    )


@pytest.fixture
def compute_tool(chain_session: Session) -> ToolDefinitionVersion:
    tool_registry.register_tool(
        chain_session, key=COMPUTE_KEY, name="Tabular compute", description="Compute figures."
    )
    return tool_registry.publish_tool_version(
        chain_session, key=COMPUTE_KEY, input_schema={}, output_schema={}
    )


def make_task(
    session: Session,
    execution_id: UUID,
    agent_version: AgentDefinitionVersion,
    keystore: LocalKeyStore,
    grants: list[GrantRequest] | None = None,
    sequence: int = 1,
) -> Task:
    return task_service.create_task(
        session,
        tenant_id=TENANT_A,
        execution_id=execution_id,
        sequence=sequence,
        agent_version=agent_version,
        tool_grants=grants or [],
        keystore=keystore,
        actor_id=ORCHESTRATOR,
    )


def now_of(session: Session) -> object:
    return session.execute(select(func.transaction_timestamp())).scalar_one()


# --- Declaration at task creation -------------------------------------------


def test_a_task_declares_its_permission_set_at_creation(
    chain_session: Session,
    execution_id: UUID,
    agent_version: AgentDefinitionVersion,
    read_tool: ToolDefinitionVersion,
    dev_keystore: LocalKeyStore,
) -> None:
    task = make_task(
        chain_session,
        execution_id,
        agent_version,
        dev_keystore,
        [GrantRequest(tool_version=read_tool, scopes=("blob:read",))],
    )
    grants = grant_service.for_task(chain_session, task.id)
    assert len(grants) == 1
    assert grants[0].tool_definition_version_id == read_tool.id
    assert grant_service.scopes(grants[0]) == frozenset({"blob:read"})


def test_a_task_with_no_declared_tools_holds_nothing(
    chain_session: Session,
    execution_id: UUID,
    agent_version: AgentDefinitionVersion,
    dev_keystore: LocalKeyStore,
) -> None:
    """The default is no capability. An agent that was granted nothing can do
    nothing, which is what least privilege means when nobody remembered to ask."""
    task = make_task(chain_session, execution_id, agent_version, dev_keystore)
    assert grant_service.for_task(chain_session, task.id) == []


def test_the_grant_is_also_the_version_pin(
    chain_session: Session,
    execution_id: UUID,
    agent_version: AgentDefinitionVersion,
    read_tool: ToolDefinitionVersion,
    dev_keystore: LocalKeyStore,
) -> None:
    """I4: one row answers both "was this allowed?" and "which version ran?"."""
    task = make_task(
        chain_session,
        execution_id,
        agent_version,
        dev_keystore,
        [GrantRequest(tool_version=read_tool, scopes=("blob:read",))],
    )
    tool_registry.publish_tool_version(
        chain_session, key=READ_KEY, input_schema={}, output_schema={}, timeout_seconds=3600
    )
    grant = grant_service.for_task(chain_session, task.id)[0]
    assert grant.tool_definition_version_id == read_tool.id, (
        "publishing a newer descriptor must not move an existing grant"
    )


def test_declaration_is_audited_with_the_task(
    chain_session: Session,
    execution_id: UUID,
    agent_version: AgentDefinitionVersion,
    read_tool: ToolDefinitionVersion,
    dev_keystore: LocalKeyStore,
) -> None:
    """A task's capability and its instructions become durable together."""
    make_task(
        chain_session,
        execution_id,
        agent_version,
        dev_keystore,
        [GrantRequest(tool_version=read_tool, scopes=("blob:read",))],
    )
    events = [
        record.event_type
        for record in chain_session.execute(select(AuditChainRecord)).scalars().all()
    ]
    assert grant_service.EVENT_GRANTS_DECLARED in events
    assert task_service.EVENT_TASK_CREATED in events


def test_a_task_may_hold_only_one_version_of_a_tool(
    chain_session: Session,
    execution_id: UUID,
    agent_version: AgentDefinitionVersion,
    read_tool: ToolDefinitionVersion,
    dev_keystore: LocalKeyStore,
) -> None:
    """A grant reviewed against one descriptor must not silently come to mean
    another."""
    second = tool_registry.publish_tool_version(
        chain_session, key=READ_KEY, input_schema={}, output_schema={}
    )
    with pytest.raises(GrantError, match="only one version"):
        make_task(
            chain_session,
            execution_id,
            agent_version,
            dev_keystore,
            [GrantRequest(tool_version=read_tool), GrantRequest(tool_version=second)],
        )


def test_the_database_enforces_one_grant_per_tool_per_task(
    chain_session: Session,
    execution_id: UUID,
    agent_version: AgentDefinitionVersion,
    read_tool: ToolDefinitionVersion,
    dev_keystore: LocalKeyStore,
) -> None:
    """The service explains; the constraint guarantees."""
    task = make_task(
        chain_session, execution_id, agent_version, dev_keystore, [GrantRequest(read_tool)]
    )
    chain_session.add(
        ToolGrant(
            tenant_id=TENANT_A,
            task_id=task.id,
            tool_definition_id=read_tool.tool_definition_id,
            tool_definition_version_id=read_tool.id,
            expires_at=now_of(chain_session),
        )
    )
    with pytest.raises(IntegrityError):
        chain_session.flush()
    chain_session.rollback()


def test_a_non_positive_lifetime_is_refused(
    chain_session: Session,
    execution_id: UUID,
    agent_version: AgentDefinitionVersion,
    read_tool: ToolDefinitionVersion,
    dev_keystore: LocalKeyStore,
) -> None:
    with pytest.raises(GrantError, match="positive lifetime"):
        make_task(
            chain_session,
            execution_id,
            agent_version,
            dev_keystore,
            [GrantRequest(tool_version=read_tool, ttl_seconds=0)],
        )


def test_grants_are_time_boxed_from_the_database_clock(
    chain_session: Session,
    execution_id: UUID,
    agent_version: AgentDefinitionVersion,
    read_tool: ToolDefinitionVersion,
    dev_keystore: LocalKeyStore,
) -> None:
    """I9/D21: the expiry the gateway enforces and the expiry a console shows
    cannot diverge, because neither comes from a host clock."""
    task = make_task(
        chain_session, execution_id, agent_version, dev_keystore, [GrantRequest(read_tool)]
    )
    grant = grant_service.for_task(chain_session, task.id)[0]
    database_now = now_of(chain_session)
    assert grant.expires_at == database_now + timedelta(seconds=DEFAULT_GRANT_TTL_SECONDS)  # type: ignore[operator]


# --- B3: the set cannot be widened ------------------------------------------


def test_there_is_no_function_that_adds_a_permission_to_a_running_task() -> None:
    """The absence is the feature. If a name like this appears, B3 has been
    quietly reversed and this test is where that shows up."""
    public = {name for name in dir(grant_service) if not name.startswith("_")}
    forbidden = {"grant", "add_grant", "escalate", "request_grant", "extend", "widen"}
    assert not public & forbidden


@pytest.mark.parametrize(
    ("column", "value"),
    [
        ("scopes_json", '\'["blob:read","blob:write"]\''),
        ("expires_at", "expires_at + interval '10 years'"),
    ],
)
def test_direct_sql_cannot_widen_a_declared_grant(
    chain_session: Session,
    execution_id: UUID,
    agent_version: AgentDefinitionVersion,
    read_tool: ToolDefinitionVersion,
    dev_keystore: LocalKeyStore,
    column: str,
    value: str,
) -> None:
    """The strong form of B3, tested where it matters: against SQL, not against a
    service that could be called differently tomorrow."""
    task = make_task(
        chain_session, execution_id, agent_version, dev_keystore, [GrantRequest(read_tool)]
    )
    grant = grant_service.for_task(chain_session, task.id)[0]
    chain_session.flush()
    with pytest.raises(DBAPIError, match="cannot be widened"):
        chain_session.execute(
            text(f"UPDATE tool_grant SET {column} = {value} WHERE id = :i"), {"i": grant.id}
        )
    chain_session.rollback()


def test_a_grant_cannot_be_repointed_at_another_tool_version(
    chain_session: Session,
    execution_id: UUID,
    agent_version: AgentDefinitionVersion,
    read_tool: ToolDefinitionVersion,
    compute_tool: ToolDefinitionVersion,
    dev_keystore: LocalKeyStore,
) -> None:
    task = make_task(
        chain_session, execution_id, agent_version, dev_keystore, [GrantRequest(read_tool)]
    )
    grant = grant_service.for_task(chain_session, task.id)[0]
    chain_session.flush()
    with pytest.raises(DBAPIError, match="cannot be widened"):
        chain_session.execute(
            text("UPDATE tool_grant SET tool_definition_version_id = :v WHERE id = :i"),
            {"v": compute_tool.id, "i": grant.id},
        )
    chain_session.rollback()


def test_a_grant_cannot_be_deleted_to_hide_that_it_existed(
    chain_session: Session,
    execution_id: UUID,
    agent_version: AgentDefinitionVersion,
    read_tool: ToolDefinitionVersion,
    dev_keystore: LocalKeyStore,
) -> None:
    task = make_task(
        chain_session, execution_id, agent_version, dev_keystore, [GrantRequest(read_tool)]
    )
    grant = grant_service.for_task(chain_session, task.id)[0]
    chain_session.flush()
    with pytest.raises(DBAPIError, match="cannot be deleted"):
        chain_session.execute(text("DELETE FROM tool_grant WHERE id = :i"), {"i": grant.id})
    chain_session.rollback()


def test_the_runtime_role_cannot_delete_a_grant(app_engine: Engine, migrated_schema: None) -> None:
    with Session(app_engine) as session:
        granted = session.execute(
            text(
                "SELECT has_table_privilege('adw_app', 'tool_grant', 'SELECT'), "
                "has_table_privilege('adw_app', 'tool_grant', 'DELETE')"
            )
        ).one()
    assert granted == (True, False)


def test_grants_are_tenant_scoped(owner_engine: Engine, migrated_schema: None) -> None:
    """I7: another tenant's permission set is not merely hidden, it is absent."""
    with Session(owner_engine) as session:
        forced = session.execute(
            text(
                "SELECT relrowsecurity, relforcerowsecurity FROM pg_class "
                "WHERE oid = cast('tool_grant' AS regclass)"
            )
        ).one()
    assert forced == (True, True)


# --- Liveness, expiry, revocation (B4) --------------------------------------


def test_a_fresh_grant_is_live(
    chain_session: Session,
    execution_id: UUID,
    agent_version: AgentDefinitionVersion,
    read_tool: ToolDefinitionVersion,
    dev_keystore: LocalKeyStore,
) -> None:
    task = make_task(
        chain_session, execution_id, agent_version, dev_keystore, [GrantRequest(read_tool)]
    )
    grant = grant_service.for_task(chain_session, task.id)[0]
    assert grant_service.is_live(grant, now=now_of(chain_session))  # type: ignore[arg-type]


def test_an_expired_grant_is_not_live(
    chain_session: Session,
    execution_id: UUID,
    agent_version: AgentDefinitionVersion,
    read_tool: ToolDefinitionVersion,
    dev_keystore: LocalKeyStore,
) -> None:
    """The time-box is real, not decorative."""
    task = make_task(
        chain_session,
        execution_id,
        agent_version,
        dev_keystore,
        [GrantRequest(tool_version=read_tool, ttl_seconds=60)],
    )
    grant = grant_service.for_task(chain_session, task.id)[0]
    assert not grant_service.is_live(grant, now=grant.expires_at + timedelta(seconds=1))


def test_revocation_is_audited_and_one_way(
    chain_session: Session,
    execution_id: UUID,
    agent_version: AgentDefinitionVersion,
    read_tool: ToolDefinitionVersion,
    dev_keystore: LocalKeyStore,
) -> None:
    task = make_task(
        chain_session, execution_id, agent_version, dev_keystore, [GrantRequest(read_tool)]
    )
    grant = grant_service.for_task(chain_session, task.id)[0]

    grant_service.revoke(
        chain_session,
        grant=grant,
        revoked_by_identity=CONTROLLER,
        keystore=dev_keystore,
        actor_id=CONTROLLER,
    )
    assert grant.revoked_at is not None
    assert grant.revoked_by_identity == CONTROLLER
    assert not grant_service.is_live(grant, now=now_of(chain_session))  # type: ignore[arg-type]

    events = [
        record.event_type
        for record in chain_session.execute(select(AuditChainRecord)).scalars().all()
    ]
    assert grant_service.EVENT_GRANT_REVOKED in events

    with pytest.raises(GrantError, match="already revoked"):
        grant_service.revoke(
            chain_session,
            grant=grant,
            revoked_by_identity=CONTROLLER,
            keystore=dev_keystore,
            actor_id=CONTROLLER,
        )


def test_a_revoked_grant_cannot_be_un_revoked_by_sql(
    chain_session: Session,
    execution_id: UUID,
    agent_version: AgentDefinitionVersion,
    read_tool: ToolDefinitionVersion,
    dev_keystore: LocalKeyStore,
) -> None:
    task = make_task(
        chain_session, execution_id, agent_version, dev_keystore, [GrantRequest(read_tool)]
    )
    grant = grant_service.for_task(chain_session, task.id)[0]
    grant_service.revoke(
        chain_session,
        grant=grant,
        revoked_by_identity=CONTROLLER,
        keystore=dev_keystore,
        actor_id=CONTROLLER,
    )
    chain_session.flush()
    with pytest.raises(DBAPIError, match="un-revoked"):
        chain_session.execute(
            text(
                "UPDATE tool_grant SET revoked_at = NULL, revoked_by_identity = NULL WHERE id = :i"
            ),
            {"i": grant.id},
        )
    chain_session.rollback()


def test_a_revocation_must_name_who_made_it(
    chain_session: Session,
    execution_id: UUID,
    agent_version: AgentDefinitionVersion,
    read_tool: ToolDefinitionVersion,
    dev_keystore: LocalKeyStore,
) -> None:
    task = make_task(
        chain_session, execution_id, agent_version, dev_keystore, [GrantRequest(read_tool)]
    )
    grant = grant_service.for_task(chain_session, task.id)[0]
    chain_session.flush()
    with pytest.raises(DBAPIError):
        chain_session.execute(
            text("UPDATE tool_grant SET revoked_at = transaction_timestamp() WHERE id = :i"),
            {"i": grant.id},
        )
    chain_session.rollback()


def test_the_full_declared_set_survives_revocation(
    chain_session: Session,
    execution_id: UUID,
    agent_version: AgentDefinitionVersion,
    read_tool: ToolDefinitionVersion,
    dev_keystore: LocalKeyStore,
) -> None:
    """ "What was this task ever allowed to do?" is a different question from
    "what may it do now", and the record has to answer both."""
    task = make_task(
        chain_session, execution_id, agent_version, dev_keystore, [GrantRequest(read_tool)]
    )
    grant = grant_service.for_task(chain_session, task.id)[0]
    grant_service.revoke(
        chain_session,
        grant=grant,
        revoked_by_identity=CONTROLLER,
        keystore=dev_keystore,
        actor_id=CONTROLLER,
    )
    assert len(grant_service.for_task(chain_session, task.id)) == 1


# --- What the gateway will rely on ------------------------------------------


def test_a_grant_covers_only_the_exact_version_it_named(
    chain_session: Session,
    execution_id: UUID,
    agent_version: AgentDefinitionVersion,
    read_tool: ToolDefinitionVersion,
    dev_keystore: LocalKeyStore,
) -> None:
    """Identity, not compatibility. The point of pinning is that nobody has to
    judge whether a change mattered."""
    task = make_task(
        chain_session,
        execution_id,
        agent_version,
        dev_keystore,
        [GrantRequest(tool_version=read_tool, scopes=("blob:read",))],
    )
    grant = grant_service.for_task(chain_session, task.id)[0]
    newer = tool_registry.publish_tool_version(
        chain_session,
        key=READ_KEY,
        input_schema={},
        output_schema={},
        required_scopes=["blob:read"],
    )
    assert grant_service.covers(grant, read_tool)
    assert not grant_service.covers(grant, newer)


def test_a_grant_missing_a_required_scope_does_not_cover_the_tool(
    chain_session: Session,
    execution_id: UUID,
    agent_version: AgentDefinitionVersion,
    read_tool: ToolDefinitionVersion,
    dev_keystore: LocalKeyStore,
) -> None:
    """The descriptor declares what is needed; the grant declares what is held.
    Neither is widened by anything the model says."""
    task = make_task(
        chain_session, execution_id, agent_version, dev_keystore, [GrantRequest(read_tool)]
    )
    grant = grant_service.for_task(chain_session, task.id)[0]
    assert grant_service.scopes(grant) == frozenset()
    assert not grant_service.covers(grant, read_tool)


def test_an_undeclared_tool_has_no_grant_at_all(
    chain_session: Session,
    execution_id: UUID,
    agent_version: AgentDefinitionVersion,
    read_tool: ToolDefinitionVersion,
    compute_tool: ToolDefinitionVersion,
    dev_keystore: LocalKeyStore,
) -> None:
    """What the gateway's first check will find: nothing. Not a narrower
    permission — an absence."""
    task = make_task(
        chain_session, execution_id, agent_version, dev_keystore, [GrantRequest(read_tool)]
    )
    assert (
        grant_service.find(
            chain_session, task_id=task.id, tool_definition_id=compute_tool.tool_definition_id
        )
        is None
    )


def test_grants_are_per_task_not_per_execution(
    chain_session: Session,
    execution_id: UUID,
    agent_version: AgentDefinitionVersion,
    read_tool: ToolDefinitionVersion,
    dev_keystore: LocalKeyStore,
) -> None:
    """D10: the task is the unit of permission. A sibling task in the same
    execution inherits nothing."""
    granted = make_task(
        chain_session,
        execution_id,
        agent_version,
        dev_keystore,
        [GrantRequest(read_tool)],
        sequence=1,
    )
    sibling = make_task(chain_session, execution_id, agent_version, dev_keystore, sequence=2)
    assert len(grant_service.for_task(chain_session, granted.id)) == 1
    assert grant_service.for_task(chain_session, sibling.id) == []
