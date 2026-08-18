"""Pre-declared tool permission grants.

Revision ID: 0011_tool_grants
Revises: 0010_tool_registry
Create Date: Phase 3 Task 2

Additive, and tenant-scoped like every other runtime table.

The trigger installed here is the mechanical form of B3: **a grant's
authorization can never be widened after it is declared.** Any update touching
the task, the tool version, the scopes, or the expiry is rejected. Revocation is
allowed through, and only in one direction, because it narrows.

That is not the qualified immutability rejected for definition versions in
migration 0009. A definition version claims to be byte-immutable and any
exemption would weaken that claim. A grant never claimed it: it is a runtime
record with a decision applied later, like ``approval_item``, and the trigger is
what makes the *authorization* half of it immutable in a row that is not.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0011_tool_grants"
down_revision: str | None = "0010_tool_registry"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TENANT_PREDICATE = "tenant_id = nullif(current_setting('app.tenant_id', true), '')::uuid"


def upgrade() -> None:
    op.create_table(
        "tool_grant",
        sa.Column("id", sa.dialects.postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("tenant_id", sa.dialects.postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("task_id", sa.dialects.postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("tool_definition_id", sa.dialects.postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "tool_definition_version_id",
            sa.dialects.postgresql.UUID(as_uuid=True),
            nullable=False,
        ),
        sa.Column("scopes_json", sa.String(), nullable=False, server_default=sa.text("'[]'")),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_by_identity", sa.String(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("transaction_timestamp()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "(revoked_at IS NULL) = (revoked_by_identity IS NULL)",
            name=op.f("ck_tool_grant_a_revocation_names_who_made_it"),
        ),
        sa.ForeignKeyConstraint(
            ["task_id"], ["task.id"], name=op.f("fk_tool_grant_task_id"), ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"], ["tenant.id"], name=op.f("fk_tool_grant_tenant_id"), ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["tool_definition_id"],
            ["tool_definition.id"],
            name=op.f("fk_tool_grant_tool_definition_id"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["tool_definition_version_id"],
            ["tool_definition_version.id"],
            name=op.f("fk_tool_grant_tool_definition_version_id"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_tool_grant")),
        sa.UniqueConstraint(
            "task_id",
            "tool_definition_id",
            name=op.f("uq_tool_grant_one_version_per_tool_per_task"),
        ),
    )
    op.create_index(op.f("ix_tool_grant_tenant_id"), "tool_grant", ["tenant_id"])
    op.create_index(op.f("ix_tool_grant_task_id"), "tool_grant", ["task_id"])
    op.create_index(op.f("ix_tool_grant_tool_definition_id"), "tool_grant", ["tool_definition_id"])
    op.create_index(
        op.f("ix_tool_grant_tool_definition_version_id"),
        "tool_grant",
        ["tool_definition_version_id"],
    )

    op.execute("ALTER TABLE tool_grant ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE tool_grant FORCE ROW LEVEL SECURITY")
    op.execute(
        f"CREATE POLICY tool_grant_tenant_isolation ON tool_grant "
        f"USING ({TENANT_PREDICATE}) WITH CHECK ({TENANT_PREDICATE})"
    )

    # B3, mechanically: a declared permission can never be widened, and a grant
    # can never be deleted to hide that it existed.
    op.execute("REVOKE DELETE ON tool_grant FROM adw_app")
    op.execute("""
        CREATE OR REPLACE FUNCTION adw_reject_grant_widening() RETURNS trigger AS $$
        BEGIN
            IF TG_OP = 'DELETE' THEN
                RAISE EXCEPTION 'a tool grant cannot be deleted; revoke it instead'
                    USING ERRCODE = 'restrict_violation';
            END IF;
            IF NEW.task_id IS DISTINCT FROM OLD.task_id
               OR NEW.tenant_id IS DISTINCT FROM OLD.tenant_id
               OR NEW.tool_definition_id IS DISTINCT FROM OLD.tool_definition_id
               OR NEW.tool_definition_version_id IS DISTINCT FROM OLD.tool_definition_version_id
               OR NEW.scopes_json IS DISTINCT FROM OLD.scopes_json
               OR NEW.expires_at IS DISTINCT FROM OLD.expires_at THEN
                RAISE EXCEPTION
                    'a tool grant is pre-declared and cannot be widened after creation'
                    USING ERRCODE = 'restrict_violation';
            END IF;
            IF OLD.revoked_at IS NOT NULL AND NEW.revoked_at IS NULL THEN
                RAISE EXCEPTION 'a revoked tool grant cannot be un-revoked'
                    USING ERRCODE = 'restrict_violation';
            END IF;
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
    """)
    op.execute("""
        CREATE TRIGGER tool_grant_authorization_immutable
        BEFORE UPDATE OR DELETE ON tool_grant
        FOR EACH ROW EXECUTE FUNCTION adw_reject_grant_widening()
    """)

    op.execute("GRANT SELECT ON tool_grant TO adw_auditor")


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS tool_grant_authorization_immutable ON tool_grant")
    op.execute("DROP FUNCTION IF EXISTS adw_reject_grant_widening()")
    op.drop_table("tool_grant")
