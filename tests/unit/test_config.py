"""Settings validate strictly and fail fast.

These exercise the real path — values arriving from the environment — rather
than the constructor directly, because that is how the application loads them.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from adw import config
from adw.config import AppEnv, Settings, get_settings


@pytest.mark.unit
def test_settings_load_from_environment(env_settings: None) -> None:
    settings = get_settings()
    assert settings.app_env is AppEnv.TEST
    assert settings.database_url.scheme == "postgresql+psycopg"
    assert settings.is_dev is False


@pytest.mark.unit
def test_missing_database_url_is_rejected(
    env_settings: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("ADW_DATABASE_URL", raising=False)
    config.get_settings.cache_clear()
    with pytest.raises(ValidationError):
        get_settings()


@pytest.mark.unit
def test_non_psycopg_driver_is_rejected(
    env_settings: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A URL without the pinned driver must not be accepted silently."""
    monkeypatch.setenv("ADW_DATABASE_URL", "postgresql://adw_owner:pw@localhost:5432/adw_dev")
    config.get_settings.cache_clear()
    with pytest.raises(ValidationError) as excinfo:
        get_settings()
    assert "postgresql+psycopg" in str(excinfo.value)


@pytest.mark.unit
def test_unknown_key_in_env_file_is_rejected(
    env_settings: None, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """extra='forbid' turns a typo in .env into a startup failure, not a silent default."""
    for key in ("ADW_APP_ENV", "ADW_DATABASE_URL", "ADW_LOG_LEVEL"):
        monkeypatch.delenv(key, raising=False)
    env_file = tmp_path / "dotenv"
    env_file.write_text(
        "ADW_APP_ENV=test\n"
        "ADW_DATABASE_URL=postgresql+psycopg://adw_owner:pw@localhost:5432/adw_dev\n"
        "ADW_DATABSE_URL=typo\n",
        encoding="utf-8",
    )
    with pytest.raises(ValidationError):
        # _env_file is a runtime kwarg of BaseSettings that mypy cannot see.
        Settings(_env_file=str(env_file))  # type: ignore[call-arg]


@pytest.mark.unit
def test_unrecognised_environment_variable_is_ignored(
    env_settings: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Documented limitation, verified rather than assumed.

    ``extra="forbid"`` guards the .env *file*. pydantic-settings deliberately
    ignores unrecognised environment variables, even prefixed ones, so a typo
    such as ``ADW_DATABSE_URL`` exported in a shell is silently inert. Anything
    relying on env vars being validated must not assume otherwise.
    """
    monkeypatch.setenv("ADW_DATABSE_URL", "typo")
    config.get_settings.cache_clear()
    assert get_settings().app_env is AppEnv.TEST


@pytest.mark.unit
def test_unknown_environment_is_rejected(
    env_settings: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("ADW_APP_ENV", "production")
    config.get_settings.cache_clear()
    with pytest.raises(ValidationError):
        get_settings()


@pytest.mark.unit
def test_settings_are_frozen(env_settings: None) -> None:
    """Configuration cannot drift at runtime."""
    with pytest.raises(ValidationError):
        get_settings().log_level = "DEBUG"
