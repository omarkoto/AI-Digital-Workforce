"""Authoring and resolving Agent Definitions and Skills — D5, D9, D10, D30.

Open decision **F** is settled: definitions live in the database, using the
immutable versioning already built in Phase 1. This module adds the authoring
surface and the resolution path. **It adds no schema** — the tables, the version
immutability trigger, and the pinning foreign keys all exist and are unchanged.

Two privilege levels, and the split is enforced by the database rather than here:

* **Authoring** requires a session on the owner connection. Migration 0001
  revokes INSERT, UPDATE and DELETE on all four definition tables from
  ``adw_app`` and grants it SELECT only. That is D5's "platform-curated in MVP"
  made structural — a tenant runtime *cannot* author a definition, however it is
  called and whatever an agent is persuaded to attempt.
* **Resolution** is a read, so it works on the runtime connection like any other
  query.

Publishing is append-only. A correction is a new version, never an edit, because
an execution that pinned v1 must still be able to say what v1 said (D9/I4).

A Skill still grants nothing (D10). Publishing skill content cannot widen an
agent's capability, which is why instruction and permission are separate tables
and why injected content cannot escalate privilege.
"""

from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from adw.domain.errors import DomainError
from adw.models.definition import (
    AgentDefinition,
    AgentDefinitionVersion,
    Skill,
    SkillVersion,
)


class DefinitionNotFoundError(DomainError):
    """No definition exists under the requested key."""


class NoPublishableVersionError(DomainError):
    """A definition exists but has no version a task may pin.

    Either nothing has been published yet, or every version is deprecated.
    Distinguished from "not found" because the two mean different things to an
    operator: one is a missing definition, the other a retired one.
    """


class DuplicateDefinitionError(DomainError):
    """A definition already exists under that key."""


# --- Authoring: identities --------------------------------------------------


def create_agent_definition(session: Session, *, key: str, name: str) -> AgentDefinition:
    """Create the durable identity of an agent role.

    The identity carries no instructions. Instructions belong to a version, so
    that changing them leaves the previous wording intact and referenceable.
    """
    if session.scalar(select(AgentDefinition).where(AgentDefinition.key == key)) is not None:
        msg = f"an agent definition already exists under key {key!r}"
        raise DuplicateDefinitionError(msg)
    definition = AgentDefinition(key=key, name=name)
    session.add(definition)
    session.flush()
    return definition


def create_skill(session: Session, *, key: str, name: str) -> Skill:
    """Create the durable identity of a reusable instruction set."""
    if session.scalar(select(Skill).where(Skill.key == key)) is not None:
        msg = f"a skill already exists under key {key!r}"
        raise DuplicateDefinitionError(msg)
    skill = Skill(key=key, name=name)
    session.add(skill)
    session.flush()
    return skill


# --- Authoring: versions ----------------------------------------------------


# Version numbers are read-then-written without a lock, deliberately. The unique
# constraint on (identity_id, version_no) is what actually prevents a collision:
# two concurrent publishes race and one loses with an integrity error rather than
# silently overwriting. Authoring is a rare, human-paced platform operation, so an
# occasional retry is the right price for not holding a lock.


def publish_agent_version(
    session: Session, *, key: str, instructions: str
) -> AgentDefinitionVersion:
    """Publish the next immutable version of an agent's instructions.

    Requires an owner session — the runtime role has no INSERT here.

    Raises:
        DefinitionNotFoundError: if no agent definition uses that key.
    """
    definition = session.scalar(select(AgentDefinition).where(AgentDefinition.key == key))
    if definition is None:
        msg = f"no agent definition under key {key!r}"
        raise DefinitionNotFoundError(msg)

    highest = session.scalar(
        select(func.max(AgentDefinitionVersion.version_no)).where(
            AgentDefinitionVersion.agent_definition_id == definition.id
        )
    )
    version = AgentDefinitionVersion(
        agent_definition_id=definition.id,
        version_no=int(highest or 0) + 1,
        instructions=instructions,
    )
    session.add(version)
    session.flush()
    return version


def publish_skill_version(session: Session, *, key: str, content: str) -> SkillVersion:
    """Publish the next immutable version of a skill's content.

    Requires an owner session.

    Raises:
        DefinitionNotFoundError: if no skill uses that key.
    """
    skill = session.scalar(select(Skill).where(Skill.key == key))
    if skill is None:
        msg = f"no skill under key {key!r}"
        raise DefinitionNotFoundError(msg)

    highest = session.scalar(
        select(func.max(SkillVersion.version_no)).where(SkillVersion.skill_id == skill.id)
    )
    version = SkillVersion(
        skill_id=skill.id,
        version_no=int(highest or 0) + 1,
        content=content,
    )
    session.add(version)
    session.flush()
    return version


# --- Resolution -------------------------------------------------------------


def resolve_agent_version(
    session: Session, *, key: str, version_no: int | None = None
) -> AgentDefinitionVersion:
    """Return the version a task should pin.

    With ``version_no``, the exact version — including a deprecated one, because
    reproducing a past execution must be possible after a definition is retired.
    Without it, the highest non-deprecated version.

    Raises:
        DefinitionNotFoundError: no definition, or no such version number.
        NoPublishableVersionError: nothing published, or everything deprecated.
    """
    definition = session.scalar(select(AgentDefinition).where(AgentDefinition.key == key))
    if definition is None:
        msg = f"no agent definition under key {key!r}"
        raise DefinitionNotFoundError(msg)

    query = select(AgentDefinitionVersion).where(
        AgentDefinitionVersion.agent_definition_id == definition.id
    )
    if version_no is not None:
        version = session.scalar(query.where(AgentDefinitionVersion.version_no == version_no))
        if version is None:
            msg = f"agent definition {key!r} has no version {version_no}"
            raise DefinitionNotFoundError(msg)
        return version

    latest = session.scalar(
        query.where(AgentDefinitionVersion.is_deprecated.is_(False))
        .order_by(AgentDefinitionVersion.version_no.desc())
        .limit(1)
    )
    if latest is None:
        msg = f"agent definition {key!r} has no version a task may pin"
        raise NoPublishableVersionError(msg)
    return latest


def resolve_skill_version(
    session: Session, *, key: str, version_no: int | None = None
) -> SkillVersion:
    """Return the skill version a task should pin. See ``resolve_agent_version``."""
    skill = session.scalar(select(Skill).where(Skill.key == key))
    if skill is None:
        msg = f"no skill under key {key!r}"
        raise DefinitionNotFoundError(msg)

    query = select(SkillVersion).where(SkillVersion.skill_id == skill.id)
    if version_no is not None:
        version = session.scalar(query.where(SkillVersion.version_no == version_no))
        if version is None:
            msg = f"skill {key!r} has no version {version_no}"
            raise DefinitionNotFoundError(msg)
        return version

    latest = session.scalar(
        query.where(SkillVersion.is_deprecated.is_(False))
        .order_by(SkillVersion.version_no.desc())
        .limit(1)
    )
    if latest is None:
        msg = f"skill {key!r} has no version a task may pin"
        raise NoPublishableVersionError(msg)
    return latest


def resolve_skill_versions(session: Session, *, keys: tuple[str, ...]) -> list[SkillVersion]:
    """Resolve several skills, in the order given.

    All or nothing: a missing skill raises before anything is pinned, so a task
    never starts with a partial instruction set it does not know is partial.
    """
    return [resolve_skill_version(session, key=key) for key in keys]
