"""Fixtures for the tenant-isolation suite.

These tests need a live PostgreSQL and two distinct connections — one as the
owner role that performs DDL, one as the runtime role that must be constrained
by row-level security. They skip cleanly when either is unconfigured.

The probe table is test-only. It is created and dropped inside a fixture, is
never referenced by a migration, and introduces no business concept: it exists
solely to give RLS something to filter while the domain schema is still empty.
"""

from __future__ import annotations

import os
from collections.abc import Iterator
from uuid import UUID, uuid4

import pytest
from sqlalchemy import Engine, create_engine, text

PROBE_TABLE = "_rls_probe"

TENANT_A = UUID("aaaaaaaa-0000-4000-8000-00000000000a")
TENANT_B = UUID("bbbbbbbb-0000-4000-8000-00000000000b")


def _engine_or_skip(variable: str) -> Engine:
    url = os.environ.get(variable)
    if not url:
        pytest.skip(f"{variable} is not set; skipping isolation test")
    return create_engine(url, future=True, poolclass=None)


@pytest.fixture(scope="session")
def owner_engine() -> Iterator[Engine]:
    """Connection as adw_owner — the DDL role Alembic uses."""
    engine = _engine_or_skip("ADW_MIGRATION_DATABASE_URL")
    yield engine
    engine.dispose()


@pytest.fixture(scope="session")
def app_engine() -> Iterator[Engine]:
    """Connection as adw_app — the runtime role, constrained by RLS."""
    engine = _engine_or_skip("ADW_DATABASE_URL")
    yield engine
    engine.dispose()


@pytest.fixture
def probe_table(owner_engine: Engine) -> Iterator[str]:
    """Create a tenant-scoped probe table, then drop it.

    Seed rows are inserted before RLS is enabled, because FORCE ROW LEVEL
    SECURITY applies to the table owner too — which is the point of forcing it.
    """
    with owner_engine.begin() as connection:
        connection.execute(text(f"DROP TABLE IF EXISTS {PROBE_TABLE}"))
        connection.execute(
            text(f"""
                CREATE TABLE {PROBE_TABLE} (
                    id        uuid PRIMARY KEY,
                    tenant_id uuid NOT NULL,
                    label     text NOT NULL
                )
            """)
        )
        for tenant, label in ((TENANT_A, "northwind-row"), (TENANT_B, "contoso-row")):
            connection.execute(
                text(f"INSERT INTO {PROBE_TABLE} (id, tenant_id, label) VALUES (:i, :t, :l)"),
                {"i": uuid4(), "t": tenant, "l": label},
            )
        connection.execute(text(f"ALTER TABLE {PROBE_TABLE} ENABLE ROW LEVEL SECURITY"))
        connection.execute(text(f"ALTER TABLE {PROBE_TABLE} FORCE ROW LEVEL SECURITY"))
        # The predicate every tenant policy uses. When app.tenant_id is unset,
        # current_setting returns NULL, the comparison is NULL rather than true,
        # and the query sees zero rows — the fail-closed rule in D18.
        predicate = "tenant_id = nullif(current_setting('app.tenant_id', true), '')::uuid"
        connection.execute(
            text(f"""
                CREATE POLICY {PROBE_TABLE}_tenant_isolation ON {PROBE_TABLE}
                    USING ({predicate})
                    WITH CHECK ({predicate})
            """)
        )
        grant = f"GRANT SELECT, INSERT, UPDATE, DELETE ON {PROBE_TABLE} TO adw_app"
        connection.execute(text(grant))

    yield PROBE_TABLE

    with owner_engine.begin() as connection:
        connection.execute(text(f"DROP TABLE IF EXISTS {PROBE_TABLE}"))
