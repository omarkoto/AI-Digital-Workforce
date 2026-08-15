"""FastAPI application factory.

The application object is built by a function rather than created at import
time so that tests can construct isolated instances.

This module wires routes and nothing else. Business logic belongs in
``adw.services`` (PHASE-1-IMPLEMENTATION-PLAN §2).
"""

from __future__ import annotations

import logging

from fastapi import FastAPI

from adw.api.routes import health
from adw.config import get_settings

__version__ = "0.1.0"


def create_app() -> FastAPI:
    """Construct the ASGI application."""
    settings = get_settings()
    logging.basicConfig(level=settings.log_level)

    app = FastAPI(
        title="AI Digital Workforce — Execution Record Core",
        version=__version__,
        summary="Phase 1 foundation. Domain surface is not yet implemented.",
        docs_url="/docs" if settings.is_dev else None,
        redoc_url=None,
    )
    app.include_router(health.router)
    return app
