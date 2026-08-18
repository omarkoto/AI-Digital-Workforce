"""Cost accounting and execution budgets.

Revision ID: 0008_cost_accounting
Revises: 0007_dispatch_queue
Create Date: Phase 2 Task 6

Additive only. No Phase 1 table, policy, trigger, or grant is altered — the two
tables added here are new, tenant-scoped, and carry counts rather than content.

``execution_budget`` is mutable by design, unlike most of this schema: raising a
ceiling is the human authorization `PRODUCT.md` §25 requires, and it is audited
by the service that performs it. ``action_cost`` is not: a spend figure that can
be edited after the fact is not an accounting record.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0008_cost_accounting"
down_revision: str | None = "0007_dispatch_queue"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TENANT_PREDICATE = "tenant_id = nullif(current_setting('app.tenant_id', true), '')::uuid"


def upgrade() -> None:
    op.create_table(
        "action_cost",
        sa.Column("id", sa.dialects.postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("tenant_id", sa.dialects.postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("action_id", sa.dialects.postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("execution_id", sa.dialects.postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("provider", sa.String(), nullable=False),
        sa.Column("model", sa.String(), nullable=False),
        sa.Column("prompt_tokens", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("completion_tokens", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("transaction_timestamp()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "prompt_tokens >= 0", name=op.f("ck_action_cost_prompt_tokens_not_negative")
        ),
        sa.CheckConstraint(
            "completion_tokens >= 0", name=op.f("ck_action_cost_completion_tokens_not_negative")
        ),
        sa.ForeignKeyConstraint(
            ["action_id"], ["action.id"], name=op.f("fk_action_cost_action_id"), ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["execution_id"],
            ["execution.id"],
            name=op.f("fk_action_cost_execution_id"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"], ["tenant.id"], name=op.f("fk_action_cost_tenant_id"), ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_action_cost")),
        sa.UniqueConstraint("action_id", name=op.f("uq_action_cost_one_cost_row_per_action")),
    )
    op.create_index(op.f("ix_action_cost_tenant_id"), "action_cost", ["tenant_id"])
    op.create_index(op.f("ix_action_cost_action_id"), "action_cost", ["action_id"])
    op.create_index(op.f("ix_action_cost_execution_id"), "action_cost", ["execution_id"])

    op.create_table(
        "execution_budget",
        sa.Column("id", sa.dialects.postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("tenant_id", sa.dialects.postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("execution_id", sa.dialects.postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("max_total_tokens", sa.Integer(), nullable=False),
        sa.Column("warn_at_ratio", sa.Float(), nullable=False, server_default=sa.text("0.8")),
        sa.Column("authorized_by_identity", sa.String(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("transaction_timestamp()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "max_total_tokens > 0", name=op.f("ck_execution_budget_budget_is_positive")
        ),
        sa.CheckConstraint(
            "warn_at_ratio > 0 AND warn_at_ratio < 1",
            name=op.f("ck_execution_budget_warning_precedes_exhaustion"),
        ),
        sa.ForeignKeyConstraint(
            ["execution_id"],
            ["execution.id"],
            name=op.f("fk_execution_budget_execution_id"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenant.id"],
            name=op.f("fk_execution_budget_tenant_id"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_execution_budget")),
        sa.UniqueConstraint(
            "execution_id", name=op.f("uq_execution_budget_one_budget_per_execution")
        ),
    )
    op.create_index(op.f("ix_execution_budget_tenant_id"), "execution_budget", ["tenant_id"])
    op.create_index(op.f("ix_execution_budget_execution_id"), "execution_budget", ["execution_id"])

    for table in ("action_cost", "execution_budget"):
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
        op.execute(
            f"CREATE POLICY {table}_tenant_isolation ON {table} "
            f"USING ({TENANT_PREDICATE}) WITH CHECK ({TENANT_PREDICATE})"
        )

    # A spend figure that can be edited after the fact is not an accounting
    # record. The budget stays mutable, because raising it is the authorization.
    op.execute("REVOKE UPDATE, DELETE ON action_cost FROM adw_app")
    op.execute("""
        CREATE OR REPLACE FUNCTION adw_reject_cost_mutation() RETURNS trigger AS $$
        BEGIN
            RAISE EXCEPTION
                'recorded cost is immutable: % on %', TG_OP, TG_TABLE_NAME
                USING ERRCODE = 'restrict_violation';
        END;
        $$ LANGUAGE plpgsql;
    """)
    op.execute("""
        CREATE TRIGGER action_cost_immutable
        BEFORE UPDATE OR DELETE ON action_cost
        FOR EACH ROW EXECUTE FUNCTION adw_reject_cost_mutation()
    """)

    op.execute("GRANT SELECT ON action_cost, execution_budget TO adw_auditor")


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS action_cost_immutable ON action_cost")
    op.execute("DROP FUNCTION IF EXISTS adw_reject_cost_mutation()")
    op.drop_table("execution_budget")
    op.drop_table("action_cost")
