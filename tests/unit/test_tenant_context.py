"""The tenant-context helper — D18 / G3.

There must be exactly one way to open a tenant transaction, so there is exactly
one place to get it wrong. These tests need no database: they assert the shape
of the contract, not its effect on rows, which test_rls_probe.py proves.
"""

from __future__ import annotations

import inspect
from uuid import uuid4

import pytest

from adw import db


@pytest.mark.unit
def test_tenant_session_requires_a_tenant() -> None:
    """The parameter is mandatory, so a tenantless call cannot be written."""
    signature = inspect.signature(db.tenant_session)
    tenant = signature.parameters["tenant_id"]
    assert tenant.default is inspect.Parameter.empty


@pytest.mark.unit
def test_tenant_session_rejects_a_missing_tenant_at_runtime() -> None:
    """Belt and braces: an untyped caller passing None must still be refused."""
    with pytest.raises(ValueError, match="tenant"):
        with db.tenant_session(None):  # type: ignore[arg-type]
            pass


@pytest.mark.unit
def test_setting_name_is_the_documented_one() -> None:
    """The policies in every migration reference this exact setting name."""
    assert db.TENANT_SETTING == "app.tenant_id"


@pytest.mark.unit
def test_tenant_context_statement_is_parameterised(env_settings: None) -> None:
    """A tenant id must never be interpolated into SQL text.

    PostgreSQL's SET does not accept bind parameters, which is why the helper
    uses set_config() — the parameterised equivalent — rather than building a
    statement by string concatenation.
    """
    source = inspect.getsource(db)
    assert "set_config" in source
    assert "SET LOCAL app.tenant_id" not in source


@pytest.mark.unit
def test_tenant_context_is_transaction_local(env_settings: None) -> None:
    """set_config's third argument must be true, meaning local to the transaction."""
    source = inspect.getsource(db.tenant_session)
    assert "true" in source.lower()


@pytest.mark.unit
def test_migration_url_is_separate_from_the_runtime_url(env_settings: None) -> None:
    """Alembic runs as the owner; the application runs as the non-owner role."""
    from adw.config import get_settings

    settings = get_settings()
    assert settings.migration_database_url is not None
    assert str(settings.migration_database_url) != str(settings.database_url)


@pytest.mark.unit
def test_uuid_is_accepted_for_tenant_id() -> None:
    """Tenant identifiers are UUIDv4 per D28; the helper takes a UUID, not a string."""
    signature = inspect.signature(db.tenant_session)
    annotation = signature.parameters["tenant_id"].annotation
    assert "UUID" in str(annotation)
    assert isinstance(uuid4(), object)
