"""Database engine, session factory, and the tenant-context boundary.

The runtime connects as ``adw_app``: not a superuser, not a table owner, and
without ``BYPASSRLS``. Every one of those exemptions would silently void the
row-level security policies, so the role holding none of them is what makes the
policies real (D18/G3).

**There is exactly one way to open a tenant transaction**, :func:`tenant_session`,
so there is exactly one place to get it wrong. It takes a tenant identifier as a
required argument, which makes a tenantless tenant transaction unwriteable
rather than merely discouraged.

Deliberately absent, and not to be added here by accident:

* Session-level tenant context. The setting is applied per *transaction*,
  because connection pooling hands the same physical connection to a different
  tenant moments later.
* Any ORM model. Those belong to Task 4 and later.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from functools import lru_cache
from typing import Final
from uuid import UUID

from sqlalchemy import Engine, create_engine, text
from sqlalchemy.orm import Session, sessionmaker

from adw.config import get_settings

TENANT_SETTING: Final = "app.tenant_id"
"""The PostgreSQL setting every row-level security policy compares against.

Policies read it as::

    USING (tenant_id = nullif(current_setting('app.tenant_id', true), '')::uuid)

When the setting is absent, ``current_setting`` returns NULL, the comparison
yields NULL rather than true, and the query sees **zero rows**. That is the
fail-closed rule in D18: a missing context returns nothing, never everything.
"""


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
    """Provide a transactional scope with **no** tenant context.

    Use only for platform-scoped work: the dispatch queue and the anchoring
    chain-head read, which are the two structures I13 permits to be read across
    tenants and which carry identifiers and hashes only.

    Any query touching tenant-owned data through this helper returns zero rows,
    because no policy can match an absent tenant setting. That is intended: it
    fails closed rather than leaking.
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


@contextmanager
def tenant_session(tenant_id: UUID) -> Iterator[Session]:
    """Provide a transactional scope bound to one tenant.

    The tenant setting is applied with ``set_config(..., is_local => true)`` as
    the first statement of the transaction, so it is discarded when the
    transaction ends and cannot survive into the next use of a pooled
    connection.

    ``set_config`` is used rather than ``SET LOCAL`` because PostgreSQL's ``SET``
    is a utility statement that accepts no bind parameters; building it by string
    concatenation would put a caller-supplied value into SQL text.

    Args:
        tenant_id: the tenant this transaction acts for. Required — there is no
            default, because a default would be a way to forget.

    Raises:
        ValueError: if no tenant identifier is supplied.
    """
    if tenant_id is None:
        # Unreachable for a type-checked caller, which is exactly why it is here:
        # the guard exists for callers the type checker never sees. Failing loudly
        # beats opening a transaction whose policy would silently match nothing.
        msg = "tenant_session requires a tenant identifier; refusing to open without one"  # type: ignore[unreachable]
        raise ValueError(msg)

    session = get_session_factory()()
    try:
        session.execute(
            text("SELECT set_config(:name, :value, true)"),
            {"name": TENANT_SETTING, "value": str(tenant_id)},
        )
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
