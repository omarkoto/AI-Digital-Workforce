"""Alembic environment.

The URL comes from application settings, never from ``alembic.ini``, so there is
exactly one source of database configuration and no credentials in tracked files.
Specifically it comes from ``migration_database_url`` — the owner connection —
because RLS policies, grants, and roles are schema, and schema is Alembic's job.

``target_metadata`` is ``None`` in Task 1 because no models exist yet. Task 4
introduces the declarative base and sets it here.
"""

from __future__ import annotations

from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

from adw.config import get_settings

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# Migrations run as adw_owner, never as the runtime role: DDL belongs to
# migrations, and the application must not hold it (D18/G3).
config.set_main_option("sqlalchemy.url", str(get_settings().migration_database_url))

target_metadata = None


def run_migrations_offline() -> None:
    """Emit SQL to stdout without connecting."""
    context.configure(
        url=config.get_main_option("sqlalchemy.url"),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Connect and run migrations against the live database."""
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
