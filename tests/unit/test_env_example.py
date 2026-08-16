"""`.env.example` must stay consistent with `Settings`.

This exists because of a real failure. `Settings` uses ``extra="forbid"``, which
rejects unknown keys **in the .env file** — so an ``ADW_``-prefixed variable that
is not a real setting does not get ignored, it stops the application from
starting. Test-harness variables therefore use a ``PYTEST_`` prefix and live
outside the application's namespace.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from adw.config import Settings

ENV_EXAMPLE = Path(__file__).resolve().parents[2] / ".env.example"
KEY = re.compile(r"^(?P<commented>#\s*)?(?P<key>[A-Z][A-Z0-9_]*)=", re.MULTILINE)


def declared_keys() -> set[str]:
    return {f"ADW_{name.upper()}" for name in Settings.model_fields}


@pytest.mark.unit
def test_env_example_exists() -> None:
    assert ENV_EXAMPLE.is_file()


@pytest.mark.unit
def test_every_adw_key_in_the_example_is_a_real_setting() -> None:
    """An ADW_ key that is not a field would break startup, not be ignored."""
    text = ENV_EXAMPLE.read_text(encoding="utf-8")
    found = {m.group("key") for m in KEY.finditer(text) if m.group("key").startswith("ADW_")}
    unknown = found - declared_keys()
    assert not unknown, (
        f"unknown ADW_ keys in .env.example: {sorted(unknown)}. "
        "Test-harness variables must use the PYTEST_ prefix."
    )


@pytest.mark.unit
def test_every_required_setting_appears_in_the_example() -> None:
    """A required setting missing from the template is a setup trap."""
    text = ENV_EXAMPLE.read_text(encoding="utf-8")
    present = {m.group("key") for m in KEY.finditer(text)}
    required = {
        f"ADW_{name.upper()}"
        for name, field in Settings.model_fields.items()
        if field.is_required()
    }
    assert required <= present, f"missing from .env.example: {sorted(required - present)}"


@pytest.mark.unit
def test_the_example_contains_no_real_password() -> None:
    text = ENV_EXAMPLE.read_text(encoding="utf-8")
    for line in text.splitlines():
        if "://" in line and "@" in line:
            credentials = line.split("://", 1)[1].split("@", 1)[0]
            assert "REPLACE_WITH" in credentials, f"non-placeholder credential: {line}"
