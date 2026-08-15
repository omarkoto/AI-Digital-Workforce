"""Application settings.

Settings are loaded once, validated by Pydantic, and fail fast. A missing or
malformed value stops the process at import time rather than surfacing as a
confusing failure later.

Per D16 (G1), Pydantic guards every trust boundary; configuration is the first
of them.
"""

from __future__ import annotations

from enum import StrEnum
from functools import lru_cache

from pydantic import Field, PostgresDsn, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class AppEnv(StrEnum):
    """Deployment environment.

    This is not cosmetic. Development-only adapters — the local key store, the
    local blob store, and the stub authenticator introduced in later tasks —
    are required to refuse to start unless the environment is ``dev``
    (PHASE-1-IMPLEMENTATION-PLAN §33.2 rule 3).
    """

    DEV = "dev"
    TEST = "test"
    STAGING = "staging"
    PROD = "prod"


class Settings(BaseSettings):
    """Validated application configuration."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        env_prefix="ADW_",
        extra="forbid",
        frozen=True,
    )

    app_env: AppEnv = Field(
        default=AppEnv.DEV,
        description="Deployment environment. Gates development-only adapters.",
    )
    database_url: PostgresDsn = Field(
        description="SQLAlchemy URL for the dedicated project database.",
    )
    log_level: str = Field(default="INFO")

    @field_validator("database_url")
    @classmethod
    def _require_psycopg_driver(cls, value: PostgresDsn) -> PostgresDsn:
        """Pin the driver explicitly.

        SQLAlchemy would otherwise pick a default DBAPI. Naming ``psycopg``
        keeps the driver a deliberate choice rather than an environment
        accident.
        """
        if value.scheme != "postgresql+psycopg":
            msg = f"database_url scheme must be 'postgresql+psycopg', got {value.scheme!r}"
            raise ValueError(msg)
        return value

    @property
    def is_dev(self) -> bool:
        return self.app_env is AppEnv.DEV


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return the process-wide settings, constructed once."""
    return Settings()  # type: ignore[call-arg]  # values come from env/.env
