"""Module boundaries declared in PHASE-1-IMPLEMENTATION-PLAN §1 are enforced, not merely documented.

These assertions hold trivially today because the layers they guard are mostly
empty. They exist now so that the first violation fails the build rather than
being discovered during a later review.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

SRC = Path(__file__).resolve().parents[2] / "src" / "adw"


def _imports(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    found: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            found.add(node.module)
    return found


def _modules_under(package: str) -> list[Path]:
    directory = SRC / package
    return sorted(directory.rglob("*.py")) if directory.is_dir() else []


@pytest.mark.unit
def test_domain_layer_is_pure() -> None:
    """domain/ must not import SQLAlchemy, FastAPI, or any adapter."""
    forbidden = ("sqlalchemy", "fastapi", "alembic", "psycopg", "adw.adapters", "adw.models")
    for module in _modules_under("domain"):
        for imported in _imports(module):
            assert not imported.startswith(forbidden), (
                f"{module.relative_to(SRC)} imports {imported!r}; domain must stay pure"
            )


@pytest.mark.unit
def test_services_do_not_import_the_api_layer() -> None:
    for module in _modules_under("services"):
        for imported in _imports(module):
            assert not imported.startswith("adw.api"), (
                f"{module.relative_to(SRC)} imports {imported!r}; "
                "services must not depend on the API"
            )


@pytest.mark.unit
def test_no_production_module_imports_stubs() -> None:
    """Phase 1 stubs must never be reachable from a production path."""
    for module in SRC.rglob("*.py"):
        if "stubs" in module.parts:
            continue
        for imported in _imports(module):
            assert not imported.startswith("adw.stubs"), (
                f"{module.relative_to(SRC)} imports {imported!r}; stubs are test-only"
            )
