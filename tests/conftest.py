"""Shared test fixtures.

Unit tests must not depend on a database. Integration tests skip cleanly when
one is not configured, so the unit suite stays runnable anywhere.
"""

from __future__ import annotations

import os
from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

TEST_DATABASE_URL = "postgresql+psycopg://adw_owner:test@localhost:5432/adw_test"


@pytest.fixture
def env_settings(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Iterator[None]:
    """Provide a valid, self-contained settings environment.

    Two isolations matter here:

    * Cached settings and engine accessors are cleared before and after, so a
      test never inherits another test's configuration.
    * The working directory is moved to an empty temporary directory. ``Settings``
      resolves ``env_file=".env"`` relative to the current directory, so without
      this a developer's real ``.env`` silently satisfies values a test is trying
      to prove are absent. That made the suite pass on a clean checkout and fail
      on a configured machine.
    """
    from adw import config, db

    monkeypatch.chdir(tmp_path)

    for key in list(os.environ):
        if key.startswith("ADW_"):
            monkeypatch.delenv(key, raising=False)

    monkeypatch.setenv("ADW_APP_ENV", "test")
    monkeypatch.setenv("ADW_DATABASE_URL", TEST_DATABASE_URL)
    monkeypatch.setenv("ADW_LOG_LEVEL", "WARNING")

    config.get_settings.cache_clear()
    db.get_engine.cache_clear()
    db.get_session_factory.cache_clear()
    yield
    config.get_settings.cache_clear()
    db.get_engine.cache_clear()
    db.get_session_factory.cache_clear()


@pytest.fixture
def client(env_settings: None) -> Iterator[TestClient]:
    """A test client over a freshly constructed application."""
    from adw.api.app import create_app

    with TestClient(create_app()) as test_client:
        yield test_client


@pytest.fixture
def live_database_url() -> str:
    """Return a live database URL, or skip the test.

    Docker is intentionally not used in this environment, so integration tests
    run against the locally installed PostgreSQL. Set ADW_TEST_DATABASE_URL to
    enable them.
    """
    url = os.environ.get("ADW_TEST_DATABASE_URL")
    if not url:
        pytest.skip("ADW_TEST_DATABASE_URL is not set; skipping integration test")
    return url
