"""Every tenant-owned table carries row-level security — D18 / G3.

This check is close to vacuous today because the domain schema is empty. It is
written now so that the first tenant-owned table added in Task 4 cannot ship
without a policy: the failure arrives from CI rather than from a review.
"""

from __future__ import annotations

import pytest
from sqlalchemy import Engine, text

pytestmark = pytest.mark.security

# Platform-scoped by design (I13). These carry identifiers and hashes only,
# never business content, and are governed by role grants rather than by a
# tenant policy. Listed explicitly so an addition here is a deliberate act.
PLATFORM_SCOPED_TABLES = frozenset(
    {
        "alembic_version",
        "dispatch_queue",
        "anchor_record",
        "anchor_head",
    }
)


def tables_with_tenant_id(engine: Engine) -> list[str]:
    with engine.begin() as connection:
        result = connection.execute(
            text("""
                SELECT c.relname
                FROM pg_class c
                JOIN pg_namespace n ON n.oid = c.relnamespace
                JOIN pg_attribute a ON a.attrelid = c.oid
                WHERE n.nspname = 'public'
                  AND c.relkind = 'r'
                  AND a.attname = 'tenant_id'
                  AND NOT a.attisdropped
                ORDER BY c.relname
            """)
        )
        return [str(row[0]) for row in result]


def security_flags(engine: Engine, table: str) -> tuple[bool, bool, int]:
    with engine.begin() as connection:
        enabled, forced = connection.execute(
            text("SELECT relrowsecurity, relforcerowsecurity FROM pg_class WHERE relname = :t"),
            {"t": table},
        ).one()
        policies = connection.execute(
            text("SELECT count(*) FROM pg_policies WHERE tablename = :t"), {"t": table}
        ).scalar_one()
    return bool(enabled), bool(forced), int(policies)


def test_every_tenant_scoped_table_enables_and_forces_rls(owner_engine: Engine) -> None:
    failures: list[str] = []
    for table in tables_with_tenant_id(owner_engine):
        if table in PLATFORM_SCOPED_TABLES:
            continue
        enabled, forced, policies = security_flags(owner_engine, table)
        if not enabled:
            failures.append(f"{table}: RLS not enabled")
        if not forced:
            failures.append(f"{table}: RLS not forced")
        if policies == 0:
            failures.append(f"{table}: no policy defined")
    assert not failures, "tenant-owned tables without complete RLS: " + "; ".join(failures)


def test_the_probe_table_is_detected_by_the_coverage_scan(
    owner_engine: Engine, probe_table: str
) -> None:
    """Proves the scan above can actually see a tenant-owned table.

    Without this, an empty result would make the coverage test pass for the
    wrong reason forever.
    """
    assert probe_table in tables_with_tenant_id(owner_engine)


def test_coverage_scan_would_catch_an_unprotected_table(owner_engine: Engine) -> None:
    """Negative control: a tenant-owned table with no RLS must be reported."""
    unprotected = "_rls_coverage_negative_control"
    with owner_engine.begin() as connection:
        connection.execute(text(f"DROP TABLE IF EXISTS {unprotected}"))
        connection.execute(text(f"CREATE TABLE {unprotected} (id int, tenant_id uuid)"))
    try:
        enabled, forced, policies = security_flags(owner_engine, unprotected)
        assert enabled is False
        assert forced is False
        assert policies == 0
        assert unprotected in tables_with_tenant_id(owner_engine)
    finally:
        with owner_engine.begin() as connection:
            connection.execute(text(f"DROP TABLE IF EXISTS {unprotected}"))
