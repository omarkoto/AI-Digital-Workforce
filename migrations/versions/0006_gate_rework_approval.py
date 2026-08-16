"""Control gates, rework attempts, and human approval.

Revision ID: 0006_gate_rework_approval
Revises: 0005_artifact
Create Date: Phase 1 Task 9

Two constraints here carry claims the product is sold on, and both are in the
database rather than only in a service:

* ``producer_is_not_the_approver`` — D4/I5. Possible as a CHECK because both
  identities live on the same row, which is why the model stores the producer
  identity rather than deriving it.
* ``within_rework_limit`` — D11, so the cap holds where a service forgets.

Also completes the evidence table: ``gate_decision_id`` gains its foreign key.
The exclusivity invariant has held since Task 7; only the reference waited.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0006_gate_rework_approval"
down_revision: str | None = "0005_artifact"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TENANT_PREDICATE = "tenant_id = nullif(current_setting('app.tenant_id', true), '')::uuid"

GATE_VERDICTS = "'pass', 'fail', 'waived'"
EVALUATION_KINDS = "'deterministic', 'model_assessed'"
APPROVAL_STATES = "'pending', 'approved', 'rejected', 'expired'"

TENANT_SCOPED = ("gate_decision", "rework_attempt", "approval_item")
DEFINITION_TABLES = ("gate_definition", "gate_definition_version")


def upgrade() -> None:
    op.create_table(
        "gate_definition",
        sa.Column("id", sa.dialects.postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("key", sa.String(), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("transaction_timestamp()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_gate_definition")),
        sa.UniqueConstraint("key", name=op.f("uq_gate_definition_key")),
    )

    op.create_table(
        "gate_definition_version",
        sa.Column("id", sa.dialects.postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("gate_definition_id", sa.dialects.postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("version_no", sa.Integer(), nullable=False),
        sa.Column("rule_id", sa.String(), nullable=False),
        sa.Column("evaluation_kind", sa.String(length=32), nullable=False),
        sa.Column("requires_human", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("config_json", sa.String(), nullable=False, server_default="{}"),
        sa.Column("is_deprecated", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("transaction_timestamp()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            f"evaluation_kind IN ({EVALUATION_KINDS})",
            name=op.f("ck_gate_definition_version_gate_evaluation_kind"),
        ),
        sa.ForeignKeyConstraint(
            ["gate_definition_id"],
            ["gate_definition.id"],
            name=op.f("fk_gate_definition_version_gate_definition_id"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_gate_definition_version")),
        sa.UniqueConstraint(
            "gate_definition_id",
            "version_no",
            name=op.f("uq_gate_definition_version_gate_definition_id_version_no"),
        ),
    )
    op.create_index(
        op.f("ix_gate_definition_version_gate_definition_id"),
        "gate_definition_version",
        ["gate_definition_id"],
    )

    op.create_table(
        "gate_decision",
        sa.Column("id", sa.dialects.postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("tenant_id", sa.dialects.postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "gate_definition_version_id",
            sa.dialects.postgresql.UUID(as_uuid=True),
            nullable=False,
        ),
        sa.Column("artifact_version_id", sa.dialects.postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("task_id", sa.dialects.postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("verdict", sa.String(length=16), nullable=False),
        sa.Column("decided_by_identity", sa.String(), nullable=False),
        sa.Column("producer_identity", sa.String(), nullable=False),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("rule_id", sa.String(), nullable=False),
        sa.Column("evaluation_kind", sa.String(length=32), nullable=False),
        sa.Column("failure_detail", sa.String(), nullable=True),
        sa.Column("waiver_reason", sa.String(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("transaction_timestamp()"),
            nullable=False,
        ),
        # D4/I5. CLAUDE.md §3: enforce in code, not by prompt instruction.
        sa.CheckConstraint(
            "decided_by_identity <> producer_identity",
            name=op.f("ck_gate_decision_producer_is_not_the_approver"),
        ),
        sa.CheckConstraint(f"verdict IN ({GATE_VERDICTS})", name=op.f("ck_gate_decision_verdict")),
        sa.CheckConstraint(
            f"evaluation_kind IN ({EVALUATION_KINDS})",
            name=op.f("ck_gate_decision_gate_evaluation_kind"),
        ),
        sa.ForeignKeyConstraint(
            ["artifact_version_id"],
            ["artifact_version.id"],
            name=op.f("fk_gate_decision_artifact_version_id"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["gate_definition_version_id"],
            ["gate_definition_version.id"],
            name=op.f("fk_gate_decision_gate_definition_version_id"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["task_id"], ["task.id"], name=op.f("fk_gate_decision_task_id"), ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenant.id"],
            name=op.f("fk_gate_decision_tenant_id"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_gate_decision")),
    )
    for column in ("tenant_id", "artifact_version_id", "task_id", "verdict"):
        op.create_index(op.f(f"ix_gate_decision_{column}"), "gate_decision", [column])
    op.create_index(
        op.f("ix_gate_decision_gate_definition_version_id"),
        "gate_decision",
        ["gate_definition_version_id"],
    )

    op.create_table(
        "rework_attempt",
        sa.Column("id", sa.dialects.postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("tenant_id", sa.dialects.postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("task_id", sa.dialects.postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("attempt_no", sa.Integer(), nullable=False),
        sa.Column(
            "triggering_gate_decision_id",
            sa.dialects.postgresql.UUID(as_uuid=True),
            nullable=False,
        ),
        sa.Column("failure_detail", sa.String(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("transaction_timestamp()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "attempt_no BETWEEN 1 AND 3", name=op.f("ck_rework_attempt_within_rework_limit")
        ),
        sa.ForeignKeyConstraint(
            ["task_id"], ["task.id"], name=op.f("fk_rework_attempt_task_id"), ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenant.id"],
            name=op.f("fk_rework_attempt_tenant_id"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["triggering_gate_decision_id"],
            ["gate_decision.id"],
            name=op.f("fk_rework_attempt_triggering_gate_decision_id"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_rework_attempt")),
        sa.UniqueConstraint(
            "task_id", "attempt_no", name=op.f("uq_rework_attempt_task_id_attempt_no")
        ),
    )
    op.create_index(op.f("ix_rework_attempt_tenant_id"), "rework_attempt", ["tenant_id"])
    op.create_index(op.f("ix_rework_attempt_task_id"), "rework_attempt", ["task_id"])
    op.create_index(
        op.f("ix_rework_attempt_triggering_gate_decision_id"),
        "rework_attempt",
        ["triggering_gate_decision_id"],
    )

    op.create_table(
        "approval_item",
        sa.Column("id", sa.dialects.postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("tenant_id", sa.dialects.postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("artifact_version_id", sa.dialects.postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "gate_definition_version_id",
            sa.dialects.postgresql.UUID(as_uuid=True),
            nullable=False,
        ),
        sa.Column("task_id", sa.dialects.postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("state", sa.String(length=16), nullable=False),
        sa.Column("producer_identity", sa.String(), nullable=False),
        sa.Column("requester_identity", sa.String(), nullable=False),
        sa.Column("decided_by_identity", sa.String(), nullable=True),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("sla_deadline", sa.DateTime(timezone=True), nullable=False),
        sa.Column("escalated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("escalated_to", sa.String(), nullable=True),
        sa.Column("gate_decision_id", sa.dialects.postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("transaction_timestamp()"),
            nullable=False,
        ),
        sa.CheckConstraint(f"state IN ({APPROVAL_STATES})", name=op.f("ck_approval_item_state")),
        # D4 bars the producer; PRODUCT.md §18 bars the requester as well.
        sa.CheckConstraint(
            "decided_by_identity IS NULL OR "
            "(decided_by_identity <> producer_identity "
            "AND decided_by_identity <> requester_identity)",
            name=op.f("ck_approval_item_decider_is_neither_producer_nor_requester"),
        ),
        sa.CheckConstraint(
            "(state = 'pending') = (decided_at IS NULL)",
            name=op.f("ck_approval_item_decided_states_carry_a_timestamp"),
        ),
        sa.ForeignKeyConstraint(
            ["artifact_version_id"],
            ["artifact_version.id"],
            name=op.f("fk_approval_item_artifact_version_id"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["gate_decision_id"],
            ["gate_decision.id"],
            name=op.f("fk_approval_item_gate_decision_id"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["gate_definition_version_id"],
            ["gate_definition_version.id"],
            name=op.f("fk_approval_item_gate_definition_version_id"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["task_id"], ["task.id"], name=op.f("fk_approval_item_task_id"), ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenant.id"],
            name=op.f("fk_approval_item_tenant_id"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_approval_item")),
    )
    for column in ("tenant_id", "artifact_version_id", "task_id", "state"):
        op.create_index(op.f(f"ix_approval_item_{column}"), "approval_item", [column])

    for table in TENANT_SCOPED:
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
        op.execute(
            f"CREATE POLICY {table}_tenant_isolation ON {table} "
            f"USING ({TENANT_PREDICATE}) WITH CHECK ({TENANT_PREDICATE})"
        )

    for table in DEFINITION_TABLES:
        op.execute(f"REVOKE INSERT, UPDATE, DELETE ON {table} FROM adw_app")
        op.execute(f"GRANT SELECT ON {table} TO adw_app")

    op.execute("""
        CREATE TRIGGER gate_definition_version_immutable
        BEFORE UPDATE OR DELETE ON gate_definition_version
        FOR EACH ROW EXECUTE FUNCTION adw_reject_version_mutation()
    """)

    # A verdict and a rework attempt are records of what happened. Neither is
    # revisable: a gate that changed its mind after the fact is not a control.
    op.execute("REVOKE UPDATE, DELETE ON gate_decision, rework_attempt FROM adw_app")
    op.execute("""
        CREATE OR REPLACE FUNCTION adw_reject_decision_mutation() RETURNS trigger AS $$
        BEGIN
            RAISE EXCEPTION
                'gate decisions and rework attempts are append-only: % on %',
                TG_OP, TG_TABLE_NAME
                USING ERRCODE = 'restrict_violation';
        END;
        $$ LANGUAGE plpgsql;
    """)
    for table in ("gate_decision", "rework_attempt"):
        op.execute(f"""
            CREATE TRIGGER {table}_append_only
            BEFORE UPDATE OR DELETE ON {table}
            FOR EACH ROW EXECUTE FUNCTION adw_reject_decision_mutation()
        """)

    # --- Task.attempt_no widens to match D11 --------------------------------
    # D11 permits three rework loops, so a task can reach a fourth attempt. The
    # original bound of 3 silently allowed only two loops. The rework rows are
    # the authority for the budget; this column mirrors them.
    # Bare name: the metadata naming convention supplies the ck_task_ prefix.
    op.drop_constraint("attempt_no_within_rework_limit", "task", type_="check")
    op.create_check_constraint(
        "attempt_no_within_rework_limit", "task", "attempt_no BETWEEN 1 AND 4"
    )

    # --- Evidence completes its exclusivity (Task 7) ------------------------
    op.create_foreign_key(
        op.f("fk_evidence_gate_decision_id"),
        "evidence",
        "gate_decision",
        ["gate_decision_id"],
        ["id"],
        ondelete="RESTRICT",
    )

    op.execute(
        "GRANT SELECT ON gate_definition, gate_definition_version, gate_decision, "
        "rework_attempt, approval_item TO adw_auditor"
    )


def downgrade() -> None:
    op.drop_constraint(op.f("fk_evidence_gate_decision_id"), "evidence", type_="foreignkey")
    op.drop_constraint("attempt_no_within_rework_limit", "task", type_="check")
    # Narrowing a bound is destructive by nature: rows on a fourth attempt cannot
    # satisfy the old constraint, so they are clamped rather than left to make the
    # downgrade fail half-way and strand the schema between revisions.
    op.execute("UPDATE task SET attempt_no = 3 WHERE attempt_no > 3")
    op.create_check_constraint(
        "attempt_no_within_rework_limit", "task", "attempt_no BETWEEN 1 AND 3"
    )
    for table in ("gate_decision", "rework_attempt"):
        op.execute(f"DROP TRIGGER IF EXISTS {table}_append_only ON {table}")
    op.execute("DROP FUNCTION IF EXISTS adw_reject_decision_mutation()")
    op.execute(
        "DROP TRIGGER IF EXISTS gate_definition_version_immutable ON gate_definition_version"
    )
    op.drop_table("approval_item")
    op.drop_table("rework_attempt")
    op.drop_table("gate_decision")
    op.drop_table("gate_definition_version")
    op.drop_table("gate_definition")
