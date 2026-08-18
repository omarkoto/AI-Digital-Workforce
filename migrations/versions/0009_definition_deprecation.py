"""Deprecation as an append-only record, and definition versions fully immutable.

Revision ID: 0009_definition_deprecation
Revises: 0008_cost_accounting
Create Date: Phase 2, D9 follow-up

D9 says a pinned version "can never be mutated or hard-deleted; only
deprecated" — and the immutability trigger from migration 0001 blocked the one
mutation D9 permits, for every role including the owner. So ``is_deprecated``
was unsettable after insert: dead state that looked like a lifecycle.

The fix keeps the version row **byte-immutable** and moves deprecation into its
own append-only record. The 0001, 0005, and 0006 triggers are deliberately left
exactly as they are; nothing about them needed relaxing, which was the point.

Deprecation is an act with an actor, a time, and a reason — the same shape as an
escalation under D7 — and a boolean flag cannot carry any of that. The row *is*
the audit record: append-only, platform-scoped, and outside the per-tenant
chains for the same reason the definitions themselves are (D30/I13). A
platform-curated act has no tenant whose chain it belongs in.

All four version tables are covered. D9 versions Agent Definitions, Skills,
Artifact Definitions, and Control Gate Definitions alike, and leaving any of
them on the old flag would put deprecation in two places — the exact split this
change exists to avoid.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0009_definition_deprecation"
down_revision: str | None = "0008_cost_accounting"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SUBJECTS: tuple[tuple[str, str], ...] = (
    ("agent_definition_version_id", "agent_definition_version"),
    ("skill_version_id", "skill_version"),
    ("artifact_definition_version_id", "artifact_definition_version"),
    ("gate_definition_version_id", "gate_definition_version"),
)

VERSION_TABLES: tuple[str, ...] = tuple(table for _, table in SUBJECTS)


def upgrade() -> None:
    columns: list[sa.Column[object] | sa.SchemaItem] = [
        sa.Column("id", sa.dialects.postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("deprecated_by_identity", sa.String(), nullable=False),
        sa.Column("reason", sa.String(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("transaction_timestamp()"),
            nullable=False,
        ),
    ]
    for column_name, table in SUBJECTS:
        columns.append(
            sa.Column(column_name, sa.dialects.postgresql.UUID(as_uuid=True), nullable=True)
        )
        columns.append(
            sa.ForeignKeyConstraint(
                [column_name],
                [f"{table}.id"],
                name=op.f(f"fk_definition_deprecation_{column_name}"),
                ondelete="RESTRICT",
            )
        )
        # One deprecation per version. Deprecating twice is not a second fact,
        # and NULLs do not collide, so one constraint per subject is enough.
        columns.append(
            sa.UniqueConstraint(column_name, name=op.f(f"uq_definition_deprecation_{column_name}"))
        )

    subject_list = ", ".join(name for name, _ in SUBJECTS)
    columns.append(
        sa.CheckConstraint(
            f"num_nonnulls({subject_list}) = 1",
            name=op.f("ck_definition_deprecation_names_exactly_one_version"),
        )
    )
    columns.append(sa.PrimaryKeyConstraint("id", name=op.f("pk_definition_deprecation")))

    op.create_table("definition_deprecation", *columns)

    # Platform-curated, exactly like the definitions it refers to (D30): every
    # tenant may read it, and only the owner connection may write it. A tenant
    # runtime cannot retire a definition any more than it can publish one.
    op.execute("REVOKE INSERT, UPDATE, DELETE ON definition_deprecation FROM adw_app")
    op.execute("GRANT SELECT ON definition_deprecation TO adw_app")
    op.execute("GRANT SELECT ON definition_deprecation TO adw_auditor")

    op.execute("""
        CREATE OR REPLACE FUNCTION adw_reject_deprecation_mutation() RETURNS trigger AS $$
        BEGIN
            RAISE EXCEPTION
                'deprecation records are append-only: % on %', TG_OP, TG_TABLE_NAME
                USING ERRCODE = 'restrict_violation';
        END;
        $$ LANGUAGE plpgsql;
    """)
    op.execute("""
        CREATE TRIGGER definition_deprecation_append_only
        BEFORE UPDATE OR DELETE ON definition_deprecation
        FOR EACH ROW EXECUTE FUNCTION adw_reject_deprecation_mutation()
    """)

    # The dead flag goes. Keeping a column that can never change from its default
    # is state that lies about what the schema supports.
    for table in VERSION_TABLES:
        op.drop_column(table, "is_deprecated")


def downgrade() -> None:
    for table in VERSION_TABLES:
        op.add_column(
            table,
            sa.Column(
                "is_deprecated",
                sa.Boolean(),
                nullable=False,
                server_default=sa.false(),
            ),
        )

    # Carry the deprecations back onto the flag, so a downgrade loses the actor,
    # the reason, and the time — but not the fact. The immutability triggers must
    # be stood down to do it, which is itself a demonstration of why the flag was
    # unsettable in the first place.
    for column_name, table in SUBJECTS:
        op.execute(f"ALTER TABLE {table} DISABLE TRIGGER {table}_immutable")
        op.execute(
            f"UPDATE {table} SET is_deprecated = true WHERE id IN "
            f"(SELECT {column_name} FROM definition_deprecation "
            f"WHERE {column_name} IS NOT NULL)"
        )
        op.execute(f"ALTER TABLE {table} ENABLE TRIGGER {table}_immutable")

    op.execute(
        "DROP TRIGGER IF EXISTS definition_deprecation_append_only ON definition_deprecation"
    )
    op.execute("DROP FUNCTION IF EXISTS adw_reject_deprecation_mutation()")
    op.drop_table("definition_deprecation")
