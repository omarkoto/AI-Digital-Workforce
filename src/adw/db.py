"""Database engine and session factory.

Task 1 scope: connectivity only. No models, no tenant context helper, no
row-level security wiring — those arrive with Task 3, which owns the database
foundation (roles, RLS policies, and the per-transaction tenant context that
D18/G3 require).

Deliberately absent, and not to be added here by accident:

* Session-level tenant context. G3 requires ``SET LOCAL`` *inside* a
  transaction, because connection pooling reuses connections across tenants.
* Any ORM model. Those belong to Task 4 and later.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from functools import lru_cache

from sqlalchemy import Engine, create_engine, text
from sqlalchemy.orm import Session, sessionmaker

from adw.config import get_settings


@lru_cache(maxsize=1)
def get_engine() -> Engine:
    """Return the process-wide SQLAlchemy engine.

    ``pool_pre_ping`` is enabled because workers hold connections across long
    idle periods while waiting on queued work.
    """
    settings = get_settings()
    return create_engine(
        str(settings.database_url),
        pool_pre_ping=True,
        future=True,
    )


@lru_cache(maxsize=1)
def get_session_factory() -> sessionmaker[Session]:
    """Return the process-wide session factory."""
    return sessionmaker(bind=get_engine(), expire_on_commit=False, future=True)


@contextmanager
def session_scope() -> Iterator[Session]:
    """Provide a transactional scope around a series of operations.

    This is *not* the tenant-scoped transaction helper. Task 3 adds that as a
    separate, explicit entry point so that opening a tenant transaction without
    a tenant is impossible by construction.
    """
    session = get_session_factory()()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def check_connection() -> bool:
    """Return ``True`` when the configured database answers a trivial query."""
    with get_engine().connect() as connection:
        result = connection.execute(text("SELECT 1")).scalar_one()
    return bool(result == 1)


def server_version() -> str:
    """Return the PostgreSQL server version string."""
    with get_engine().connect() as connection:
        return str(connection.execute(text("SHOW server_version")).scalar_one())
