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

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def pytest_configure(config: pytest.Config) -> None:
    """Load local environment files before any test runs.

    Two files, deliberately separate:

    * ``.env`` holds application settings and nothing else, because
      ``Settings`` uses ``extra="forbid"`` and rejects any other key outright.
    * ``.env.test`` holds test-harness connections, which have no place in the
      application's configuration.

    Existing environment variables always win, so CI supplies values directly
    and needs neither file.
    """
    for name in (".env", ".env.test"):
        path = PROJECT_ROOT / name
        if not path.is_file():
            continue
        for raw in path.read_text(encoding="utf-8").splitlines():
            line = raw.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            os.environ.setdefault(key.strip(), value.strip())


TEST_DATABASE_URL = "postgresql+psycopg://adw_app:test@localhost:5432/adw_test"
TEST_MIGRATION_DATABASE_URL = "postgresql+psycopg://adw_owner:test@localhost:5432/adw_test"


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
    monkeypatch.setenv("ADW_MIGRATION_DATABASE_URL", TEST_MIGRATION_DATABASE_URL)
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
    run against the locally installed PostgreSQL. Set PYTEST_DATABASE_URL to
    enable them.

    The separate file is deliberate. ``Settings`` uses ``extra="forbid"``, which
    rejects **any** key in ``.env`` that is not a declared setting — the prefix
    is irrelevant, and the failure is a refusal to start rather than a silent
    ignore. Test-harness variables therefore live in ``.env.test``.
    """
    url = os.environ.get("PYTEST_DATABASE_URL")
    if not url:
        pytest.skip("PYTEST_DATABASE_URL is not set; skipping integration test")
    return url
