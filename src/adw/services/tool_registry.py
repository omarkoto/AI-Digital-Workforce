"""Authoring and resolving tool descriptors — `ARCHITECTURE.md` §13, D9, D30.

The registry holds what a tool *is*: its contract, its limits, its required
scopes. It does not hold what a tool *may do here and now* — that is a grant, it
lives with the task, and the two are separate tables for the same reason
instruction and capability are (D10).

Authoring requires an owner session. Migration 0010 grants ``adw_app`` SELECT and
nothing else, so a tenant runtime cannot register a tool, revise one, or widen
its limits, however the call is made and whatever an agent is persuaded to
attempt.

Publishing is append-only, like every other definition. Raising a timeout is a
new version, never an edit, because an execution has to be able to say what the
limit was when it ran.
"""

from __future__ import annotations

import json
from collections.abc import Sequence

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from adw.domain.canonical import canonicalize
from adw.domain.errors import DomainError
from adw.models.definition import DefinitionKind
from adw.models.tool import (
    DEFAULT_MAX_OUTPUT_BYTES,
    DEFAULT_TIMEOUT_SECONDS,
    ToolDefinition,
    ToolDefinitionVersion,
)
from adw.services.definition_service import (
    DefinitionNotFoundError,
    DuplicateDefinitionError,
    NoPublishableVersionError,
    not_deprecated,
)


class ToolDescriptorError(DomainError):
    """A tool descriptor was rejected."""


def register_tool(session: Session, *, key: str, name: str, description: str) -> ToolDefinition:
    """Create the durable identity of a capability.

    Requires an owner session.

    Raises:
        DuplicateDefinitionError: if the key is already registered.
    """
    if session.scalar(select(ToolDefinition).where(ToolDefinition.key == key)) is not None:
        msg = f"a tool is already registered under key {key!r}"
        raise DuplicateDefinitionError(msg)
    definition = ToolDefinition(key=key, name=name, description=description)
    session.add(definition)
    session.flush()
    return definition


def publish_tool_version(
    session: Session,
    *,
    key: str,
    input_schema: object,
    output_schema: object,
    timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS,
    max_output_bytes: int = DEFAULT_MAX_OUTPUT_BYTES,
    required_scopes: Sequence[str] = (),
) -> ToolDefinitionVersion:
    """Publish the next immutable version of a tool's contract and limits.

    Schemas are canonicalized (D23) before storage, so two descriptors that mean
    the same thing store identically and a diff between versions is a real
    difference rather than a reordering.

    Requires an owner session.

    Raises:
        DefinitionNotFoundError: if no tool uses that key.
        ToolDescriptorError: if a limit is not positive. `CLAUDE.md` §4 requires a
            timeout and a resource limit on every tool call, and a descriptor is
            where that requirement is made enforceable.
    """
    if timeout_seconds <= 0:
        msg = "a tool version must carry a positive timeout"
        raise ToolDescriptorError(msg)
    if max_output_bytes <= 0:
        msg = "a tool version must carry a positive output limit"
        raise ToolDescriptorError(msg)

    definition = session.scalar(select(ToolDefinition).where(ToolDefinition.key == key))
    if definition is None:
        msg = f"no tool registered under key {key!r}"
        raise DefinitionNotFoundError(msg)

    highest = session.scalar(
        select(func.max(ToolDefinitionVersion.version_no)).where(
            ToolDefinitionVersion.tool_definition_id == definition.id
        )
    )
    version = ToolDefinitionVersion(
        tool_definition_id=definition.id,
        version_no=int(highest or 0) + 1,
        input_schema_json=canonicalize(input_schema).decode("utf-8"),
        output_schema_json=canonicalize(output_schema).decode("utf-8"),
        timeout_seconds=timeout_seconds,
        max_output_bytes=max_output_bytes,
        required_scopes_json=canonicalize(sorted(required_scopes)).decode("utf-8"),
    )
    session.add(version)
    session.flush()
    return version


def resolve_tool_version(
    session: Session, *, key: str, version_no: int | None = None
) -> ToolDefinitionVersion:
    """Return the tool version a task should pin.

    With ``version_no``, the exact version — including a deprecated one, because
    an execution that pinned it must keep reading the limits that applied to it.
    Without it, the highest version that has not been deprecated.

    Raises:
        DefinitionNotFoundError: no tool, or no such version number.
        NoPublishableVersionError: nothing published, or everything deprecated.
    """
    definition = session.scalar(select(ToolDefinition).where(ToolDefinition.key == key))
    if definition is None:
        msg = f"no tool registered under key {key!r}"
        raise DefinitionNotFoundError(msg)

    query = select(ToolDefinitionVersion).where(
        ToolDefinitionVersion.tool_definition_id == definition.id
    )
    if version_no is not None:
        version = session.scalar(query.where(ToolDefinitionVersion.version_no == version_no))
        if version is None:
            msg = f"tool {key!r} has no version {version_no}"
            raise DefinitionNotFoundError(msg)
        return version

    latest = session.scalar(
        query.where(not_deprecated(DefinitionKind.TOOL, ToolDefinitionVersion.id))
        .order_by(ToolDefinitionVersion.version_no.desc())
        .limit(1)
    )
    if latest is None:
        msg = f"tool {key!r} has no version a task may pin"
        raise NoPublishableVersionError(msg)
    return latest


def required_scopes(version: ToolDefinitionVersion) -> frozenset[str]:
    """The scopes a grant must carry for this version to run."""
    loaded: list[str] = json.loads(version.required_scopes_json)
    return frozenset(loaded)
