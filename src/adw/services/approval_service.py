"""Human approval — D4, D6, D7, I5.

Every execution ends in a human gate (D6): a fully autonomous execution does not
exist in this product. This service owns those gates, their SLA, and their
escalation.

**Expiry never approves.** D7 states that a timeout must never auto-approve,
auto-reject, or silently proceed. An execution that hangs forever is bad; one
that approves itself because nobody looked is catastrophic, and would directly
violate `CLAUDE.md` §3. So expiry moves the item to ``expired`` — a state that
demands explicit human action and produces no verdict at all.

The requester and the producer are never eligible (D4, `PRODUCT.md` §18). The
database refuses the row too; the refusals here exist so a caller gets an
explanation rather than a constraint violation.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime, timedelta
from typing import Final
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from adw.domain.errors import DomainError
from adw.domain.states import ApprovalState, GateVerdict
from adw.models.artifact import ArtifactVersion
from adw.models.gate import ApprovalItem, GateDecision, GateDefinitionVersion
from adw.ports.keystore import KeyStore
from adw.services import audit_writer, gate_engine

DEFAULT_SLA_HOURS: Final = 72
"""D7. Calendar hours; business-hours handling is an open item in that decision."""

EVENT_APPROVAL_REQUESTED: Final = "approval.requested"
EVENT_APPROVAL_DECIDED: Final = "approval.decided"
EVENT_APPROVAL_EXPIRED: Final = "approval.expired"
EVENT_APPROVAL_ESCALATED: Final = "approval.escalated"


class IneligibleApproverError(DomainError):
    """The requester or the producer attempted to decide their own work."""


class ApprovalNotPendingError(DomainError):
    """A decision was attempted on an item that is no longer pending."""


def _database_now(session: Session) -> datetime:
    now: datetime = session.execute(select(func.transaction_timestamp())).scalar_one()
    return now


def request_approval(
    session: Session,
    *,
    artifact_version: ArtifactVersion,
    gate_definition_version: GateDefinitionVersion,
    task_id: UUID,
    requester_identity: str,
    keystore: KeyStore,
    actor_id: str,
    sla_hours: int = DEFAULT_SLA_HOURS,
) -> ApprovalItem:
    """Open a human gate, with its deadline computed from the database clock.

    Using the same clock for the deadline a user sees and the deadline the
    scheduler enforces is what stops the two diverging (D21).
    """
    now = _database_now(session)
    item = ApprovalItem(
        tenant_id=artifact_version.tenant_id,
        artifact_version_id=artifact_version.id,
        gate_definition_version_id=gate_definition_version.id,
        task_id=task_id,
        state=ApprovalState.PENDING,
        producer_identity=artifact_version.producing_agent_identity,
        requester_identity=requester_identity,
        sla_deadline=now + timedelta(hours=sla_hours),
    )
    session.add(item)
    session.flush()

    audit_writer.append(
        session,
        tenant_id=item.tenant_id,
        event_type=EVENT_APPROVAL_REQUESTED,
        actor_id=actor_id,
        payload={
            "approval_item_id": str(item.id),
            "artifact_version_id": str(artifact_version.id),
            "producer_identity": item.producer_identity,
            "requester_identity": requester_identity,
            "sla_deadline": item.sla_deadline.isoformat(timespec="microseconds"),
        },
        keystore=keystore,
    )
    return item


def is_eligible(item: ApprovalItem, identity: str) -> bool:
    """Whether ``identity`` may decide ``item``."""
    return identity not in (item.producer_identity, item.requester_identity)


def decide(
    session: Session,
    *,
    item: ApprovalItem,
    approved: bool,
    decided_by_identity: str,
    keystore: KeyStore,
    actor_id: str,
    failure_detail: str | None = None,
) -> GateDecision:
    """Record a human verdict and the gate decision it produces.

    Raises:
        IneligibleApproverError: if the decider produced or requested the work.
        ApprovalNotPendingError: if the item has already been decided or expired.
    """
    if item.state is not ApprovalState.PENDING:
        msg = f"approval item is {item.state.value!r}, not pending"
        raise ApprovalNotPendingError(msg)
    if not is_eligible(item, decided_by_identity):
        role = "produced" if decided_by_identity == item.producer_identity else "requested"
        msg = f"{decided_by_identity!r} {role} this work and cannot approve it"
        raise IneligibleApproverError(msg)

    artifact_version = session.get(ArtifactVersion, item.artifact_version_id)
    gate_version = session.get(GateDefinitionVersion, item.gate_definition_version_id)
    if artifact_version is None or gate_version is None:
        msg = "approval item references an artifact version or gate definition that is not visible"
        raise ApprovalNotPendingError(msg)

    decision = gate_engine.record_decision(
        session,
        artifact_version=artifact_version,
        gate_definition_version=gate_version,
        task_id=item.task_id,
        verdict=GateVerdict.PASS if approved else GateVerdict.FAIL,
        decided_by_identity=decided_by_identity,
        keystore=keystore,
        actor_id=actor_id,
        failure_detail=failure_detail,
    )

    item.state = ApprovalState.APPROVED if approved else ApprovalState.REJECTED
    item.decided_by_identity = decided_by_identity
    item.decided_at = decision.decided_at
    item.gate_decision_id = decision.id
    session.flush()

    audit_writer.append(
        session,
        tenant_id=item.tenant_id,
        event_type=EVENT_APPROVAL_DECIDED,
        actor_id=actor_id,
        payload={
            "approval_item_id": str(item.id),
            "state": item.state.value,
            "decided_by_identity": decided_by_identity,
            "gate_decision_id": str(decision.id),
        },
        keystore=keystore,
    )
    return decision


def overdue(session: Session, *, now: datetime | None = None) -> Sequence[ApprovalItem]:
    """Return pending items whose deadline has passed."""
    moment = now if now is not None else _database_now(session)
    return session.scalars(
        select(ApprovalItem)
        .where(ApprovalItem.state == ApprovalState.PENDING, ApprovalItem.sla_deadline < moment)
        .order_by(ApprovalItem.sla_deadline)
    ).all()


def expire(
    session: Session,
    *,
    item: ApprovalItem,
    keystore: KeyStore,
    actor_id: str,
) -> ApprovalItem:
    """Move an overdue item to ``expired``.

    **Produces no verdict and no gate decision.** D7: expiry must never
    auto-approve, auto-reject, or silently proceed — it demands explicit human
    action, and an expired item still has nobody's name on it.
    """
    if item.state is not ApprovalState.PENDING:
        msg = f"approval item is {item.state.value!r}, not pending"
        raise ApprovalNotPendingError(msg)

    item.state = ApprovalState.EXPIRED
    item.decided_at = _database_now(session)
    session.flush()

    audit_writer.append(
        session,
        tenant_id=item.tenant_id,
        event_type=EVENT_APPROVAL_EXPIRED,
        actor_id=actor_id,
        payload={
            "approval_item_id": str(item.id),
            "sla_deadline": item.sla_deadline.isoformat(timespec="microseconds"),
            "verdict": None,
            "requires_human_action": True,
        },
        keystore=keystore,
    )
    return item


def run_expiry_pass(
    session: Session, *, keystore: KeyStore, actor_id: str, now: datetime | None = None
) -> int:
    """Expire every overdue item and return how many were expired."""
    expired = 0
    for item in overdue(session, now=now):
        expire(session, item=item, keystore=keystore, actor_id=actor_id)
        expired += 1
    return expired


def escalate(
    session: Session,
    *,
    item: ApprovalItem,
    escalated_to: str,
    keystore: KeyStore,
    actor_id: str,
) -> ApprovalItem:
    """Record an explicit, audited escalation.

    Escalation is a deliberate act (D7), never an implicit consequence of time
    passing. Who it escalates *to* remains an open item in that decision, so the
    target is supplied by the caller rather than resolved here.
    """
    item.escalated_at = _database_now(session)
    item.escalated_to = escalated_to
    session.flush()

    audit_writer.append(
        session,
        tenant_id=item.tenant_id,
        event_type=EVENT_APPROVAL_ESCALATED,
        actor_id=actor_id,
        payload={
            "approval_item_id": str(item.id),
            "escalated_to": escalated_to,
            "state": item.state.value,
        },
        keystore=keystore,
    )
    return item
