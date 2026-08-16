"""Action and evidence.

Revision ID: 0004_action_evidence
Revises: 0003_anchor_chain
Create Date: Phase 1 Task 7

The trigger installed here is the sharpest rule in the schema: an action cannot
reach ``succeeded`` without linked evidence. `CLAUDE.md` §3 forbids claiming an
action completed without execution evidence, and a rule enforced only in a
service is a rule any future caller can route around.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0004_action_evidence"
down_revision: str | None = "0003_anchor_chain"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TENANT_PREDICATE = "tenant_id = nullif(current_setting('app.tenant_id', true), '')::uuid"

ACTION_STATES = "'planned', 'attempted', 'executed', 'succeeded', 'failed', 'unverified'"


def upgrade() -> None:
    op.create_table(
        "action",
        sa.Column("id", sa.dialects.postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("tenant_id", sa.dialects.postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("task_id", sa.dialects.postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("tool_name", sa.String(), nullable=False),
        sa.Column("state", sa.String(length=32), nullable=False),
        sa.Column("failure_detail", sa.String(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("transaction_timestamp()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("transaction_timestamp()"),
            nullable=False,
        ),
        sa.CheckConstraint(f"state IN ({ACTION_STATES})", name=op.f("ck_action_action_state")),
        sa.ForeignKeyConstraint(
            ["task_id"], ["task.id"], name=op.f("fk_action_task_id"), ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"], ["tenant.id"], name=op.f("fk_action_tenant_id"), ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_action")),
        sa.UniqueConstraint("task_id", "sequence", name=op.f("uq_action_task_id_sequence")),
    )
    op.create_index(op.f("ix_action_tenant_id"), "action", ["tenant_id"])
    op.create_index(op.f("ix_action_task_id"), "action", ["task_id"])
    op.create_index(op.f("ix_action_state"), "action", ["state"])

    op.create_table(
        "evidence",
        sa.Column("id", sa.dialects.postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("tenant_id", sa.dialects.postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("action_id", sa.dialects.postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("gate_decision_id", sa.dialects.postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("kind", sa.String(), nullable=False),
        sa.Column("inline_ciphertext", sa.LargeBinary(), nullable=True),
        sa.Column("blob_key", sa.String(), nullable=True),
        sa.Column("key_id", sa.String(), nullable=False),
        sa.Column("content_digest", sa.String(), nullable=False),
        sa.Column("size_bytes", sa.Integer(), nullable=False),
        sa.Column("redaction_count", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("recorded_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("transaction_timestamp()"),
            nullable=False,
        ),
        # Exactly one subject, enforced from the first row. The foreign key to
        # gate_decision arrives in Task 9; the invariant does not wait for it.
        sa.CheckConstraint(
            "num_nonnulls(action_id, gate_decision_id) = 1",
            name=op.f("ck_evidence_attaches_to_exactly_one_subject"),
        ),
        sa.CheckConstraint(
            "num_nonnulls(inline_ciphertext, blob_key) = 1",
            name=op.f("ck_evidence_stored_inline_or_as_blob"),
        ),
        sa.CheckConstraint("size_bytes >= 0", name=op.f("ck_evidence_size_not_negative")),
        sa.CheckConstraint(
            "redaction_count >= 0", name=op.f("ck_evidence_redaction_count_not_negative")
        ),
        sa.ForeignKeyConstraint(
            ["action_id"], ["action.id"], name=op.f("fk_evidence_action_id"), ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"], ["tenant.id"], name=op.f("fk_evidence_tenant_id"), ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_evidence")),
    )
    op.create_index(op.f("ix_evidence_tenant_id"), "evidence", ["tenant_id"])
    op.create_index(op.f("ix_evidence_action_id"), "evidence", ["action_id"])
    op.create_index(op.f("ix_evidence_gate_decision_id"), "evidence", ["gate_decision_id"])

    for table in ("action", "evidence"):
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
        op.execute(
            f"CREATE POLICY {table}_tenant_isolation ON {table} "
            f"USING ({TENANT_PREDICATE}) WITH CHECK ({TENANT_PREDICATE})"
        )

    # --- I10 / G15: no success without evidence -----------------------------
    # The platform's central claim, enforced where it cannot be routed around.
    op.execute("""
        CREATE OR REPLACE FUNCTION adw_require_evidence_for_success() RETURNS trigger AS $$
        BEGIN
            IF NEW.state = 'succeeded'
               AND NOT EXISTS (SELECT 1 FROM evidence WHERE action_id = NEW.id) THEN
                RAISE EXCEPTION
                    'action % cannot reach succeeded without linked evidence', NEW.id
                    USING ERRCODE = 'restrict_violation';
            END IF;
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
    """)
    op.execute("""
        CREATE TRIGGER action_requires_evidence_for_success
        BEFORE INSERT OR UPDATE ON action
        FOR EACH ROW EXECUTE FUNCTION adw_require_evidence_for_success()
    """)

    # --- Evidence is immutable (D12, CLAUDE.md §3) --------------------------
    op.execute("REVOKE UPDATE, DELETE ON evidence FROM adw_app")
    op.execute("""
        CREATE OR REPLACE FUNCTION adw_reject_evidence_mutation() RETURNS trigger AS $$
        BEGIN
            RAISE EXCEPTION
                'evidence is immutable: % on %', TG_OP, TG_TABLE_NAME
                USING ERRCODE = 'restrict_violation';
        END;
        $$ LANGUAGE plpgsql;
    """)
    op.execute("""
        CREATE TRIGGER evidence_immutable
        BEFORE UPDATE OR DELETE ON evidence
        FOR EACH ROW EXECUTE FUNCTION adw_reject_evidence_mutation()
    """)

    op.execute("GRANT SELECT ON action, evidence TO adw_auditor")


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS evidence_immutable ON evidence")
    op.execute("DROP FUNCTION IF EXISTS adw_reject_evidence_mutation()")
    op.execute("DROP TRIGGER IF EXISTS action_requires_evidence_for_success ON action")
    op.execute("DROP FUNCTION IF EXISTS adw_require_evidence_for_success()")
    op.drop_table("evidence")
    op.drop_table("action")
