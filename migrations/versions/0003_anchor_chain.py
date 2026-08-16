"""Anchor chain: anchor_record and anchor_head.

Revision ID: 0003_anchor_chain
Revises: 0002_audit_chain
Create Date: Phase 1 Task 6

These tables are platform-scoped (I13) and deliberately **not tenant-readable**.
The runtime role receives no access at all — the default privileges granted in
Task 3 are revoked explicitly, because a default grant would otherwise hand
adw_app exactly the cross-tenant metadata D20 refused to expose.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0003_anchor_chain"
down_revision: str | None = "0002_audit_chain"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "anchor_record",
        sa.Column("id", sa.dialects.postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("anchor_seq", sa.Integer(), nullable=False),
        sa.Column("prev_anchor_hash", sa.String(), nullable=True),
        sa.Column("tenant_id", sa.dialects.postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("tenant_seq", sa.Integer(), nullable=False),
        sa.Column("tenant_head_hash", sa.String(), nullable=False),
        sa.Column("anchor_time", sa.DateTime(timezone=True), nullable=False),
        sa.Column("hash_algorithm", sa.String(), nullable=False),
        sa.Column("anchor_hash", sa.String(), nullable=False),
        sa.CheckConstraint("anchor_seq >= 1", name=op.f("ck_anchor_record_anchor_seq_positive")),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenant.id"],
            name=op.f("fk_anchor_record_tenant_id"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_anchor_record")),
        sa.UniqueConstraint("anchor_seq", name=op.f("uq_anchor_record_anchor_seq")),
        sa.UniqueConstraint(
            "tenant_id", "tenant_seq", name=op.f("uq_anchor_record_tenant_id_tenant_seq")
        ),
    )
    op.create_index(op.f("ix_anchor_record_tenant_id"), "anchor_record", ["tenant_id"])

    op.create_table(
        "anchor_head",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("anchor_seq", sa.Integer(), nullable=False),
        sa.Column("head_hash", sa.String(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("id = 1", name=op.f("ck_anchor_head_single_row")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_anchor_head")),
    )

    # --- I13: not tenant-readable -------------------------------------------
    # Task 3 granted adw_app default privileges on future tables owned by
    # adw_owner. Revoking here is not belt-and-braces: without it the runtime
    # role could read which tenants exist and how active each one is, which is
    # precisely the metadata leak that ruled out a single global chain in D20.
    op.execute("REVOKE ALL ON anchor_record, anchor_head FROM adw_app")

    # The anchoring job writes anchors and advances the head. It still cannot
    # read chain_record, and holds no key.
    op.execute("GRANT SELECT, INSERT ON anchor_record TO adw_anchor")
    op.execute("GRANT SELECT, INSERT, UPDATE ON anchor_head TO adw_anchor")

    # External audit reads both, and writes neither.
    op.execute("GRANT SELECT ON anchor_record, anchor_head TO adw_auditor")

    # --- Append-only, like the chain it anchors (D14) ------------------------
    op.execute("""
        CREATE OR REPLACE FUNCTION adw_reject_anchor_mutation() RETURNS trigger AS $$
        BEGIN
            RAISE EXCEPTION
                'anchor records are append-only: % on %', TG_OP, TG_TABLE_NAME
                USING ERRCODE = 'restrict_violation';
        END;
        $$ LANGUAGE plpgsql;
    """)
    op.execute("""
        CREATE TRIGGER anchor_record_append_only
        BEFORE UPDATE OR DELETE ON anchor_record
        FOR EACH ROW EXECUTE FUNCTION adw_reject_anchor_mutation()
    """)


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS anchor_record_append_only ON anchor_record")
    op.execute("DROP FUNCTION IF EXISTS adw_reject_anchor_mutation()")
    op.drop_table("anchor_head")
    op.drop_table("anchor_record")
