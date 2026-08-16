"""The tenant — the isolation boundary itself.

Unusual among tables: it carries ``id`` rather than ``tenant_id``, because it
*is* the tenant. Its policy therefore compares ``id`` against the session
setting, so a tenant can read its own row and cannot enumerate the others.
"""

from __future__ import annotations

from uuid import UUID

from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column

from adw.domain.ids import new_tenant_id
from adw.models.base import Base, CreatedAtMixin


class Tenant(Base, CreatedAtMixin):
    """One customer organization."""

    __tablename__ = "tenant"

    id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True),
        primary_key=True,
        default=new_tenant_id,
    )
    """UUIDv4, never v7 (D28): the isolation boundary must disclose nothing,
    not even creation time."""

    slug: Mapped[str] = mapped_column(unique=True, nullable=False)
    name: Mapped[str] = mapped_column(nullable=False)
