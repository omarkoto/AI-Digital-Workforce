"""Cost accounting and hard stops — `PRODUCT.md` §25, D11.

Limits here are **hard stops, not alerts**. The one rule that shapes every
decision in this module:

    A breach never silently truncates work. It pauses and escalates.

Producing a partial artifact because the budget ran out, without saying so,
would violate the platform's core claim. So the stop happens **before** a call,
never by cutting a response short: an unmade call leaves an honest record —
"stopped, budget exhausted" — while a truncated one leaves an answer that looks
complete and is not.

Continuing after exhaustion is an explicit, audited act that raises the ceiling
and names who authorized it. It is deliberately not a retry that quietly
succeeds because a counter was reset.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from adw.domain.errors import DomainError
from adw.models.action import Action
from adw.models.cost import ActionCost, ExecutionBudget
from adw.ports.keystore import KeyStore
from adw.ports.llm import CompletionResponse
from adw.services import audit_writer

EVENT_BUDGET_SET = "budget.set"
EVENT_BUDGET_WARNING = "budget.warning"
EVENT_BUDGET_EXHAUSTED = "budget.exhausted"
EVENT_BUDGET_AUTHORIZED = "budget.authorized"

DEFAULT_WARN_AT_RATIO = 0.8
"""`PRODUCT.md` §25: warn at 80%, pause at 100%."""


class BudgetError(DomainError):
    """A budget operation was refused."""


class BudgetStatus(StrEnum):
    """How much room is left. Persisted vocabulary, not a log string."""

    UNLIMITED = "unlimited"
    """No budget is configured for this execution. Explicit rather than implied,
    so an unbudgeted execution is visible as a choice rather than an oversight."""

    OK = "ok"
    WARNING = "warning"
    """At or past the warning ratio. Work continues; someone is told."""

    EXHAUSTED = "exhausted"
    """At or past the ceiling. No further model call may start."""


@dataclass(frozen=True, slots=True)
class BudgetReading:
    """What has been spent against what was allowed."""

    status: BudgetStatus
    spent_tokens: int
    limit_tokens: int | None

    @property
    def may_continue(self) -> bool:
        return self.status is not BudgetStatus.EXHAUSTED

    @property
    def remaining_tokens(self) -> int | None:
        if self.limit_tokens is None:
            return None
        return max(self.limit_tokens - self.spent_tokens, 0)


# --- Recording --------------------------------------------------------------


def record_usage(
    session: Session,
    *,
    action: Action,
    execution_id: UUID,
    response: CompletionResponse,
) -> ActionCost:
    """Record what one action consumed, in a form that can be summed.

    The same figures are already inside the action's evidence, encrypted. This is
    the summable copy: a budget that has to decrypt every payload to know what
    has been spent is a budget that never gets checked. It carries counts and
    attribution only — no prompt, no completion, and never a credential.
    """
    cost = ActionCost(
        tenant_id=action.tenant_id,
        action_id=action.id,
        execution_id=execution_id,
        provider=response.provider,
        model=response.model,
        prompt_tokens=response.usage.prompt_tokens,
        completion_tokens=response.usage.completion_tokens,
    )
    session.add(cost)
    session.flush()
    return cost


def spend_for_execution(session: Session, execution_id: UUID) -> int:
    """Total tokens recorded against one execution."""
    total = session.scalar(
        select(
            func.coalesce(func.sum(ActionCost.prompt_tokens + ActionCost.completion_tokens), 0)
        ).where(ActionCost.execution_id == execution_id)
    )
    return int(total or 0)


# --- Budgets ----------------------------------------------------------------


def set_budget(
    session: Session,
    *,
    tenant_id: UUID,
    execution_id: UUID,
    max_total_tokens: int,
    warn_at_ratio: float = DEFAULT_WARN_AT_RATIO,
    keystore: KeyStore,
    actor_id: str,
) -> ExecutionBudget:
    """Set the token ceiling for one execution.

    Tenant-configurable per `PRODUCT.md` §25, which is why there is no default
    here: a platform-wide number would be wrong for every tenant it was not
    chosen for.
    """
    if max_total_tokens <= 0:
        msg = "a budget must be positive; use no budget at all to mean unlimited"
        raise BudgetError(msg)

    existing = get_budget(session, execution_id)
    if existing is not None:
        msg = f"execution {execution_id} already has a budget; raise it via authorize_additional"
        raise BudgetError(msg)

    budget = ExecutionBudget(
        tenant_id=tenant_id,
        execution_id=execution_id,
        max_total_tokens=max_total_tokens,
        warn_at_ratio=warn_at_ratio,
    )
    session.add(budget)
    session.flush()

    audit_writer.append(
        session,
        tenant_id=tenant_id,
        event_type=EVENT_BUDGET_SET,
        actor_id=actor_id,
        payload={
            "execution_id": str(execution_id),
            "max_total_tokens": max_total_tokens,
            "warn_at_ratio": warn_at_ratio,
        },
        keystore=keystore,
    )
    return budget


def get_budget(session: Session, execution_id: UUID) -> ExecutionBudget | None:
    return session.scalar(
        select(ExecutionBudget).where(ExecutionBudget.execution_id == execution_id)
    )


def read_budget(session: Session, execution_id: UUID) -> BudgetReading:
    """Return spend against the ceiling, without changing anything.

    An execution with no budget reads as ``UNLIMITED`` rather than ``OK``, so an
    unbudgeted execution is visible as a choice rather than mistaken for one
    comfortably within its limits.
    """
    spent = spend_for_execution(session, execution_id)
    budget = get_budget(session, execution_id)
    if budget is None:
        return BudgetReading(status=BudgetStatus.UNLIMITED, spent_tokens=spent, limit_tokens=None)

    limit = budget.max_total_tokens
    if spent >= limit:
        status = BudgetStatus.EXHAUSTED
    elif spent >= limit * budget.warn_at_ratio:
        status = BudgetStatus.WARNING
    else:
        status = BudgetStatus.OK
    return BudgetReading(status=status, spent_tokens=spent, limit_tokens=limit)


def check_before_spending(
    session: Session,
    *,
    tenant_id: UUID,
    execution_id: UUID,
    keystore: KeyStore,
    actor_id: str,
) -> BudgetReading:
    """Read the budget and record what it says, before any call is made.

    Called *before* a model call, never after, which is what makes the stop a
    pause rather than a truncation. Warning and exhaustion are both audit events:
    a limit that fired and left no record is indistinguishable from one that was
    never configured.
    """
    reading = read_budget(session, execution_id)

    if reading.status is BudgetStatus.EXHAUSTED:
        audit_writer.append(
            session,
            tenant_id=tenant_id,
            event_type=EVENT_BUDGET_EXHAUSTED,
            actor_id=actor_id,
            payload={
                "execution_id": str(execution_id),
                "spent_tokens": reading.spent_tokens,
                "limit_tokens": reading.limit_tokens,
            },
            keystore=keystore,
        )
    elif reading.status is BudgetStatus.WARNING:
        audit_writer.append(
            session,
            tenant_id=tenant_id,
            event_type=EVENT_BUDGET_WARNING,
            actor_id=actor_id,
            payload={
                "execution_id": str(execution_id),
                "spent_tokens": reading.spent_tokens,
                "limit_tokens": reading.limit_tokens,
            },
            keystore=keystore,
        )
    return reading


def authorize_additional(
    session: Session,
    *,
    tenant_id: UUID,
    execution_id: UUID,
    additional_tokens: int,
    authorized_by_identity: str,
    keystore: KeyStore,
    actor_id: str,
) -> ExecutionBudget:
    """Raise an execution's ceiling, on a named human's authority.

    This is `PRODUCT.md` §25's "requires human authorization to continue", and it
    is why the budget row is mutable while ``action_cost`` is not: the ceiling is
    a decision someone makes, the spend is a fact that happened.

    Raises:
        BudgetError: if no budget exists, or the increase is not positive.
    """
    if additional_tokens <= 0:
        msg = "an authorization must add tokens; a reduction is not an authorization"
        raise BudgetError(msg)

    budget = get_budget(session, execution_id)
    if budget is None:
        msg = f"execution {execution_id} has no budget to raise"
        raise BudgetError(msg)

    previous = budget.max_total_tokens
    budget.max_total_tokens = previous + additional_tokens
    budget.authorized_by_identity = authorized_by_identity
    session.flush()

    audit_writer.append(
        session,
        tenant_id=tenant_id,
        event_type=EVENT_BUDGET_AUTHORIZED,
        actor_id=actor_id,
        payload={
            "execution_id": str(execution_id),
            "previous_max_total_tokens": previous,
            "max_total_tokens": budget.max_total_tokens,
            "authorized_by_identity": authorized_by_identity,
        },
        keystore=keystore,
    )
    return budget
