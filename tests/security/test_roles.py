"""Database role attributes — D18 / G3.

RLS does not apply to a superuser, to a role holding BYPASSRLS, or (without
FORCE) to a table's owner. So the policies proved in test_rls_probe.py are only
meaningful if the runtime role holds none of those exemptions. These tests
assert that, permanently.
"""

from __future__ import annotations

import pytest
from sqlalchemy import Engine, text

pytestmark = pytest.mark.security

RUNTIME_ROLES = ["adw_app", "adw_anchor", "adw_auditor"]
ALL_ROLES = ["adw_owner", *RUNTIME_ROLES]


def role_attributes(engine: Engine, role: str) -> dict[str, bool]:
    with engine.begin() as connection:
        row = connection.execute(
            text("""
                SELECT rolsuper, rolbypassrls, rolcreatedb, rolcreaterole, rolcanlogin
                FROM pg_roles WHERE rolname = :r
            """),
            {"r": role},
        ).one_or_none()
    assert row is not None, f"role {role} does not exist"
    return {
        "superuser": row[0],
        "bypassrls": row[1],
        "createdb": row[2],
        "createrole": row[3],
        "canlogin": row[4],
    }


@pytest.mark.parametrize("role", ALL_ROLES)
def test_role_exists(owner_engine: Engine, role: str) -> None:
    assert role_attributes(owner_engine, role)


@pytest.mark.parametrize("role", ALL_ROLES)
def test_no_role_is_a_superuser(owner_engine: Engine, role: str) -> None:
    assert role_attributes(owner_engine, role)["superuser"] is False


@pytest.mark.parametrize("role", ALL_ROLES)
def test_no_role_bypasses_rls(owner_engine: Engine, role: str) -> None:
    """Requirement 6, first half. BYPASSRLS would silently void every policy."""
    assert role_attributes(owner_engine, role)["bypassrls"] is False


@pytest.mark.parametrize("role", RUNTIME_ROLES)
def test_runtime_roles_cannot_create_roles_or_databases(owner_engine: Engine, role: str) -> None:
    attributes = role_attributes(owner_engine, role)
    assert attributes["createdb"] is False
    assert attributes["createrole"] is False


def test_app_role_is_not_the_owner_of_tenant_tables(owner_engine: Engine, probe_table: str) -> None:
    """Requirement 6, second half.

    Without FORCE, a table's owner is exempt from its policies. The runtime role
    must therefore never own a tenant-scoped table.
    """
    with owner_engine.begin() as connection:
        owner = connection.execute(
            text("SELECT pg_get_userbyid(relowner) FROM pg_class WHERE relname = :t"),
            {"t": probe_table},
        ).scalar_one()
    assert owner == "adw_owner"
    assert owner != "adw_app"


def test_app_role_cannot_perform_ddl(app_engine: Engine) -> None:
    """DDL belongs to migrations, which run as adw_owner."""
    from sqlalchemy.exc import ProgrammingError

    with pytest.raises(ProgrammingError), app_engine.begin() as connection:
        connection.execute(text("CREATE TABLE _adw_app_should_not_create (id int)"))


def test_anchor_role_cannot_read_tenant_tables(probe_table: str) -> None:
    """I13: the anchoring role may read chain-head hashes and nothing else.

    The chain tables do not exist until Task 5, so what is provable now is the
    absence of blanket table access — the anchor role must not have inherited a
    default grant on tenant data.
    """
    import os

    from sqlalchemy import create_engine
    from sqlalchemy.exc import ProgrammingError

    url = os.environ.get("PYTEST_ANCHOR_DATABASE_URL")
    if not url:
        pytest.skip("PYTEST_ANCHOR_DATABASE_URL is not set")

    engine = create_engine(url, future=True)
    try:
        with pytest.raises(ProgrammingError, match="permission denied"), engine.begin() as conn:
            conn.execute(text(f"SELECT * FROM {probe_table}"))
    finally:
        engine.dispose()
