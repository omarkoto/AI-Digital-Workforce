"""Versioned definitions — D9, D30.

Each definition type is two tables: a durable **identity** and an ordered list of
immutable **versions**. The identity is what the console names; the version is
what an execution pins.

These tables are **platform-scoped** (D30): they carry no ``tenant_id`` and are
readable by every tenant, because D5 makes MVP departments platform-curated and a
definition is platform content rather than tenant content. That is the third
structure outside tenant scope named by invariant I13.

Immutability is enforced in the database, not by convention: the migration
revokes UPDATE and DELETE on the version tables from the runtime role and adds a
trigger. A version an execution pinned can never change, or the record could no
longer answer what the rules were at the time.
"""

from __future__ import annotations

from enum import StrEnum
from uuid import UUID

from sqlalchemy import CheckConstraint, ForeignKey, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from adw.domain.ids import new_id
from adw.models.base import Base, CreatedAtMixin


class AgentDefinition(Base, CreatedAtMixin):
    """The durable identity of an agent role, across all its revisions."""

    __tablename__ = "agent_definition"

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True, default=new_id)
    key: Mapped[str] = mapped_column(unique=True, nullable=False)
    name: Mapped[str] = mapped_column(nullable=False)

    versions: Mapped[list[AgentDefinitionVersion]] = relationship(
        back_populates="definition",
        order_by="AgentDefinitionVersion.version_no",
    )


class AgentDefinitionVersion(Base, CreatedAtMixin):
    """One immutable revision of an agent's job description."""

    __tablename__ = "agent_definition_version"
    __table_args__ = (UniqueConstraint("agent_definition_id", "version_no"),)

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True, default=new_id)
    agent_definition_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("agent_definition.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    version_no: Mapped[int] = mapped_column(nullable=False)
    """Ordinal and human-facing. D26's non-enumerable rule governs entity
    identity, never version numbers, which must stay legible as v1, v2, v3."""

    instructions: Mapped[str] = mapped_column(nullable=False)
    """The whole of the row's mutable surface: none. Deprecation — the only
    lifecycle a referenced version has (D9) — is a row in
    :class:`DefinitionDeprecation`, not a column here."""

    definition: Mapped[AgentDefinition] = relationship(back_populates="versions")


class Skill(Base, CreatedAtMixin):
    """The durable identity of a reusable instruction set."""

    __tablename__ = "skill"

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True, default=new_id)
    key: Mapped[str] = mapped_column(unique=True, nullable=False)
    name: Mapped[str] = mapped_column(nullable=False)

    versions: Mapped[list[SkillVersion]] = relationship(
        back_populates="skill",
        order_by="SkillVersion.version_no",
    )


class SkillVersion(Base, CreatedAtMixin):
    """One immutable revision of a skill's content.

    A Skill grants nothing (D10). It shapes reasoning; capability arrives only
    through a permission grant, which is why instruction can never confer access.
    """

    __tablename__ = "skill_version"
    __table_args__ = (UniqueConstraint("skill_id", "version_no"),)

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True, default=new_id)
    skill_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("skill.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    version_no: Mapped[int] = mapped_column(nullable=False)
    content: Mapped[str] = mapped_column(nullable=False)

    skill: Mapped[Skill] = relationship(back_populates="versions")


class DefinitionKind(StrEnum):
    """Which sort of definition version a deprecation refers to."""

    AGENT_DEFINITION = "agent_definition_version"
    SKILL = "skill_version"
    ARTIFACT_DEFINITION = "artifact_definition_version"
    GATE_DEFINITION = "gate_definition_version"
    TOOL = "tool_definition_version"


class DefinitionDeprecation(Base, CreatedAtMixin):
    """A definition version retired from new use — D9.

    D9 permits exactly one lifecycle event on a pinned version: deprecation.
    This is that event, recorded rather than flagged, because deprecation is an
    **act with an actor, a time, and a reason** and a boolean carries none of
    them. The version row itself stays byte-immutable, which is the guarantee
    worth keeping absolute: no UPDATE on a version table, by any role, ever.

    Append-only by trigger, and platform-scoped like the definitions it refers
    to (D30/I13) — a platform-curated act has no tenant whose chain it belongs
    in, so this row *is* the audit record.

    **Deprecation retires a version from new pins. It never touches old ones.**
    An execution that pinned v1 keeps v1, keeps reading it, and keeps
    reconstructing from it, which is the whole reason a version can be retired
    but never deleted.
    """

    __tablename__ = "definition_deprecation"

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True, default=new_id)

    agent_definition_version_id: Mapped[UUID | None] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("agent_definition_version.id", ondelete="RESTRICT"),
        nullable=True,
        unique=True,
    )
    skill_version_id: Mapped[UUID | None] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("skill_version.id", ondelete="RESTRICT"),
        nullable=True,
        unique=True,
    )
    artifact_definition_version_id: Mapped[UUID | None] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("artifact_definition_version.id", ondelete="RESTRICT"),
        nullable=True,
        unique=True,
    )
    gate_definition_version_id: Mapped[UUID | None] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("gate_definition_version.id", ondelete="RESTRICT"),
        nullable=True,
        unique=True,
    )
    tool_definition_version_id: Mapped[UUID | None] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("tool_definition_version.id", ondelete="RESTRICT"),
        nullable=True,
        unique=True,
    )
    """Real foreign keys rather than a kind-plus-id pair, so the database refuses
    a deprecation of a version that does not exist. Exactly one is set;
    ``RESTRICT`` because a deprecated version must outlive its retirement.

    Adding a kind means adding a column here, which is deliberate friction: a new
    sort of definition should have to say so in the schema rather than arrive as
    an unchecked string."""

    deprecated_by_identity: Mapped[str] = mapped_column(nullable=False)
    reason: Mapped[str] = mapped_column(nullable=False)
    """Required, not optional. "Why is this retired?" is the question an operator
    asks six months later, and a nullable column is how it goes unanswered."""

    __table_args__ = (
        CheckConstraint(
            "num_nonnulls(agent_definition_version_id, skill_version_id, "
            "artifact_definition_version_id, gate_definition_version_id, "
            "tool_definition_version_id) = 1",
            name="names_exactly_one_version",
        ),
    )

    @property
    def kind(self) -> DefinitionKind:
        """Which sort of version this retires."""
        if self.agent_definition_version_id is not None:
            return DefinitionKind.AGENT_DEFINITION
        if self.skill_version_id is not None:
            return DefinitionKind.SKILL
        if self.artifact_definition_version_id is not None:
            return DefinitionKind.ARTIFACT_DEFINITION
        if self.gate_definition_version_id is not None:
            return DefinitionKind.GATE_DEFINITION
        return DefinitionKind.TOOL

    @property
    def subject_id(self) -> UUID:
        """The version this retires, whichever kind it is."""
        for candidate in (
            self.agent_definition_version_id,
            self.skill_version_id,
            self.artifact_definition_version_id,
            self.gate_definition_version_id,
            self.tool_definition_version_id,
        ):
            if candidate is not None:
                return candidate
        msg = "a deprecation row must name exactly one version"
        raise ValueError(msg)
