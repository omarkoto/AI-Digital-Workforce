"""Execution record core: tenant, definitions, execution, task.

Revision ID: 0001_execution_record_core
Revises:
Create Date: Phase 1 Task 4

Every tenant-owned table created here enables *and* forces row-level security
and defines its policy in this same migration. Splitting those apart would leave
a window in which the table exists unprotected, and a migration that half-ran
would leave it that way permanently.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0001_execution_record_core"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TENANT_PREDICATE = "tenant_id = nullif(current_setting('app.tenant_id', true), '')::uuid"
TENANT_SELF_PREDICATE = "id = nullif(current_setting('app.tenant_id', true), '')::uuid"

TENANT_SCOPED = ("execution", "task", "task_skill_pin")
DEFINITION_TABLES = ("agent_definition", "agent_definition_version", "skill", "skill_version")
VERSION_TABLES = ("agent_definition_version", "skill_version")


def _protect(table: str, predicate: str) -> None:
    """Enable, force, and police row-level security on ``table``."""
    op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
    op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
    op.execute(
        f"CREATE POLICY {table}_tenant_isolation ON {table} "
        f"USING ({predicate}) WITH CHECK ({predicate})"
    )


def upgrade() -> None:
    op.create_table(
        "tenant",
        sa.Column("id", sa.dialects.postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("slug", sa.String(), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(),
            server_default=sa.text("transaction_timestamp()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_tenant")),
        sa.UniqueConstraint("slug", name=op.f("uq_tenant_slug")),
    )

    for table in ("agent_definition", "skill"):
        op.create_table(
            table,
            sa.Column("id", sa.dialects.postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column("key", sa.String(), nullable=False),
            sa.Column("name", sa.String(), nullable=False),
            sa.Column(
                "created_at",
                sa.DateTime(),
                server_default=sa.text("transaction_timestamp()"),
                nullable=False,
            ),
            sa.PrimaryKeyConstraint("id", name=op.f(f"pk_{table}")),
            sa.UniqueConstraint("key", name=op.f(f"uq_{table}_key")),
        )

    op.create_table(
        "agent_definition_version",
        sa.Column("id", sa.dialects.postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("agent_definition_id", sa.dialects.postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("version_no", sa.Integer(), nullable=False),
        sa.Column("instructions", sa.String(), nullable=False),
        sa.Column("is_deprecated", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column(
            "created_at",
            sa.DateTime(),
            server_default=sa.text("transaction_timestamp()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["agent_definition_id"],
            ["agent_definition.id"],
            name=op.f("fk_agent_definition_version_agent_definition_id"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_agent_definition_version")),
        sa.UniqueConstraint(
            "agent_definition_id",
            "version_no",
            name=op.f("uq_agent_definition_version_agent_definition_id_version_no"),
        ),
    )
    op.create_index(
        op.f("ix_agent_definition_version_agent_definition_id"),
        "agent_definition_version",
        ["agent_definition_id"],
    )

    op.create_table(
        "skill_version",
        sa.Column("id", sa.dialects.postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("skill_id", sa.dialects.postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("version_no", sa.Integer(), nullable=False),
        sa.Column("content", sa.String(), nullable=False),
        sa.Column("is_deprecated", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column(
            "created_at",
            sa.DateTime(),
            server_default=sa.text("transaction_timestamp()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["skill_id"], ["skill.id"], name=op.f("fk_skill_version_skill_id"), ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_skill_version")),
        sa.UniqueConstraint(
            "skill_id", "version_no", name=op.f("uq_skill_version_skill_id_version_no")
        ),
    )
    op.create_index(op.f("ix_skill_version_skill_id"), "skill_version", ["skill_id"])

    op.create_table(
        "execution",
        sa.Column("id", sa.dialects.postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("tenant_id", sa.dialects.postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("requester_identity", sa.String(), nullable=False),
        sa.Column("state", sa.String(length=32), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(),
            server_default=sa.text("transaction_timestamp()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(),
            server_default=sa.text("transaction_timestamp()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "state IN ('draft', 'planning', 'awaiting_confirmation', 'running', "
            "'awaiting_approval', 'completed', 'failed', 'blocked', 'cancelled', 'expired')",
            name=op.f("ck_execution_execution_state"),
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"], ["tenant.id"], name=op.f("fk_execution_tenant_id"), ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_execution")),
    )
    op.create_index(op.f("ix_execution_tenant_id"), "execution", ["tenant_id"])
    op.create_index(op.f("ix_execution_state"), "execution", ["state"])

    op.create_table(
        "task",
        sa.Column("id", sa.dialects.postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("tenant_id", sa.dialects.postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("execution_id", sa.dialects.postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column(
            "agent_definition_version_id",
            sa.dialects.postgresql.UUID(as_uuid=True),
            nullable=False,
        ),
        sa.Column("state", sa.String(length=32), nullable=False),
        sa.Column("attempt_no", sa.Integer(), nullable=False, server_default=sa.text("1")),
        sa.Column(
            "created_at",
            sa.DateTime(),
            server_default=sa.text("transaction_timestamp()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(),
            server_default=sa.text("transaction_timestamp()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "attempt_no BETWEEN 1 AND 3", name=op.f("ck_task_attempt_no_within_rework_limit")
        ),
        sa.CheckConstraint(
            "state IN ('planned', 'queued', 'running', 'producing', 'awaiting_gate', "
            "'passed', 'reworking', 'blocked', 'failed')",
            name=op.f("ck_task_task_state"),
        ),
        sa.ForeignKeyConstraint(
            ["agent_definition_version_id"],
            ["agent_definition_version.id"],
            name=op.f("fk_task_agent_definition_version_id"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["execution_id"],
            ["execution.id"],
            name=op.f("fk_task_execution_id"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"], ["tenant.id"], name=op.f("fk_task_tenant_id"), ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_task")),
        sa.UniqueConstraint("execution_id", "sequence", name=op.f("uq_task_execution_id_sequence")),
    )
    op.create_index(op.f("ix_task_tenant_id"), "task", ["tenant_id"])
    op.create_index(op.f("ix_task_execution_id"), "task", ["execution_id"])
    op.create_index(op.f("ix_task_state"), "task", ["state"])
    op.create_index(
        op.f("ix_task_agent_definition_version_id"), "task", ["agent_definition_version_id"]
    )

    op.create_table(
        "task_skill_pin",
        sa.Column("id", sa.dialects.postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("tenant_id", sa.dialects.postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("task_id", sa.dialects.postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("skill_version_id", sa.dialects.postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(),
            server_default=sa.text("transaction_timestamp()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["skill_version_id"],
            ["skill_version.id"],
            name=op.f("fk_task_skill_pin_skill_version_id"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["task_id"], ["task.id"], name=op.f("fk_task_skill_pin_task_id"), ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenant.id"],
            name=op.f("fk_task_skill_pin_tenant_id"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_task_skill_pin")),
        sa.UniqueConstraint(
            "task_id", "skill_version_id", name=op.f("uq_task_skill_pin_task_id_skill_version_id")
        ),
    )
    op.create_index(op.f("ix_task_skill_pin_tenant_id"), "task_skill_pin", ["tenant_id"])
    op.create_index(op.f("ix_task_skill_pin_task_id"), "task_skill_pin", ["task_id"])
    op.create_index(
        op.f("ix_task_skill_pin_skill_version_id"), "task_skill_pin", ["skill_version_id"]
    )

    # --- Row-level security -------------------------------------------------
    _protect("tenant", TENANT_SELF_PREDICATE)
    for table in TENANT_SCOPED:
        _protect(table, TENANT_PREDICATE)

    # --- Definition tables: platform-curated, read-only at runtime (D30) -----
    for table in DEFINITION_TABLES:
        op.execute(f"REVOKE INSERT, UPDATE, DELETE ON {table} FROM adw_app")
        op.execute(f"GRANT SELECT ON {table} TO adw_app")

    # --- Version immutability (D9) ------------------------------------------
    # A version an execution pinned must never change, or the record could no
    # longer answer what the rules were at the time. Enforced by trigger as well
    # as by grant, because a grant protects against the runtime role only.
    op.execute("""
        CREATE OR REPLACE FUNCTION adw_reject_version_mutation() RETURNS trigger AS $$
        BEGIN
            RAISE EXCEPTION
                'definition versions are immutable: % on %', TG_OP, TG_TABLE_NAME
                USING ERRCODE = 'restrict_violation';
        END;
        $$ LANGUAGE plpgsql;
    """)
    for table in VERSION_TABLES:
        op.execute(f"""
            CREATE TRIGGER {table}_immutable
            BEFORE UPDATE OR DELETE ON {table}
            FOR EACH ROW EXECUTE FUNCTION adw_reject_version_mutation()
        """)


def downgrade() -> None:
    for table in VERSION_TABLES:
        op.execute(f"DROP TRIGGER IF EXISTS {table}_immutable ON {table}")
    op.execute("DROP FUNCTION IF EXISTS adw_reject_version_mutation()")

    op.drop_table("task_skill_pin")
    op.drop_table("task")
    op.drop_table("execution")
    op.drop_table("skill_version")
    op.drop_table("agent_definition_version")
    op.drop_table("skill")
    op.drop_table("agent_definition")
    op.drop_table("tenant")
