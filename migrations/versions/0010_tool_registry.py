"""Tool registry: versioned tool descriptors.

Revision ID: 0010_tool_registry
Revises: 0009_definition_deprecation
Create Date: Phase 3 Task 1

Additive. The two new tables follow the definition pattern exactly — platform-
curated (D30), immutable versions (D9), SELECT-only for ``adw_app`` — because a
tool's timeout, limits and required scopes are precisely the sort of thing an
execution must be able to prove after the fact, and only a pinned immutable
version can answer "what were the limits at the time?".

``definition_deprecation`` gains a fifth link column so a retired tool version
uses the same append-only record as every other kind. Its exclusivity constraint
is dropped and recreated to cover it: a new sort of definition should have to say
so in the schema rather than arrive as an unchecked string.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0010_tool_registry"
down_revision: str | None = "0009_definition_deprecation"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

EXCLUSIVITY = "ck_definition_deprecation_names_exactly_one_version"
"""Wrapped in ``op.f()`` at every use. The naming convention would otherwise
prefix this already-conventionalized name a second time, producing
``ck_definition_deprecation_ck_definition_deprecation_...`` and a constraint that
does not exist."""

SUBJECTS_BEFORE = (
    "agent_definition_version_id",
    "skill_version_id",
    "artifact_definition_version_id",
    "gate_definition_version_id",
)
SUBJECTS_AFTER = (*SUBJECTS_BEFORE, "tool_definition_version_id")


def upgrade() -> None:
    op.create_table(
        "tool_definition",
        sa.Column("id", sa.dialects.postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("key", sa.String(), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("description", sa.String(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("transaction_timestamp()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_tool_definition")),
        sa.UniqueConstraint("key", name=op.f("uq_tool_definition_key")),
    )

    op.create_table(
        "tool_definition_version",
        sa.Column("id", sa.dialects.postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("tool_definition_id", sa.dialects.postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("version_no", sa.Integer(), nullable=False),
        sa.Column("input_schema_json", sa.String(), nullable=False),
        sa.Column("output_schema_json", sa.String(), nullable=False),
        sa.Column("timeout_seconds", sa.Integer(), nullable=False),
        sa.Column("max_output_bytes", sa.Integer(), nullable=False),
        sa.Column(
            "required_scopes_json", sa.String(), nullable=False, server_default=sa.text("'[]'")
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("transaction_timestamp()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "timeout_seconds > 0", name=op.f("ck_tool_definition_version_timeout_is_positive")
        ),
        sa.CheckConstraint(
            "max_output_bytes > 0",
            name=op.f("ck_tool_definition_version_output_limit_is_positive"),
        ),
        sa.ForeignKeyConstraint(
            ["tool_definition_id"],
            ["tool_definition.id"],
            name=op.f("fk_tool_definition_version_tool_definition_id"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_tool_definition_version")),
        sa.UniqueConstraint(
            "tool_definition_id",
            "version_no",
            name=op.f("uq_tool_definition_version_tool_definition_id_version_no"),
        ),
    )
    op.create_index(
        op.f("ix_tool_definition_version_tool_definition_id"),
        "tool_definition_version",
        ["tool_definition_id"],
    )

    # Platform-curated: readable by every tenant, writable by no tenant (D5/D30).
    for table in ("tool_definition", "tool_definition_version"):
        op.execute(f"REVOKE INSERT, UPDATE, DELETE ON {table} FROM adw_app")
        op.execute(f"GRANT SELECT ON {table} TO adw_app")
        op.execute(f"GRANT SELECT ON {table} TO adw_auditor")

    # The same unconditional immutability every other version table carries. The
    # function was created in migration 0001 and is reused, not redefined.
    op.execute("""
        CREATE TRIGGER tool_definition_version_immutable
        BEFORE UPDATE OR DELETE ON tool_definition_version
        FOR EACH ROW EXECUTE FUNCTION adw_reject_version_mutation()
    """)

    # A retired tool version uses the same append-only record as every other kind.
    op.add_column(
        "definition_deprecation",
        sa.Column("tool_definition_version_id", sa.dialects.postgresql.UUID(as_uuid=True)),
    )
    op.create_foreign_key(
        op.f("fk_definition_deprecation_tool_definition_version_id"),
        "definition_deprecation",
        "tool_definition_version",
        ["tool_definition_version_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_unique_constraint(
        op.f("uq_definition_deprecation_tool_definition_version_id"),
        "definition_deprecation",
        ["tool_definition_version_id"],
    )
    op.drop_constraint(op.f(EXCLUSIVITY), "definition_deprecation", type_="check")
    op.create_check_constraint(
        op.f(EXCLUSIVITY),
        "definition_deprecation",
        f"num_nonnulls({', '.join(SUBJECTS_AFTER)}) = 1",
    )


def downgrade() -> None:
    # A tool deprecation cannot survive the removal of tool versions, and leaving
    # the row would leave it naming nothing — which the exclusivity constraint
    # correctly refuses. The trigger has to stand down to remove it, which is
    # itself a reminder that this record is append-only in normal operation.
    op.execute(
        "ALTER TABLE definition_deprecation DISABLE TRIGGER definition_deprecation_append_only"
    )
    op.execute("DELETE FROM definition_deprecation WHERE tool_definition_version_id IS NOT NULL")
    op.execute(
        "ALTER TABLE definition_deprecation ENABLE TRIGGER definition_deprecation_append_only"
    )

    op.drop_constraint(op.f(EXCLUSIVITY), "definition_deprecation", type_="check")
    op.create_check_constraint(
        op.f(EXCLUSIVITY),
        "definition_deprecation",
        f"num_nonnulls({', '.join(SUBJECTS_BEFORE)}) = 1",
    )
    op.drop_constraint(
        op.f("uq_definition_deprecation_tool_definition_version_id"),
        "definition_deprecation",
        type_="unique",
    )
    op.drop_constraint(
        op.f("fk_definition_deprecation_tool_definition_version_id"),
        "definition_deprecation",
        type_="foreignkey",
    )
    op.drop_column("definition_deprecation", "tool_definition_version_id")

    op.execute(
        "DROP TRIGGER IF EXISTS tool_definition_version_immutable ON tool_definition_version"
    )
    op.drop_table("tool_definition_version")
    op.drop_table("tool_definition")
