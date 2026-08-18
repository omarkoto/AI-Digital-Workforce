"""Tool permission grants — D10, I9, B3.

Grants are **declared at task creation and never afterwards**. There is no
function here that adds a permission to a running task, and that absence is the
feature: it is what makes "an agent cannot acquire a capability it did not start
with" a property of the code rather than a promise about it.

Three things can end a grant, and none of them edits the authorization:

* **expiry** — time-boxed from the database clock (D21/G6), so the expiry the
  gateway enforces and the expiry a console shows cannot diverge;
* **revocation** — an explicit, audited, one-way act;
* **the task ending** — which the gateway checks, because a grant outliving its
  task would be a permission with no owner.

Per B4, none of these interrupts a call already executing. They take effect at
the next invocation, which is the only boundary where enforcement leaves an
honest record.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from adw.domain.canonical import canonicalize
from adw.domain.errors import DomainError
from adw.models.grant import DEFAULT_GRANT_TTL_SECONDS, ToolGrant
from adw.models.tool import ToolDefinitionVersion
from adw.ports.keystore import KeyStore
from adw.services import audit_writer, tool_registry

EVENT_GRANTS_DECLARED = "grant.declared"
EVENT_GRANT_REVOKED = "grant.revoked"


class GrantError(DomainError):
    """A grant operation was refused."""


@dataclass(frozen=True, slots=True)
class GrantRequest:
    """One permission to declare when a task is created.

    Carries the resolved tool version rather than a key, so the caller has
    already decided *which descriptor* is being authorized. A grant that resolved
    its own version at creation could authorize something newer than whoever
    declared it reviewed.
    """

    tool_version: ToolDefinitionVersion
    scopes: tuple[str, ...] = ()
    ttl_seconds: int = DEFAULT_GRANT_TTL_SECONDS


def _database_now(session: Session) -> datetime:
    now: datetime = session.execute(select(func.transaction_timestamp())).scalar_one()
    return now


def declare(
    session: Session,
    *,
    tenant_id: UUID,
    task_id: UUID,
    requests: Sequence[GrantRequest],
    keystore: KeyStore,
    actor_id: str,
) -> list[ToolGrant]:
    """Declare a task's complete permission set, once, at creation.

    Called only from ``task_service.create_task``, in the same transaction and
    the same audit event as the definition pins — so a task's capability and its
    instructions become durable together or not at all.

    Raises:
        GrantError: on a non-positive TTL, or two grants for the same tool.
    """
    seen: set[UUID] = set()
    granted: list[ToolGrant] = []
    now = _database_now(session)

    for request in requests:
        if request.ttl_seconds <= 0:
            msg = "a grant must have a positive lifetime; an expired grant authorizes nothing"
            raise GrantError(msg)
        definition_id = request.tool_version.tool_definition_id
        if definition_id in seen:
            msg = (
                "a task may hold only one version of a tool; a grant reviewed against "
                "one descriptor must not silently come to mean another"
            )
            raise GrantError(msg)
        seen.add(definition_id)

        grant = ToolGrant(
            tenant_id=tenant_id,
            task_id=task_id,
            tool_definition_id=definition_id,
            tool_definition_version_id=request.tool_version.id,
            scopes_json=canonicalize(sorted(request.scopes)).decode("utf-8"),
            expires_at=now + timedelta(seconds=request.ttl_seconds),
        )
        session.add(grant)
        granted.append(grant)

    session.flush()

    if granted:
        audit_writer.append(
            session,
            tenant_id=tenant_id,
            event_type=EVENT_GRANTS_DECLARED,
            actor_id=actor_id,
            payload={
                "task_id": str(task_id),
                "grants": [
                    {
                        "grant_id": str(grant.id),
                        "tool_definition_version_id": str(grant.tool_definition_version_id),
                        "scopes": json.loads(grant.scopes_json),
                        "expires_at": grant.expires_at.isoformat(),
                    }
                    for grant in granted
                ],
            },
            keystore=keystore,
        )
    return granted


def for_task(session: Session, task_id: UUID) -> list[ToolGrant]:
    """Every grant declared for a task, revoked and expired ones included.

    The full declared set, because "what was this task ever allowed to do?" is a
    different question from "what may it do now", and the record has to answer
    both.
    """
    return list(session.execute(select(ToolGrant).where(ToolGrant.task_id == task_id)).scalars())


def find(session: Session, *, task_id: UUID, tool_definition_id: UUID) -> ToolGrant | None:
    """The grant a task holds for one tool, whatever state it is in."""
    return session.scalar(
        select(ToolGrant).where(
            ToolGrant.task_id == task_id,
            ToolGrant.tool_definition_id == tool_definition_id,
        )
    )


def scopes(grant: ToolGrant) -> frozenset[str]:
    loaded: list[str] = json.loads(grant.scopes_json)
    return frozenset(loaded)


def is_live(grant: ToolGrant, *, now: datetime) -> bool:
    """Whether this grant authorizes anything at ``now``."""
    return grant.revoked_at is None and now < grant.expires_at


def covers(grant: ToolGrant, version: ToolDefinitionVersion) -> bool:
    """Whether this grant authorizes exactly the descriptor being invoked.

    Identity, not compatibility. A grant reviewed against v1 does not authorize
    v2, however similar — the point of pinning is that nobody has to judge
    whether a change mattered.
    """
    return grant.tool_definition_version_id == version.id and tool_registry.required_scopes(
        version
    ) <= scopes(grant)


def revoke(
    session: Session,
    *,
    grant: ToolGrant,
    revoked_by_identity: str,
    keystore: KeyStore,
    actor_id: str,
    now: datetime | None = None,
) -> ToolGrant:
    """Withdraw a grant. One-way, audited, and effective from the next call (B4).

    A call already executing runs to completion — killing it mid-flight would
    produce an action that started, touched something, and left no trustworthy
    account of what it did.

    Raises:
        GrantError: if the grant is already revoked. Revoking twice is not a
            second fact.
    """
    if grant.revoked_at is not None:
        msg = f"grant {grant.id} is already revoked"
        raise GrantError(msg)

    grant.revoked_at = now if now is not None else _database_now(session)
    grant.revoked_by_identity = revoked_by_identity
    session.flush()

    audit_writer.append(
        session,
        tenant_id=grant.tenant_id,
        event_type=EVENT_GRANT_REVOKED,
        actor_id=actor_id,
        payload={
            "grant_id": str(grant.id),
            "task_id": str(grant.task_id),
            "tool_definition_version_id": str(grant.tool_definition_version_id),
            "revoked_by_identity": revoked_by_identity,
        },
        keystore=keystore,
    )
    return grant
