"""Dispatch queue and idempotency ledger.

Revision ID: 0007_dispatch_queue
Revises: 0006_gate_rework_approval
Create Date: Phase 1 Task 10

These two tables are the deliberate exception to blanket tenant isolation
(I13). A worker cannot establish tenant context before reading the queue, so the
queue cannot sit behind that context. What makes the exception safe is that it
carries identifiers and scheduling only — never business content — and a test
asserts the column set rather than trusting the comment.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0007_dispatch_queue"
down_revision: str | None = "0006_gate_rework_approval"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

JOB_STATES = "'ready', 'claimed', 'done', 'failed'"


def upgrade() -> None:
    op.create_table(
        "dispatch_queue",
        sa.Column("id", sa.dialects.postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("tenant_id", sa.dialects.postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("job_type", sa.String(), nullable=False),
        sa.Column("target_id", sa.dialects.postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("idempotency_key", sa.String(), nullable=False),
        sa.Column("available_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("claimed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("claimed_by", sa.String(), nullable=True),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("state", sa.String(length=16), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("transaction_timestamp()"),
            nullable=False,
        ),
        sa.CheckConstraint("attempts >= 0", name=op.f("ck_dispatch_queue_attempts_not_negative")),
        sa.CheckConstraint(f"state IN ({JOB_STATES})", name=op.f("ck_dispatch_queue_job_state")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_dispatch_queue")),
        sa.UniqueConstraint(
            "tenant_id", "idempotency_key", name=op.f("uq_dispatch_queue_tenant_id_idempotency_key")
        ),
    )
    op.create_index(op.f("ix_dispatch_queue_tenant_id"), "dispatch_queue", ["tenant_id"])
    op.create_index("ix_dispatch_queue_claimable", "dispatch_queue", ["state", "available_at"])

    op.create_table(
        "job_execution",
        sa.Column("id", sa.dialects.postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("tenant_id", sa.dialects.postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("idempotency_key", sa.String(), nullable=False),
        sa.Column("job_type", sa.String(), nullable=False),
        sa.Column("outcome", sa.String(), nullable=False),
        sa.Column(
            "duplicate_deliveries", sa.Integer(), nullable=False, server_default=sa.text("0")
        ),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_job_execution")),
        sa.UniqueConstraint(
            "tenant_id", "idempotency_key", name=op.f("uq_job_execution_tenant_id_idempotency_key")
        ),
    )
    op.create_index(op.f("ix_job_execution_tenant_id"), "job_execution", ["tenant_id"])

    op.execute("GRANT SELECT ON dispatch_queue, job_execution TO adw_auditor")


def downgrade() -> None:
    op.drop_table("job_execution")
    op.drop_table("dispatch_queue")
