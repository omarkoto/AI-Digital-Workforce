"""The real schema, under row-level security — D9, D18, D30.

Task 3 proved the mechanism on a throwaway probe table. These prove it on the
tables the Execution Record actually uses.
"""

from __future__ import annotations

from uuid import UUID, uuid4

import pytest
from sqlalchemy import Engine, text
from sqlalchemy.exc import DBAPIError, ProgrammingError

from tests.security.conftest import TENANT_A, TENANT_B

pytestmark = pytest.mark.security


def as_tenant(
    engine: Engine, tenant: UUID | None, sql: str, **params: object
) -> list[tuple[object, ...]]:
    with engine.begin() as connection:
        if tenant is not None:
            connection.execute(
                text("SELECT set_config('app.tenant_id', :tid, true)"), {"tid": str(tenant)}
            )
        return [tuple(row) for row in connection.execute(text(sql), params)]


def test_execution_rows_are_tenant_isolated(app_engine: Engine, seeded_schema: None) -> None:
    a = as_tenant(app_engine, TENANT_A, "SELECT requester_identity FROM execution")
    b = as_tenant(app_engine, TENANT_B, "SELECT requester_identity FROM execution")
    assert a == [("amira@northwind",)]
    assert b == [("lena@contoso",)]


def test_task_rows_are_tenant_isolated(app_engine: Engine, seeded_schema: None) -> None:
    a = as_tenant(app_engine, TENANT_A, "SELECT sequence FROM task ORDER BY sequence")
    b = as_tenant(app_engine, TENANT_B, "SELECT sequence FROM task ORDER BY sequence")
    assert a == [(1,)]
    assert b == [(1,)]
    assert as_tenant(app_engine, TENANT_A, "SELECT count(*) FROM task") == [(1,)]


def test_missing_context_returns_zero_rows_on_every_tenant_table(
    app_engine: Engine, seeded_schema: None
) -> None:
    for table in ("tenant", "execution", "task", "task_skill_pin"):
        assert as_tenant(app_engine, None, f"SELECT count(*) FROM {table}") == [(0,)]


def test_a_tenant_reads_only_its_own_tenant_row(app_engine: Engine, seeded_schema: None) -> None:
    """The tenant table polices `id`, since it has no `tenant_id`."""
    rows = as_tenant(app_engine, TENANT_A, "SELECT slug FROM tenant")
    assert rows == [("northwind",)]


def test_definitions_are_readable_without_tenant_context(
    app_engine: Engine, seeded_schema: None
) -> None:
    """D30: platform-curated definitions carry no tenant data and no policy."""
    rows = as_tenant(app_engine, None, "SELECT key FROM agent_definition ORDER BY key")
    assert ("data-preparation",) in rows


def test_runtime_role_cannot_write_definitions(app_engine: Engine, seeded_schema: None) -> None:
    """Definitions are platform-curated: the application reads, never writes."""
    with pytest.raises(ProgrammingError, match="permission denied"), app_engine.begin() as conn:
        conn.execute(
            text("INSERT INTO agent_definition (id, key, name) VALUES (:i, 'x', 'x')"),
            {"i": uuid4()},
        )


def test_definition_versions_are_immutable(owner_engine: Engine, seeded_schema: None) -> None:
    """D9: a version an execution pinned can never change, even for the owner."""
    for statement in (
        "UPDATE agent_definition_version SET instructions = 'tampered'",
        "DELETE FROM agent_definition_version",
    ):
        with pytest.raises(DBAPIError, match="immutable"), owner_engine.begin() as conn:
            conn.execute(text(statement))


def test_cross_tenant_task_write_is_rejected(app_engine: Engine, seeded_schema: None) -> None:
    execution_id = as_tenant(app_engine, TENANT_B, "SELECT id FROM execution")[0][0]
    version_id = as_tenant(app_engine, None, "SELECT id FROM agent_definition_version LIMIT 1")[0][
        0
    ]
    with pytest.raises(ProgrammingError, match="row-level security"), app_engine.begin() as conn:
        conn.execute(text("SELECT set_config('app.tenant_id', :tid, true)"), {"tid": str(TENANT_A)})
        conn.execute(
            text(
                "INSERT INTO task (id, tenant_id, execution_id, sequence, "
                "agent_definition_version_id, state, attempt_no) "
                "VALUES (:i, :t, :e, 99, :v, 'planned', 1)"
            ),
            {"i": uuid4(), "t": TENANT_B, "e": execution_id, "v": version_id},
        )


def test_rework_limit_is_enforced_by_the_database(app_engine: Engine, seeded_schema: None) -> None:
    """D11 is a CHECK constraint. Three rework loops means a fourth attempt is valid."""
    with pytest.raises(DBAPIError, match="attempt_no"), app_engine.begin() as conn:
        conn.execute(text("SELECT set_config('app.tenant_id', :tid, true)"), {"tid": str(TENANT_A)})
        conn.execute(text("UPDATE task SET attempt_no = 5"))


def test_every_new_tenant_table_has_complete_rls(owner_engine: Engine, seeded_schema: None) -> None:
    """The Task 3 coverage scan, now non-vacuous."""
    for table in ("tenant", "execution", "task", "task_skill_pin"):
        with owner_engine.begin() as connection:
            enabled, forced = connection.execute(
                text("SELECT relrowsecurity, relforcerowsecurity FROM pg_class WHERE relname = :t"),
                {"t": table},
            ).one()
            policies = connection.execute(
                text("SELECT count(*) FROM pg_policies WHERE tablename = :t"), {"t": table}
            ).scalar_one()
        assert enabled is True, f"{table}: RLS not enabled"
        assert forced is True, f"{table}: RLS not forced"
        assert policies >= 1, f"{table}: no policy"
