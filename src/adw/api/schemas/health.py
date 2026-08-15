"""Response models for the health routes.

Pydantic guards the outbound boundary as well as the inbound one (G1): the
service returns declared shapes, not whatever a dict happened to contain.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class LivenessResponse(BaseModel):
    """The process is running. Says nothing about dependencies."""

    model_config = ConfigDict(frozen=True)

    status: Literal["ok"] = "ok"
    service: str = Field(description="Service identifier.")
    environment: str = Field(description="Configured deployment environment.")


class ReadinessResponse(BaseModel):
    """The process is running and its database answers."""

    model_config = ConfigDict(frozen=True)

    status: Literal["ready", "degraded"]
    database: Literal["up", "down"]
    server_version: str | None = Field(
        default=None,
        description="PostgreSQL server version, when reachable.",
    )
    detail: str | None = Field(
        default=None,
        description="Failure summary when the database is unreachable.",
    )
