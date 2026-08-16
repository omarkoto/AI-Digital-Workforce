"""Artifact and artifact definition.

Revision ID: 0005_artifact
Revises: 0004_action_evidence
Create Date: Phase 1 Task 8

Artifact versions are immutable (I6). Enforced by revoked grants *and* a
trigger, because a grant protects against the runtime role only, and a version a
Control Gate approved must be the same bytes anyone retrieves afterwards — or
the approval means nothing.

Also adds the deferred foreign key from evidence to gate_decision? No: gate
decisions arrive in Task 9. Evidence's exclusivity invariant already holds.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0005_artifact"
down_revision: str | None = "0004_action_evidence"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TENANT_PREDICATE = "tenant_id = nullif(current_setting('app.tenant_id', true), '')::uuid"

DEFINITION_TABLES = ("artifact_definition", "artifact_definition_version")
TENANT_SCOPED = ("artifact", "artifact_version")


def upgrade() -> None:
    # --- Platform-curated definitions (D30) ---------------------------------
    op.create_table(
        "artifact_definition",
        sa.Column("id", sa.dialects.postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("key", sa.String(), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("transaction_timestamp()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_artifact_definition")),
        sa.UniqueConstraint("key", name=op.f("uq_artifact_definition_key")),
    )

    op.create_table(
        "artifact_definition_version",
        sa.Column("id", sa.dialects.postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "artifact_definition_id", sa.dialects.postgresql.UUID(as_uuid=True), nullable=False
        ),
        sa.Column("version_no", sa.Integer(), nullable=False),
        sa.Column("content_type", sa.String(), nullable=False),
        sa.Column("schema_json", sa.String(), nullable=False),
        sa.Column("is_deprecated", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("transaction_timestamp()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["artifact_definition_id"],
            ["artifact_definition.id"],
            name=op.f("fk_artifact_definition_version_artifact_definition_id"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_artifact_definition_version")),
        sa.UniqueConstraint(
            "artifact_definition_id",
            "version_no",
            name=op.f("uq_artifact_definition_version_artifact_definition_id_version_no"),
        ),
    )
    op.create_index(
        op.f("ix_artifact_definition_version_artifact_definition_id"),
        "artifact_definition_version",
        ["artifact_definition_id"],
    )

    # --- Tenant-scoped artifacts --------------------------------------------
    op.create_table(
        "artifact",
        sa.Column("id", sa.dialects.postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("tenant_id", sa.dialects.postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("execution_id", sa.dialects.postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "artifact_definition_id", sa.dialects.postgresql.UUID(as_uuid=True), nullable=False
        ),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("transaction_timestamp()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["artifact_definition_id"],
            ["artifact_definition.id"],
            name=op.f("fk_artifact_artifact_definition_id"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["execution_id"],
            ["execution.id"],
            name=op.f("fk_artifact_execution_id"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"], ["tenant.id"], name=op.f("fk_artifact_tenant_id"), ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_artifact")),
        sa.UniqueConstraint("execution_id", "name", name=op.f("uq_artifact_execution_id_name")),
    )
    op.create_index(op.f("ix_artifact_tenant_id"), "artifact", ["tenant_id"])
    op.create_index(op.f("ix_artifact_execution_id"), "artifact", ["execution_id"])
    op.create_index(
        op.f("ix_artifact_artifact_definition_id"), "artifact", ["artifact_definition_id"]
    )

    op.create_table(
        "artifact_version",
        sa.Column("id", sa.dialects.postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("tenant_id", sa.dialects.postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("artifact_id", sa.dialects.postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("version_no", sa.Integer(), nullable=False),
        sa.Column("producing_task_id", sa.dialects.postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("producing_agent_identity", sa.String(), nullable=False),
        sa.Column(
            "artifact_definition_version_id",
            sa.dialects.postgresql.UUID(as_uuid=True),
            nullable=False,
        ),
        sa.Column("blob_key", sa.String(), nullable=False),
        sa.Column("key_id", sa.String(), nullable=False),
        sa.Column("content_digest", sa.String(), nullable=False),
        sa.Column("size_bytes", sa.Integer(), nullable=False),
        sa.Column("content_type", sa.String(), nullable=False),
        sa.Column("redaction_count", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("transaction_timestamp()"),
            nullable=False,
        ),
        sa.CheckConstraint("version_no >= 1", name=op.f("ck_artifact_version_version_no_positive")),
        sa.CheckConstraint("size_bytes >= 0", name=op.f("ck_artifact_version_size_not_negative")),
        sa.CheckConstraint(
            "redaction_count >= 0", name=op.f("ck_artifact_version_redaction_count_not_negative")
        ),
        sa.ForeignKeyConstraint(
            ["artifact_definition_version_id"],
            ["artifact_definition_version.id"],
            name=op.f("fk_artifact_version_artifact_definition_version_id"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["artifact_id"],
            ["artifact.id"],
            name=op.f("fk_artifact_version_artifact_id"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["producing_task_id"],
            ["task.id"],
            name=op.f("fk_artifact_version_producing_task_id"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenant.id"],
            name=op.f("fk_artifact_version_tenant_id"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_artifact_version")),
        sa.UniqueConstraint(
            "artifact_id", "version_no", name=op.f("uq_artifact_version_artifact_id_version_no")
        ),
    )
    op.create_index(op.f("ix_artifact_version_tenant_id"), "artifact_version", ["tenant_id"])
    op.create_index(op.f("ix_artifact_version_artifact_id"), "artifact_version", ["artifact_id"])
    op.create_index(
        op.f("ix_artifact_version_producing_task_id"), "artifact_version", ["producing_task_id"]
    )
    op.create_index(
        op.f("ix_artifact_version_artifact_definition_version_id"),
        "artifact_version",
        ["artifact_definition_version_id"],
    )

    for table in TENANT_SCOPED:
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
        op.execute(
            f"CREATE POLICY {table}_tenant_isolation ON {table} "
            f"USING ({TENANT_PREDICATE}) WITH CHECK ({TENANT_PREDICATE})"
        )

    # --- Definitions are read-only at runtime (D30) -------------------------
    for table in DEFINITION_TABLES:
        op.execute(f"REVOKE INSERT, UPDATE, DELETE ON {table} FROM adw_app")
        op.execute(f"GRANT SELECT ON {table} TO adw_app")

    # Definition versions are immutable, like every other pinned definition.
    # Reuses the function installed by migration 0001.
    op.execute("""
        CREATE TRIGGER artifact_definition_version_immutable
        BEFORE UPDATE OR DELETE ON artifact_definition_version
        FOR EACH ROW EXECUTE FUNCTION adw_reject_version_mutation()
    """)

    # --- I6: artifact versions are immutable --------------------------------
    op.execute("REVOKE UPDATE, DELETE ON artifact_version FROM adw_app")
    op.execute("""
        CREATE OR REPLACE FUNCTION adw_reject_artifact_version_mutation() RETURNS trigger AS $$
        BEGIN
            RAISE EXCEPTION
                'artifact versions are immutable: % on %', TG_OP, TG_TABLE_NAME
                USING ERRCODE = 'restrict_violation';
        END;
        $$ LANGUAGE plpgsql;
    """)
    op.execute("""
        CREATE TRIGGER artifact_version_immutable
        BEFORE UPDATE OR DELETE ON artifact_version
        FOR EACH ROW EXECUTE FUNCTION adw_reject_artifact_version_mutation()
    """)

    op.execute(
        "GRANT SELECT ON artifact, artifact_version, artifact_definition, "
        "artifact_definition_version TO adw_auditor"
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS artifact_version_immutable ON artifact_version")
    op.execute("DROP FUNCTION IF EXISTS adw_reject_artifact_version_mutation()")
    op.execute(
        "DROP TRIGGER IF EXISTS artifact_definition_version_immutable "
        "ON artifact_definition_version"
    )
    op.drop_table("artifact_version")
    op.drop_table("artifact")
    op.drop_table("artifact_definition_version")
    op.drop_table("artifact_definition")
