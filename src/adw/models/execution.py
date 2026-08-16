"""Execution — one run of one requirement for one tenant.

The root of everything: the unit of budget, audit, and delivery.

**Deliberately absent: the requirement text.** It is tenant business content, so
D1 requires it encrypted under a per-tenant key, and the KeyStore port does not
exist until Task 7. Storing it in plaintext meanwhile would be exactly the
"we'll fix it later" that D12 exists to prevent — the store is append-only, so
anything written unencrypted stays unencrypted permanently. The column arrives
with the KeyStore, alongside its ``key_id`` (D25).
"""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import Enum as SqlEnum
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column

from adw.domain.ids import new_id
from adw.domain.states import ExecutionState
from adw.models.base import Base, CreatedAtMixin, TenantScopedMixin, UpdatedAtMixin


class Execution(Base, TenantScopedMixin, CreatedAtMixin, UpdatedAtMixin):
    """One run of one requirement."""

    __tablename__ = "execution"

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True, default=new_id)

    requester_identity: Mapped[str] = mapped_column(nullable=False)
    """Who asked. An identifier, not a name — it appears in the audit record."""

    state: Mapped[ExecutionState] = mapped_column(
        SqlEnum(
            ExecutionState,
            name="execution_state",
            native_enum=False,
            values_callable=lambda enum: [member.value for member in enum],
            length=32,
        ),
        default=ExecutionState.DRAFT,
        nullable=False,
        index=True,
    )
    """Stored as a checked string rather than a native PostgreSQL enum: adding a
    state stays an ordinary migration, and the persisted value matches the
    audit-chain representation exactly.

    Transitions are **not** enforced yet. The Execution machine has documented
    states but undocumented edges — ``failed``, ``blocked``, and ``cancelled``
    have no stated entry or exit, and ``expired`` no stated target. See
    :mod:`adw.domain.transitions`.
    """
