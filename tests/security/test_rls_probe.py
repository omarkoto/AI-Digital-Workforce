"""Row-level security, proven against a live database — D15, D18, I7.

Two example tenants stand in for two customer organizations sharing the same
tables: Northwind (tenant A) and Contoso (tenant B).
"""

from __future__ import annotations

from uuid import UUID, uuid4

import pytest
from sqlalchemy import Engine, text
from sqlalchemy.exc import ProgrammingError

from tests.security.conftest import TENANT_A, TENANT_B

pytestmark = pytest.mark.security


def rows_visible_to(engine: Engine, table: str, tenant: UUID | None) -> list[str]:
    """Return the labels a connection can see, optionally under tenant context."""
    with engine.begin() as connection:
        if tenant is not None:
            connection.execute(
                text("SELECT set_config('app.tenant_id', :tid, true)"), {"tid": str(tenant)}
            )
        result = connection.execute(text(f"SELECT label FROM {table} ORDER BY label"))
        return [str(row[0]) for row in result]


def test_tenant_a_sees_its_own_rows(app_engine: Engine, probe_table: str) -> None:
    """Requirement 1."""
    assert rows_visible_to(app_engine, probe_table, TENANT_A) == ["northwind-row"]


def test_tenant_a_cannot_see_tenant_b_rows(app_engine: Engine, probe_table: str) -> None:
    """Requirement 2."""
    assert "contoso-row" not in rows_visible_to(app_engine, probe_table, TENANT_A)


def test_tenant_b_cannot_see_tenant_a_rows(app_engine: Engine, probe_table: str) -> None:
    """Requirement 3."""
    visible = rows_visible_to(app_engine, probe_table, TENANT_B)
    assert visible == ["contoso-row"]
    assert "northwind-row" not in visible


def test_missing_tenant_context_returns_zero_rows(app_engine: Engine, probe_table: str) -> None:
    """Requirement 4 — the fail-closed rule in D18.

    An absent setting must yield nothing, never everything. This is the
    difference between a safe default and a total breach.
    """
    assert rows_visible_to(app_engine, probe_table, None) == []


def test_the_probe_table_really_does_hold_both_rows(app_engine: Engine, probe_table: str) -> None:
    """Guards against the isolation tests passing because the table is empty.

    Counted one tenant at a time rather than by bypassing RLS. There is no
    bypass available, and that is the point: FORCE applies to the owner too, so
    even the role that created the table cannot read across the boundary.
    """
    seen = rows_visible_to(app_engine, probe_table, TENANT_A) + rows_visible_to(
        app_engine, probe_table, TENANT_B
    )
    assert sorted(seen) == ["contoso-row", "northwind-row"]


def test_even_the_table_owner_cannot_read_across_tenants(
    owner_engine: Engine, probe_table: str
) -> None:
    """FORCE ROW LEVEL SECURITY leaves no privileged reader inside the application.

    Without FORCE, the owning role would silently see every tenant's rows and
    every policy in the system would be decorative for migrations.
    """
    assert rows_visible_to(owner_engine, probe_table, TENANT_A) == ["northwind-row"]
    assert rows_visible_to(owner_engine, probe_table, None) == []


def test_cross_tenant_write_is_rejected(app_engine: Engine, probe_table: str) -> None:
    """Requirement 5 — WITH CHECK stops a tenant planting rows in another tenant."""
    with pytest.raises(ProgrammingError, match="row-level security"), app_engine.begin() as conn:
        conn.execute(text("SELECT set_config('app.tenant_id', :tid, true)"), {"tid": str(TENANT_A)})
        conn.execute(
            text(f"INSERT INTO {probe_table} (id, tenant_id, label) VALUES (:i, :t, :l)"),
            {"i": uuid4(), "t": TENANT_B, "l": "forged"},
        )


def test_write_within_own_tenant_is_permitted(app_engine: Engine, probe_table: str) -> None:
    """The mirror of the test above: isolation must not break ordinary work."""
    with app_engine.begin() as conn:
        conn.execute(text("SELECT set_config('app.tenant_id', :tid, true)"), {"tid": str(TENANT_A)})
        conn.execute(
            text(f"INSERT INTO {probe_table} (id, tenant_id, label) VALUES (:i, :t, :l)"),
            {"i": uuid4(), "t": TENANT_A, "l": "northwind-second"},
        )
    assert rows_visible_to(app_engine, probe_table, TENANT_A) == [
        "northwind-row",
        "northwind-second",
    ]


def test_tenant_context_does_not_survive_the_transaction(
    app_engine: Engine, probe_table: str
) -> None:
    """SET LOCAL must die with its transaction, because pooled connections are reused.

    A session-level setting would leak one tenant's context into the next
    request served by the same physical connection.
    """
    with app_engine.connect() as connection:
        with connection.begin():
            connection.execute(
                text("SELECT set_config('app.tenant_id', :tid, true)"), {"tid": str(TENANT_A)}
            )
            assert connection.execute(text(f"SELECT count(*) FROM {probe_table}")).scalar_one() == 1
        with connection.begin():
            assert connection.execute(text(f"SELECT count(*) FROM {probe_table}")).scalar_one() == 0


def test_rls_is_enabled_and_forced(owner_engine: Engine, probe_table: str) -> None:
    """Requirement 7.

    ENABLE alone leaves the table owner exempt, which would make every policy
    decorative for the role that runs migrations. FORCE closes that.
    """
    with owner_engine.begin() as connection:
        row = connection.execute(
            text("SELECT relrowsecurity, relforcerowsecurity FROM pg_class WHERE relname = :t"),
            {"t": probe_table},
        ).one()
    enabled, forced = row
    assert enabled is True
    assert forced is True
