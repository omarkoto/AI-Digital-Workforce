"""Health routes behave correctly with and without a database."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.exc import OperationalError


@pytest.mark.unit
def test_liveness_does_not_touch_the_database(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Liveness must answer even when the database is gone."""
    from adw.api.routes import health

    def _explode() -> bool:
        raise AssertionError("liveness must not query the database")

    monkeypatch.setattr(health, "check_connection", _explode)

    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "service": "adw", "environment": "test"}


@pytest.mark.unit
def test_readiness_reports_degraded_when_database_is_down(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    from adw.api.routes import health

    def _fail() -> bool:
        raise OperationalError("SELECT 1", {}, Exception("connection refused"))

    monkeypatch.setattr(health, "check_connection", _fail)

    response = client.get("/health/ready")
    assert response.status_code == 503
    body = response.json()
    assert body["status"] == "degraded"
    assert body["database"] == "down"
    assert body["server_version"] is None


@pytest.mark.unit
def test_readiness_error_detail_does_not_leak_connection_details(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The caller learns the class of failure, never the credentials in the URL."""
    from adw.api.routes import health

    secret = "s3cret-password"

    def _fail() -> bool:
        statement = f"connect to host=db user=adw_owner password={secret}"
        raise OperationalError(statement, {}, Exception())

    monkeypatch.setattr(health, "check_connection", _fail)

    response = client.get("/health/ready")
    assert secret not in response.text


@pytest.mark.unit
def test_readiness_reports_ready_when_database_answers(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    from adw.api.routes import health

    monkeypatch.setattr(health, "check_connection", lambda: True)
    monkeypatch.setattr(health, "server_version", lambda: "18.4")

    response = client.get("/health/ready")
    assert response.status_code == 200
    assert response.json() == {
        "status": "ready",
        "database": "up",
        "server_version": "18.4",
        "detail": None,
    }
