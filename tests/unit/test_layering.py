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
def test_ports_depend_on_no_adapter() -> None:
    """A port that knows its adapters is not a boundary."""
    for module in _modules_under("ports"):
        for imported in _imports(module):
            assert not imported.startswith("adw.adapters"), (
                f"{module.relative_to(SRC)} imports {imported!r}; a port must not know an adapter"
            )


@pytest.mark.unit
def test_the_runtime_depends_on_the_llm_port_and_never_on_a_provider() -> None:
    """D8: swapping providers, or running the suite on the fake, must not touch
    the runtime. An import here is how that guarantee would quietly disappear."""
    for module in _modules_under("runtime"):
        for imported in _imports(module):
            assert not imported.startswith("adw.adapters"), (
                f"{module.relative_to(SRC)} imports {imported!r}; "
                "the Agent Runtime may depend only on adw.ports.llm"
            )
        assert "httpx" not in _imports(module), (
            f"{module.relative_to(SRC)} imports an HTTP client; "
            "transport belongs to an adapter, not the runtime"
        )


@pytest.mark.unit
def test_only_the_tool_gateway_resolves_secrets() -> None:
    """`CLAUDE.md` §4: a secret is resolved at the tool boundary and nowhere else.

    `ARCHITECTURE.md` §13 makes the gateway the only component that touches
    secrets, so concentrating that capability is only real if nothing else can
    import the port. The Agent Runtime especially — it is the least-trusted
    component in the system and must never hold a resolved credential.
    """
    permitted = {"secrets.py", "secrets_env.py", "tool_gateway.py"}
    for module in SRC.rglob("*.py"):
        if module.name in permitted:
            continue
        for imported in _imports(module):
            assert imported != "adw.ports.secrets", (
                f"{module.relative_to(SRC)} imports the secret store port; "
                "only the Tool Gateway may resolve a secret"
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
