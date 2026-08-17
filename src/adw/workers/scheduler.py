"""The scheduler — turns time into queued work.

Runs as a leader-elected role inside the worker pool rather than a separate
process (open decision P5's proposed default), using a PostgreSQL advisory lock.
That keeps the deployment at three processes: an advisory lock is released
automatically when the session ends, so a crashed leader does not wedge the
schedule the way a lease row would.

Owns the periodic work the platform needs and nothing else: anchoring cadence
(D20) and approval SLA expiry (D7).
"""

from __future__ import annotations

from typing import Final

from sqlalchemy import Engine, select, text
from sqlalchemy.orm import Session

SCHEDULER_LOCK_ID: Final = 8_474_201
"""An arbitrary but fixed advisory lock key. Only one holder at a time."""


def try_become_leader(session: Session) -> bool:
    """Attempt to take the scheduler lock without blocking.

    Session-scoped rather than transaction-scoped, so the leader keeps the lock
    across its whole run and releases it by disconnecting.
    """
    held: bool = session.execute(
        select(text("pg_try_advisory_lock(:key)")).params(key=SCHEDULER_LOCK_ID)
    ).scalar_one()
    return held


def release_leadership(session: Session) -> None:
    session.execute(select(text("pg_advisory_unlock(:key)")).params(key=SCHEDULER_LOCK_ID))


def run_scheduled_pass(engine: Engine, *, keystore: object, actor_id: str) -> dict[str, int]:
    """Run one scheduler tick if this process is the leader.

    Returns what each maintenance pass did. A non-leader returns zeros rather
    than raising: not being the leader is the normal case, not a fault.
    """
    from adw.ports.keystore import KeyStore
    from adw.services import anchor_writer, approval_service

    assert isinstance(keystore, KeyStore)
    result = {"anchored": 0, "expired": 0, "leader": 0}

    with Session(engine) as session:
        if not try_become_leader(session):
            return result
        result["leader"] = 1
        try:
            result["expired"] = approval_service.run_expiry_pass(
                session, keystore=keystore, actor_id=actor_id
            )
            result["anchored"] = anchor_writer.run_anchoring_pass(session)
            session.commit()
        finally:
            release_leadership(session)
    return result
