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
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from sqlalchemy import Engine, create_engine, text
from sqlalchemy.orm import Session

from adw.adapters.keystore_local import LocalKeyStore

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


@pytest.fixture(scope="session")
def anchor_engine() -> Iterator[Engine]:
    """Connection as adw_anchor — may read chain heads and nothing else (I13)."""
    engine = _engine_or_skip("PYTEST_ANCHOR_DATABASE_URL")
    yield engine
    engine.dispose()


def _alembic_config() -> object:
    from alembic.config import Config

    root = Path(__file__).resolve().parents[2]
    config = Config(str(root / "alembic.ini"))
    config.set_main_option("script_location", str(root / "migrations"))
    return config


@pytest.fixture
def migrated_schema(owner_engine: Engine) -> Iterator[None]:
    """Apply every migration, then roll all the way back."""
    from alembic import command

    config = _alembic_config()
    command.upgrade(config, "head")  # type: ignore[arg-type]
    yield
    command.downgrade(config, "base")  # type: ignore[arg-type]


@pytest.fixture
def dev_keystore(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[LocalKeyStore]:
    """A throwaway key store. Development-only by construction."""
    from adw import config as app_config

    monkeypatch.setenv("ADW_APP_ENV", "dev")
    monkeypatch.setenv("ADW_DATABASE_URL", os.environ["ADW_DATABASE_URL"])
    monkeypatch.setenv("ADW_MIGRATION_DATABASE_URL", os.environ["ADW_MIGRATION_DATABASE_URL"])
    app_config.get_settings.cache_clear()
    store = LocalKeyStore(tmp_path / "keys.json")
    yield store
    app_config.get_settings.cache_clear()


@pytest.fixture
def chain_session(owner_engine: Engine, migrated_schema: None) -> Iterator[Session]:
    """A tenant-scoped session for tenant A, with the tenant row seeded."""
    with Session(owner_engine) as session:
        session.execute(text("SELECT set_config('app.tenant_id', :t, true)"), {"t": str(TENANT_A)})
        session.execute(
            text("INSERT INTO tenant (id, slug, name) VALUES (:i, 'northwind', 'Northwind')"),
            {"i": TENANT_A},
        )
        session.flush()
        yield session
        session.rollback()


@pytest.fixture
def seeded_chain(
    owner_engine: Engine, migrated_schema: None, dev_keystore: LocalKeyStore
) -> Iterator[None]:
    """Two tenants with chains of different lengths, committed."""
    from adw.services import audit_writer

    for tenant, slug, count in ((TENANT_A, "northwind", 2), (TENANT_B, "contoso", 1)):
        with Session(owner_engine) as session:
            session.execute(
                text("SELECT set_config('app.tenant_id', :t, true)"), {"t": str(tenant)}
            )
            session.execute(
                text("INSERT INTO tenant (id, slug, name) VALUES (:i, :s, :n)"),
                {"i": tenant, "s": slug, "n": slug.title()},
            )
            for _ in range(count):
                audit_writer.append(
                    session,
                    tenant_id=tenant,
                    event_type="task.transitioned",
                    actor_id="agent:seed",
                    payload={"detail": slug},
                    keystore=dev_keystore,
                )
            session.commit()
    yield


@pytest.fixture
def seeded_schema(owner_engine: Engine) -> Iterator[None]:
    """Apply the migration and seed two tenants with one execution and task each.

    Seeding runs as the owner under each tenant's own context, because FORCE
    ROW LEVEL SECURITY applies to the owner too — there is no privileged writer.
    """
    from alembic import command
    from alembic.config import Config

    root = Path(__file__).resolve().parents[2]
    alembic_config = Config(str(root / "alembic.ini"))
    alembic_config.set_main_option("script_location", str(root / "migrations"))

    command.upgrade(alembic_config, "head")

    agent_version_id, skill_version_id = uuid4(), uuid4()
    with owner_engine.begin() as connection:
        agent_id, skill_id = uuid4(), uuid4()
        connection.execute(
            text("INSERT INTO agent_definition (id, key, name) VALUES (:i, :k, :n)"),
            {"i": agent_id, "k": "data-preparation", "n": "Data Preparation"},
        )
        connection.execute(
            text(
                "INSERT INTO agent_definition_version "
                "(id, agent_definition_id, version_no, instructions) VALUES (:i, :d, 1, :x)"
            ),
            {"i": agent_version_id, "d": agent_id, "x": "normalize the source workbook"},
        )
        connection.execute(
            text("INSERT INTO skill (id, key, name) VALUES (:i, :k, :n)"),
            {"i": skill_id, "k": "financial-normalization", "n": "Financial normalization"},
        )
        connection.execute(
            text(
                "INSERT INTO skill_version (id, skill_id, version_no, content) "
                "VALUES (:i, :s, 1, :c)"
            ),
            {"i": skill_version_id, "s": skill_id, "c": "how to normalize actuals"},
        )

    for tenant, slug, requester in (
        (TENANT_A, "northwind", "amira@northwind"),
        (TENANT_B, "contoso", "lena@contoso"),
    ):
        with owner_engine.begin() as connection:
            connection.execute(
                text("SELECT set_config('app.tenant_id', :tid, true)"), {"tid": str(tenant)}
            )
            connection.execute(
                text("INSERT INTO tenant (id, slug, name) VALUES (:i, :s, :n)"),
                {"i": tenant, "s": slug, "n": slug.title()},
            )
            execution_id, task_id = uuid4(), uuid4()
            connection.execute(
                text(
                    "INSERT INTO execution (id, tenant_id, requester_identity, state) "
                    "VALUES (:i, :t, :r, 'draft')"
                ),
                {"i": execution_id, "t": tenant, "r": requester},
            )
            connection.execute(
                text(
                    "INSERT INTO task (id, tenant_id, execution_id, sequence, "
                    "agent_definition_version_id, state, attempt_no) "
                    "VALUES (:i, :t, :e, 1, :v, 'planned', 1)"
                ),
                {"i": task_id, "t": tenant, "e": execution_id, "v": agent_version_id},
            )
            connection.execute(
                text(
                    "INSERT INTO task_skill_pin (id, tenant_id, task_id, skill_version_id) "
                    "VALUES (:i, :t, :k, :s)"
                ),
                {"i": uuid4(), "t": tenant, "k": task_id, "s": skill_version_id},
            )

    yield

    command.downgrade(alembic_config, "base")
