"""Tool descriptors — `ARCHITECTURE.md` §13, D9, D30.

A tool the platform cannot describe is a tool it cannot validate, limit, or
authorize. The descriptor is what the Tool Gateway checks against, so it carries
everything the gateway needs and nothing it does not.

Same shape as every other definition: a durable **identity** and an ordered list
of immutable **versions**, platform-curated (D30), pinned per task (I4), and
retired through :class:`~adw.models.definition.DefinitionDeprecation` rather than
edited. That is not symmetry for its own sake — a tool's timeout, limits, and
required scopes are exactly the sort of thing an execution must be able to prove
after the fact, and only a pinned immutable version can answer "what were the
limits at the time?".

**No secret ever lives here.** A descriptor names secret *references*; the
gateway resolves them internally at invocation. The registry is readable by
every tenant, so a credential in this table would be a credential shared with
all of them.
"""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import CheckConstraint, ForeignKey, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from adw.domain.ids import new_id
from adw.models.base import Base, CreatedAtMixin

DEFAULT_TIMEOUT_SECONDS = 30
"""`CLAUDE.md` §4 requires a timeout on every tool call. A descriptor without one
would make that requirement unenforceable, so the column is NOT NULL and this is
only the value used when an author does not state one."""

DEFAULT_MAX_OUTPUT_BYTES = 1024 * 1024
"""A tool that can return a gigabyte is a denial of service with extra steps."""


class ToolDefinition(Base, CreatedAtMixin):
    """The durable identity of a capability, across all its revisions."""

    __tablename__ = "tool_definition"

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True, default=new_id)
    key: Mapped[str] = mapped_column(unique=True, nullable=False)
    """The name an agent proposes and the gateway authorizes, e.g.
    ``spreadsheet.read``. Stable across versions, because a grant that changed
    meaning when a tool was revised would authorize something nobody reviewed."""

    name: Mapped[str] = mapped_column(nullable=False)
    description: Mapped[str] = mapped_column(nullable=False)
    """What the tool does, in the words an agent is shown. Descriptive only — a
    description confers nothing (D10), which is why it is safe to put in a
    prompt."""

    versions: Mapped[list[ToolDefinitionVersion]] = relationship(
        back_populates="definition",
        order_by="ToolDefinitionVersion.version_no",
    )


class ToolDefinitionVersion(Base, CreatedAtMixin):
    """One immutable revision of a tool's contract and limits."""

    __tablename__ = "tool_definition_version"
    __table_args__ = (
        UniqueConstraint("tool_definition_id", "version_no"),
        CheckConstraint("timeout_seconds > 0", name="timeout_is_positive"),
        CheckConstraint("max_output_bytes > 0", name="output_limit_is_positive"),
    )

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True, default=new_id)
    tool_definition_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("tool_definition.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    version_no: Mapped[int] = mapped_column(nullable=False)

    input_schema_json: Mapped[str] = mapped_column(nullable=False)
    output_schema_json: Mapped[str] = mapped_column(nullable=False)
    """The contract, as canonical JSON, recorded so an execution can say what the
    contract *was*. The validating is done by the tool's Pydantic model (D16/G1);
    this is the auditable record of it, not a second implementation of it."""

    timeout_seconds: Mapped[int] = mapped_column(nullable=False, default=DEFAULT_TIMEOUT_SECONDS)
    max_output_bytes: Mapped[int] = mapped_column(nullable=False, default=DEFAULT_MAX_OUTPUT_BYTES)
    """`CLAUDE.md` §4: timeouts and resource limits on every tool call. Pinned per
    version, so a limit that was raised later cannot be mistaken for the limit
    that applied at the time."""

    required_scopes_json: Mapped[str] = mapped_column(nullable=False, default="[]")
    """The scopes a grant must carry for this tool to run. Declared by the tool,
    checked by the gateway, and never widened by anything the model says."""

    definition: Mapped[ToolDefinition] = relationship(back_populates="versions")
