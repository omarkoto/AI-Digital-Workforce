"""Live database connectivity.

Skips unless ADW_TEST_DATABASE_URL is set. Docker is intentionally not used in
this environment, so these run against the locally installed PostgreSQL.
"""

from __future__ import annotations

import pytest
from sqlalchemy import create_engine, text


@pytest.mark.integration
def test_database_answers(live_database_url: str) -> None:
    engine = create_engine(live_database_url, pool_pre_ping=True, future=True)
    with engine.connect() as connection:
        assert connection.execute(text("SELECT 1")).scalar_one() == 1


@pytest.mark.integration
def test_server_version_meets_the_accepted_floor(live_database_url: str) -> None:
    """D19 requires PostgreSQL 16 or later."""
    engine = create_engine(live_database_url, future=True)
    with engine.connect() as connection:
        raw = str(connection.execute(text("SHOW server_version")).scalar_one())
    major = int(raw.split(".")[0])
    assert major >= 16, f"D19 requires PostgreSQL 16+, connected to {raw}"


@pytest.mark.integration
def test_connected_to_the_dedicated_project_database(live_database_url: str) -> None:
    """Guard against pointing the suite at another project's database."""
    engine = create_engine(live_database_url, future=True)
    with engine.connect() as connection:
        name = str(connection.execute(text("SELECT current_database()")).scalar_one())
    assert name.startswith("adw_"), f"expected a dedicated adw_* database, connected to {name!r}"
