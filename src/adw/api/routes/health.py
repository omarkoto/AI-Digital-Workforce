"""Health routes.

Liveness answers "is this process up". Readiness answers "can it reach its
database". They are separate because an orchestrator restarting a live process
that merely lost its database is the wrong response.

No business logic lives here, and none may be added (PHASE-1-IMPLEMENTATION-PLAN §2).
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Response, status
from sqlalchemy.exc import SQLAlchemyError

from adw.api.schemas.health import LivenessResponse, ReadinessResponse
from adw.config import get_settings
from adw.db import check_connection, server_version

logger = logging.getLogger(__name__)

router = APIRouter(tags=["health"])


@router.get("/health", response_model=LivenessResponse, summary="Liveness probe")
def liveness() -> LivenessResponse:
    settings = get_settings()
    return LivenessResponse(service="adw", environment=str(settings.app_env))


@router.get("/health/ready", response_model=ReadinessResponse, summary="Readiness probe")
def readiness(response: Response) -> ReadinessResponse:
    try:
        check_connection()
    except SQLAlchemyError as exc:
        # The exception text can carry connection details, so it is logged for
        # operators and summarised — not echoed — to the caller.
        logger.warning("readiness check failed: %s", exc.__class__.__name__)
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
        return ReadinessResponse(
            status="degraded",
            database="down",
            detail=f"database unreachable ({exc.__class__.__name__})",
        )
    return ReadinessResponse(status="ready", database="up", server_version=server_version())
