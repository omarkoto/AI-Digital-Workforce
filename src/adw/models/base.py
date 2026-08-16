"""Declarative base and shared column mixins.

Two rules encoded here rather than repeated per model:

* Timestamps come from ``transaction_timestamp()`` — the database clock, never
  the application host's (D21/G6). Python never supplies a platform timestamp.
* A tenant-scoped table carries ``tenant_id``, which is what every row-level
  security policy compares against (D18/G3).
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import ForeignKey, MetaData, func, text
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

NAMING_CONVENTION = {
    "ix": "ix_%(table_name)s_%(column_0_N_name)s",
    "uq": "uq_%(table_name)s_%(column_0_N_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s",
    "pk": "pk_%(table_name)s",
}
"""Deterministic constraint names, so migrations can drop what they created."""


class Base(DeclarativeBase):
    """Declarative base for every model."""

    metadata = MetaData(naming_convention=NAMING_CONVENTION)


class CreatedAtMixin:
    """A creation timestamp issued by the database."""

    created_at: Mapped[datetime] = mapped_column(
        server_default=func.transaction_timestamp(),
        nullable=False,
    )


class UpdatedAtMixin:
    """A mutation timestamp issued by the database."""

    updated_at: Mapped[datetime] = mapped_column(
        server_default=func.transaction_timestamp(),
        onupdate=func.transaction_timestamp(),
        nullable=False,
    )


class TenantScopedMixin:
    """Marks a table as tenant-owned.

    Every table carrying this mixin must, in the migration that creates it,
    enable and force row-level security and define a policy. The coverage test
    in ``tests/security/test_policy_coverage.py`` fails the build otherwise.
    """

    tenant_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("tenant.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )


TENANT_POLICY_PREDICATE = text(
    "tenant_id = nullif(current_setting('app.tenant_id', true), '')::uuid"
)
"""The predicate every tenant policy uses.

With the setting absent, ``current_setting`` yields NULL, the comparison is NULL
rather than true, and the query sees zero rows — the fail-closed rule in D18.
"""
