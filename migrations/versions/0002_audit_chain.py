"""Per-tenant audit chain: chain_record and chain_head.

Revision ID: 0002_audit_chain
Revises: 0001_execution_record_core
Create Date: Phase 1 Task 5

Also corrects the Task 4 timestamp columns to ``timestamptz``. D21 requires UTC
at rest, and ``timestamp without time zone`` silently discards the offset — a
defect worth fixing while the tables are still empty.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0002_audit_chain"
down_revision: str | None = "0001_execution_record_core"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TENANT_PREDICATE = "tenant_id = nullif(current_setting('app.tenant_id', true), '')::uuid"

PLATFORM_TENANT_ID = "00000000-0000-0000-0000-000000000000"

TIMESTAMP_COLUMNS = (
    ("tenant", "created_at"),
    ("agent_definition", "created_at"),
    ("agent_definition_version", "created_at"),
    ("skill", "created_at"),
    ("skill_version", "created_at"),
    ("execution", "created_at"),
    ("execution", "updated_at"),
    ("task", "created_at"),
    ("task", "updated_at"),
    ("task_skill_pin", "created_at"),
)


def upgrade() -> None:
    # --- D21: UTC at rest means timestamptz, not naive timestamps -----------
    for table, column in TIMESTAMP_COLUMNS:
        op.execute(
            f"ALTER TABLE {table} ALTER COLUMN {column} TYPE timestamptz "
            f"USING {column} AT TIME ZONE 'UTC'"
        )

    # --- The reserved platform tenant (D20) ---------------------------------
    # Events belonging to no tenant need a chain, and the chain needs a tenant
    # row to reference. Inserted here rather than seeded by the application so
    # it exists before anything can need it.
    # The tenant table forces row-level security, so even this migration has no
    # privileged write path — which is the point of FORCE. The insert therefore
    # runs under the platform tenant's own context, exactly as any other write
    # would.
    op.execute(f"SELECT set_config('app.tenant_id', '{PLATFORM_TENANT_ID}', true)")
    op.execute(
        f"INSERT INTO tenant (id, slug, name) "
        f"VALUES ('{PLATFORM_TENANT_ID}', 'platform', 'Platform') "
        f"ON CONFLICT (id) DO NOTHING"
    )
    op.execute("SELECT set_config('app.tenant_id', '', true)")

    op.create_table(
        "chain_record",
        sa.Column("id", sa.dialects.postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("tenant_id", sa.dialects.postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("seq", sa.Integer(), nullable=False),
        sa.Column("prev_hash", sa.String(), nullable=True),
        sa.Column("event_type", sa.String(), nullable=False),
        sa.Column("actor_id", sa.String(), nullable=False),
        sa.Column("event_time", sa.DateTime(timezone=True), nullable=False),
        sa.Column("payload_ciphertext", sa.LargeBinary(), nullable=False),
        sa.Column("payload_digest", sa.String(), nullable=False),
        sa.Column("key_id", sa.String(), nullable=False),
        sa.Column("hash_algorithm", sa.String(), nullable=False),
        sa.Column("record_hash", sa.String(), nullable=False),
        sa.CheckConstraint("seq >= 1", name=op.f("ck_chain_record_seq_positive")),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenant.id"],
            name=op.f("fk_chain_record_tenant_id"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_chain_record")),
        sa.UniqueConstraint("tenant_id", "seq", name=op.f("uq_chain_record_tenant_id_seq")),
    )
    op.create_index(op.f("ix_chain_record_tenant_id"), "chain_record", ["tenant_id"])

    op.create_table(
        "chain_head",
        sa.Column("tenant_id", sa.dialects.postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("seq", sa.Integer(), nullable=False),
        sa.Column("head_hash", sa.String(), nullable=False),
        sa.Column("last_event_time", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["tenant_id"], ["tenant.id"], name=op.f("fk_chain_head_tenant_id"), ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("tenant_id", name=op.f("pk_chain_head")),
    )

    # --- Row-level security -------------------------------------------------
    for table in ("chain_record", "chain_head"):
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
        op.execute(
            f"CREATE POLICY {table}_tenant_isolation ON {table} "
            f"USING ({TENANT_PREDICATE}) WITH CHECK ({TENANT_PREDICATE})"
        )

    # --- I13: the anchoring role reads chain heads, and nothing else --------
    # A role-scoped policy rather than a weakened tenant policy, so the
    # cross-tenant read is granted precisely where it is needed and nowhere
    # else. adw_anchor gets no access at all to chain_record.
    op.execute(
        "CREATE POLICY chain_head_anchor_read ON chain_head FOR SELECT TO adw_anchor USING (true)"
    )
    op.execute("GRANT SELECT ON chain_head TO adw_anchor")
    op.execute("GRANT SELECT ON chain_record, chain_head TO adw_auditor")

    # --- D14: append-only, and not modifiable through the application -------
    op.execute("REVOKE UPDATE, DELETE ON chain_record FROM adw_app")
    op.execute("""
        CREATE OR REPLACE FUNCTION adw_reject_chain_mutation() RETURNS trigger AS $$
        BEGIN
            RAISE EXCEPTION
                'audit chain records are append-only: % on %', TG_OP, TG_TABLE_NAME
                USING ERRCODE = 'restrict_violation';
        END;
        $$ LANGUAGE plpgsql;
    """)
    op.execute("""
        CREATE TRIGGER chain_record_append_only
        BEFORE UPDATE OR DELETE ON chain_record
        FOR EACH ROW EXECUTE FUNCTION adw_reject_chain_mutation()
    """)


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS chain_record_append_only ON chain_record")
    op.execute("DROP FUNCTION IF EXISTS adw_reject_chain_mutation()")
    op.drop_table("chain_head")
    op.drop_table("chain_record")
    op.execute(f"SELECT set_config('app.tenant_id', '{PLATFORM_TENANT_ID}', true)")
    op.execute(f"DELETE FROM tenant WHERE id = '{PLATFORM_TENANT_ID}'")
    op.execute("SELECT set_config('app.tenant_id', '', true)")

    for table, column in TIMESTAMP_COLUMNS:
        op.execute(f"ALTER TABLE {table} ALTER COLUMN {column} TYPE timestamp")
