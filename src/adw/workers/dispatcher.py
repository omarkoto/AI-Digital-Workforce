"""Queue dispatch and the worker loop — D17, D18, I13.

The sequence that matters, and the reason the queue is platform-scoped:

1. **Claim** a job outside tenant context — the worker cannot know which tenant
   to open until it has read the row.
2. **Open a tenant transaction** using the claimed row's ``tenant_id``.
3. **Check idempotency**, because at-least-once delivery is the only delivery a
   database queue provides.
4. **Run the handler**, whose effects and its audit records share that one
   transaction (G2).

Per-tenant concurrency limits are applied at claim time, so one tenant's close
week cannot starve another (`PRODUCT.md` §15).
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Final
from uuid import UUID

from sqlalchemy import Engine, func, select
from sqlalchemy.orm import Session

from adw.domain.states import JobState
from adw.models.queue import DispatchJob, JobExecution

DEFAULT_TENANT_CONCURRENCY: Final = 20
"""PRODUCT.md §15's per-tenant concurrency target."""


@dataclass(frozen=True, slots=True)
class HandlerResult:
    """What a handler did, recorded in the idempotency ledger."""

    outcome: str


Handler = Callable[[Session, DispatchJob], HandlerResult]


def _now(session: Session) -> datetime:
    moment: datetime = session.execute(select(func.transaction_timestamp())).scalar_one()
    return moment


def enqueue(
    session: Session,
    *,
    tenant_id: UUID,
    job_type: str,
    target_id: UUID,
    idempotency_key: str,
    available_at: datetime | None = None,
) -> DispatchJob:
    """Add a job. Carries identifiers only — never business content (I13)."""
    moment = _now(session)
    job = DispatchJob(
        tenant_id=tenant_id,
        job_type=job_type,
        target_id=target_id,
        idempotency_key=idempotency_key,
        available_at=available_at or moment,
        state=JobState.READY,
        created_at=moment,
    )
    session.add(job)
    session.flush()
    return job


def claim(
    session: Session,
    *,
    worker_id: str,
    limit: int = 1,
    tenant_concurrency: int = DEFAULT_TENANT_CONCURRENCY,
) -> Sequence[DispatchJob]:
    """Claim up to ``limit`` ready jobs.

    ``SKIP LOCKED`` is what makes concurrent workers safe: a row another worker
    holds is passed over rather than waited on.
    """
    moment = _now(session)
    busy: dict[UUID, int] = {
        row[0]: int(row[1])
        for row in session.execute(
            select(DispatchJob.tenant_id, func.count())
            .where(DispatchJob.state == JobState.CLAIMED)
            .group_by(DispatchJob.tenant_id)
        ).all()
    }

    candidates = session.scalars(
        select(DispatchJob)
        .where(DispatchJob.state == JobState.READY, DispatchJob.available_at <= moment)
        .order_by(DispatchJob.available_at, DispatchJob.created_at)
        .limit(limit * 4)
        .with_for_update(skip_locked=True)
    ).all()

    claimed: list[DispatchJob] = []
    for job in candidates:
        if len(claimed) >= limit:
            break
        in_flight = int(busy.get(job.tenant_id, 0))
        if in_flight >= tenant_concurrency:
            continue
        job.state = JobState.CLAIMED
        job.claimed_at = moment
        job.claimed_by = worker_id
        job.attempts += 1
        busy[job.tenant_id] = in_flight + 1
        claimed.append(job)
    session.flush()
    return claimed


def already_done(session: Session, job: DispatchJob) -> JobExecution | None:
    """Return the recorded execution for this job's key, if it already ran."""
    return session.scalar(
        select(JobExecution).where(
            JobExecution.tenant_id == job.tenant_id,
            JobExecution.idempotency_key == job.idempotency_key,
        )
    )


def record_execution(session: Session, job: DispatchJob, result: HandlerResult) -> JobExecution:
    """Write the idempotency ledger entry inside the handler's transaction."""
    execution = JobExecution(
        tenant_id=job.tenant_id,
        idempotency_key=job.idempotency_key,
        job_type=job.job_type,
        outcome=result.outcome,
        completed_at=_now(session),
    )
    session.add(execution)
    session.flush()
    return execution


def run_once(
    engine: Engine,
    *,
    worker_id: str,
    handlers: dict[str, Handler],
    limit: int = 1,
) -> int:
    """Claim and run up to ``limit`` jobs. Returns how many were handled.

    Claiming and handling are separate transactions on purpose: the claim is
    platform-scoped and the handling is tenant-scoped, and a single transaction
    cannot be both.
    """
    with Session(engine) as claim_session:
        jobs = [
            (job.id, job.tenant_id, job.job_type, job.idempotency_key)
            for job in claim(claim_session, worker_id=worker_id, limit=limit)
        ]
        claim_session.commit()

    handled = 0
    for job_id, tenant_id, job_type, _key in jobs:
        handler = handlers.get(job_type)
        with Session(engine) as session:
            session.execute(select(func.set_config("app.tenant_id", str(tenant_id), True)))
            job = session.get(DispatchJob, job_id)
            if job is None:
                continue

            previous = already_done(session, job)
            if previous is not None:
                # A redelivery. Counted rather than swallowed, so the signal
                # about delivery is visible in the record.
                previous.duplicate_deliveries += 1
                job.state = JobState.DONE
                session.commit()
                continue

            if handler is None:
                job.state = JobState.FAILED
                session.commit()
                continue

            try:
                result = handler(session, job)
                record_execution(session, job, result)
                job.state = JobState.DONE
                session.commit()
                handled += 1
            except Exception:
                session.rollback()
                with Session(engine) as failure_session:
                    failed = failure_session.get(DispatchJob, job_id)
                    if failed is not None:
                        failed.state = JobState.FAILED
                        failure_session.commit()
                raise
    return handled
