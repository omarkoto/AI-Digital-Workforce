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

from uuid import UUID

from sqlalchemy import ForeignKey, UniqueConstraint
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
    is_deprecated: Mapped[bool] = mapped_column(default=False, nullable=False)
    """Deprecation is the only lifecycle a referenced version has. Deleting one
    would strand every execution that pinned it."""

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
    is_deprecated: Mapped[bool] = mapped_column(default=False, nullable=False)

    skill: Mapped[Skill] = relationship(back_populates="versions")
