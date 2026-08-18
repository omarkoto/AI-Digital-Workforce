"""The tool registry — `ARCHITECTURE.md` §13, D9, D30, `CLAUDE.md` §4.

A descriptor is what the Tool Gateway will check against, so the questions here
are the ones the gateway depends on: can a tenant forge one, can a limit change
under an execution's feet, and can a version that was pinned still be read after
it is retired.

No gateway exists yet. Nothing in this file executes anything.
"""

from __future__ import annotations

from uuid import uuid4

import pytest
from sqlalchemy import Engine, select, text
from sqlalchemy.exc import DBAPIError, ProgrammingError
from sqlalchemy.orm import Session

from adw.models.definition import DefinitionKind
from adw.models.tool import (
    DEFAULT_MAX_OUTPUT_BYTES,
    DEFAULT_TIMEOUT_SECONDS,
    ToolDefinitionVersion,
)
from adw.services import definition_service, tool_registry
from adw.services.definition_service import (
    DefinitionNotFoundError,
    DuplicateDefinitionError,
    NoPublishableVersionError,
)
from adw.services.tool_registry import ToolDescriptorError

pytestmark = pytest.mark.security

CURATOR = "lena@platform"
TOOL_KEY = "spreadsheet.read"

INPUT_SCHEMA: dict[str, object] = {
    "type": "object",
    "properties": {"blob_key": {"type": "string"}, "sheet": {"type": "string"}},
    "required": ["blob_key"],
}
OUTPUT_SCHEMA: dict[str, object] = {
    "type": "object",
    "properties": {"rows": {"type": "array"}},
    "required": ["rows"],
}


@pytest.fixture
def registered(chain_session: Session) -> Session:
    tool_registry.register_tool(
        chain_session,
        key=TOOL_KEY,
        name="Spreadsheet read",
        description="Read rows from an uploaded workbook.",
    )
    tool_registry.publish_tool_version(
        chain_session,
        key=TOOL_KEY,
        input_schema=INPUT_SCHEMA,
        output_schema=OUTPUT_SCHEMA,
        timeout_seconds=15,
        max_output_bytes=256_000,
        required_scopes=["blob:read"],
    )
    return chain_session


# --- Authoring --------------------------------------------------------------


def test_a_published_descriptor_carries_its_contract_and_limits(registered: Session) -> None:
    version = tool_registry.resolve_tool_version(registered, key=TOOL_KEY)
    assert version.version_no == 1
    assert version.timeout_seconds == 15
    assert version.max_output_bytes == 256_000
    assert tool_registry.required_scopes(version) == frozenset({"blob:read"})
    assert "blob_key" in version.input_schema_json
    assert "rows" in version.output_schema_json


def test_limits_have_defaults_so_a_descriptor_never_lacks_them(chain_session: Session) -> None:
    """`CLAUDE.md` §4 requires a timeout and a resource limit on every tool call.
    A descriptor is where that requirement is made enforceable, so neither can be
    omitted — only left at its default."""
    tool_registry.register_tool(
        chain_session, key="tabular.compute", name="Compute", description="Compute figures."
    )
    version = tool_registry.publish_tool_version(
        chain_session, key="tabular.compute", input_schema={}, output_schema={}
    )
    assert version.timeout_seconds == DEFAULT_TIMEOUT_SECONDS
    assert version.max_output_bytes == DEFAULT_MAX_OUTPUT_BYTES


@pytest.mark.parametrize(
    ("field", "value"),
    [("timeout_seconds", 0), ("timeout_seconds", -1), ("max_output_bytes", 0)],
)
def test_a_non_positive_limit_is_refused(registered: Session, field: str, value: int) -> None:
    with pytest.raises(ToolDescriptorError, match="positive"):
        tool_registry.publish_tool_version(
            registered,
            key=TOOL_KEY,
            input_schema={},
            output_schema={},
            **{field: value},  # type: ignore[arg-type]
        )


def test_the_database_refuses_a_non_positive_limit_too(registered: Session) -> None:
    """The service explains; the constraint guarantees."""
    existing = tool_registry.resolve_tool_version(registered, key=TOOL_KEY)
    registered.add(
        ToolDefinitionVersion(
            tool_definition_id=existing.tool_definition_id,
            version_no=99,
            input_schema_json="{}",
            output_schema_json="{}",
            timeout_seconds=0,
            max_output_bytes=1,
        )
    )
    with pytest.raises(DBAPIError):
        registered.flush()
    registered.rollback()


def test_schemas_are_canonicalized_so_a_diff_is_a_real_difference(
    chain_session: Session,
) -> None:
    """D23. Two descriptors that mean the same thing store identically, so a
    version-to-version comparison shows a change rather than a reordering."""
    tool_registry.register_tool(chain_session, key="t.a", name="A", description="a")
    tool_registry.register_tool(chain_session, key="t.b", name="B", description="b")
    first = tool_registry.publish_tool_version(
        chain_session, key="t.a", input_schema={"b": 1, "a": 2}, output_schema={}
    )
    second = tool_registry.publish_tool_version(
        chain_session, key="t.b", input_schema={"a": 2, "b": 1}, output_schema={}
    )
    assert first.input_schema_json == second.input_schema_json


def test_required_scopes_are_stored_in_a_stable_order(chain_session: Session) -> None:
    tool_registry.register_tool(chain_session, key="t.c", name="C", description="c")
    version = tool_registry.publish_tool_version(
        chain_session,
        key="t.c",
        input_schema={},
        output_schema={},
        required_scopes=["z:write", "a:read"],
    )
    assert version.required_scopes_json == '["a:read","z:write"]'


def test_a_duplicate_key_is_refused(registered: Session) -> None:
    """A key is what a grant authorizes, so two tools cannot share one."""
    with pytest.raises(DuplicateDefinitionError):
        tool_registry.register_tool(
            registered, key=TOOL_KEY, name="Impostor", description="also reads"
        )


def test_publishing_against_an_unknown_key_is_refused(registered: Session) -> None:
    with pytest.raises(DefinitionNotFoundError):
        tool_registry.publish_tool_version(
            registered, key="nobody", input_schema={}, output_schema={}
        )


# --- Immutability -----------------------------------------------------------


def test_raising_a_limit_is_a_new_version_not_an_edit(registered: Session) -> None:
    """An execution has to be able to say what the limit was when it ran."""
    second = tool_registry.publish_tool_version(
        registered,
        key=TOOL_KEY,
        input_schema=INPUT_SCHEMA,
        output_schema=OUTPUT_SCHEMA,
        timeout_seconds=60,
    )
    assert second.version_no == 2
    first = tool_registry.resolve_tool_version(registered, key=TOOL_KEY, version_no=1)
    assert first.timeout_seconds == 15


def test_a_descriptor_cannot_be_edited(registered: Session) -> None:
    version = tool_registry.resolve_tool_version(registered, key=TOOL_KEY)
    with pytest.raises(DBAPIError, match="immutable"):
        registered.execute(
            text("UPDATE tool_definition_version SET timeout_seconds = 3600 WHERE id = :i"),
            {"i": version.id},
        )
    registered.rollback()


def test_a_descriptor_cannot_be_deleted(registered: Session) -> None:
    version = tool_registry.resolve_tool_version(registered, key=TOOL_KEY)
    with pytest.raises(DBAPIError, match="immutable"):
        registered.execute(
            text("DELETE FROM tool_definition_version WHERE id = :i"), {"i": version.id}
        )
    registered.rollback()


def test_the_immutability_trigger_is_unconditional(
    owner_engine: Engine, migrated_schema: None
) -> None:
    """The same guarantee every other version table carries: no WHEN clause may
    exempt a column."""
    with Session(owner_engine) as session:
        row = session.execute(
            text(
                "SELECT tgtype, tgqual IS NULL AS unconditional FROM pg_trigger "
                "WHERE tgrelid = cast('tool_definition_version' AS regclass) "
                "AND NOT tgisinternal"
            )
        ).one()
    tgtype = int(row.tgtype)
    assert tgtype & 0b00000010, "must fire BEFORE the write"
    assert tgtype & 0b00000001, "must fire FOR EACH ROW"
    assert tgtype & 0b00010000, "must cover UPDATE"
    assert tgtype & 0b00001000, "must cover DELETE"
    assert row.unconditional


# --- Privilege: platform-curated (D5/D30) -----------------------------------


@pytest.mark.parametrize("table", ["tool_definition", "tool_definition_version"])
def test_the_runtime_role_may_read_but_not_write_the_registry(
    app_engine: Engine, migrated_schema: None, table: str
) -> None:
    """A tenant runtime cannot register a tool, revise one, or widen its limits."""
    with Session(app_engine) as session:
        granted = session.execute(
            text(
                "SELECT has_table_privilege('adw_app', :t, 'SELECT'), "
                "has_table_privilege('adw_app', :t, 'INSERT'), "
                "has_table_privilege('adw_app', :t, 'UPDATE'), "
                "has_table_privilege('adw_app', :t, 'DELETE')"
            ),
            {"t": table},
        ).one()
    assert granted == (True, False, False, False)


def test_the_runtime_role_cannot_publish_a_descriptor(
    app_engine: Engine, migrated_schema: None
) -> None:
    """Attempted for real, not only asserted as a privilege — this is the write
    that would let an agent grant itself a longer timeout."""
    with Session(app_engine) as session:
        with pytest.raises(ProgrammingError, match="permission denied"):
            session.execute(
                text(
                    "INSERT INTO tool_definition_version (id, tool_definition_id, version_no, "
                    "input_schema_json, output_schema_json, timeout_seconds, max_output_bytes) "
                    "VALUES (:i, :d, 1, '{}', '{}', 86400, 999999999)"
                ),
                {"i": uuid4(), "d": uuid4()},
            )
        session.rollback()


def test_the_registry_is_outside_tenant_scope_and_holds_no_tenant_column(
    owner_engine: Engine, migrated_schema: None
) -> None:
    """I13/D30: platform-curated content, shared by every tenant. A tenant_id here
    would be a claim this table does not make."""
    from sqlalchemy import inspect

    for table in ("tool_definition", "tool_definition_version"):
        columns = {column["name"] for column in inspect(owner_engine).get_columns(table)}
        assert "tenant_id" not in columns


def test_no_descriptor_column_could_hold_a_secret(
    owner_engine: Engine, migrated_schema: None
) -> None:
    """The registry is readable by every tenant, so a credential in this table
    would be a credential shared with all of them. Descriptors name secret
    *references*; the gateway resolves them."""
    from sqlalchemy import inspect

    columns = {
        column["name"] for column in inspect(owner_engine).get_columns("tool_definition_version")
    }
    assert not columns & {"secret", "api_key", "token", "password", "credential"}


# --- Resolution and deprecation ---------------------------------------------


def test_resolution_returns_the_highest_version(registered: Session) -> None:
    tool_registry.publish_tool_version(
        registered, key=TOOL_KEY, input_schema=INPUT_SCHEMA, output_schema=OUTPUT_SCHEMA
    )
    assert tool_registry.resolve_tool_version(registered, key=TOOL_KEY).version_no == 2


def test_a_deprecated_descriptor_is_not_selected_for_a_new_task(registered: Session) -> None:
    second = tool_registry.publish_tool_version(
        registered, key=TOOL_KEY, input_schema=INPUT_SCHEMA, output_schema=OUTPUT_SCHEMA
    )
    definition_service.deprecate(
        registered,
        kind=DefinitionKind.TOOL,
        version_id=second.id,
        deprecated_by_identity=CURATOR,
        reason="output limit too permissive",
    )
    assert tool_registry.resolve_tool_version(registered, key=TOOL_KEY).version_no == 1


def test_a_pinned_deprecated_descriptor_still_resolves_exactly(registered: Session) -> None:
    """An execution that pinned it must keep reading the limits that applied."""
    version = tool_registry.resolve_tool_version(registered, key=TOOL_KEY)
    definition_service.deprecate(
        registered,
        kind=DefinitionKind.TOOL,
        version_id=version.id,
        deprecated_by_identity=CURATOR,
        reason="superseded",
    )
    exact = tool_registry.resolve_tool_version(registered, key=TOOL_KEY, version_no=1)
    assert exact.id == version.id
    assert exact.timeout_seconds == 15


def test_deprecation_uses_the_same_append_only_record_as_every_other_kind(
    registered: Session,
) -> None:
    """One mechanism, not a second one bolted on for tools."""
    version = tool_registry.resolve_tool_version(registered, key=TOOL_KEY)
    record = definition_service.deprecate(
        registered,
        kind=DefinitionKind.TOOL,
        version_id=version.id,
        deprecated_by_identity=CURATOR,
        reason="superseded",
    )
    assert record.kind is DefinitionKind.TOOL
    assert record.subject_id == version.id
    assert record.reason == "superseded"

    registered.flush()
    with pytest.raises(DBAPIError, match="append-only"):
        registered.execute(
            text("DELETE FROM definition_deprecation WHERE id = :i"), {"i": record.id}
        )
    registered.rollback()


def test_deprecating_every_version_reports_no_publishable_version(
    registered: Session,
) -> None:
    only = tool_registry.resolve_tool_version(registered, key=TOOL_KEY)
    definition_service.deprecate(
        registered,
        kind=DefinitionKind.TOOL,
        version_id=only.id,
        deprecated_by_identity=CURATOR,
        reason="withdrawn",
    )
    with pytest.raises(NoPublishableVersionError):
        tool_registry.resolve_tool_version(registered, key=TOOL_KEY)


def test_an_unknown_tool_is_not_found(chain_session: Session) -> None:
    with pytest.raises(DefinitionNotFoundError):
        tool_registry.resolve_tool_version(chain_session, key="nobody")


def test_an_unknown_version_number_is_not_found(registered: Session) -> None:
    with pytest.raises(DefinitionNotFoundError):
        tool_registry.resolve_tool_version(registered, key=TOOL_KEY, version_no=99)


def test_a_deprecated_descriptor_cannot_be_deleted(registered: Session) -> None:
    """RESTRICT: a retired descriptor must outlive its retirement, because an
    execution that pinned it still refers to it."""
    version = tool_registry.resolve_tool_version(registered, key=TOOL_KEY)
    definition_service.deprecate(
        registered,
        kind=DefinitionKind.TOOL,
        version_id=version.id,
        deprecated_by_identity=CURATOR,
        reason="superseded",
    )
    registered.flush()
    with pytest.raises(DBAPIError):
        registered.execute(
            text("DELETE FROM tool_definition_version WHERE id = :i"), {"i": version.id}
        )
    registered.rollback()


def test_the_exclusivity_constraint_covers_the_new_kind(registered: Session) -> None:
    """A deprecation naming a tool version and an agent version at once is
    refused — the constraint was widened, not loosened."""
    from adw.models.definition import DefinitionDeprecation

    version = tool_registry.resolve_tool_version(registered, key=TOOL_KEY)
    agent_id = uuid4()
    registered.execute(
        text("INSERT INTO agent_definition (id, key, name) VALUES (:i, 'a', 'A')"),
        {"i": agent_id},
    )
    agent_version_id = uuid4()
    registered.execute(
        text(
            "INSERT INTO agent_definition_version "
            "(id, agent_definition_id, version_no, instructions) VALUES (:i, :d, 1, 'x')"
        ),
        {"i": agent_version_id, "d": agent_id},
    )
    registered.add(
        DefinitionDeprecation(
            tool_definition_version_id=version.id,
            agent_definition_version_id=agent_version_id,
            deprecated_by_identity=CURATOR,
            reason="two at once",
        )
    )
    with pytest.raises(DBAPIError):
        registered.flush()
    registered.rollback()


def test_a_tool_version_is_readable_by_the_runtime_role(registered: Session) -> None:
    """Resolution runs on the runtime connection at task creation."""
    stored = registered.execute(
        select(ToolDefinitionVersion).where(ToolDefinitionVersion.version_no == 1)
    ).scalar_one()
    assert stored.timeout_seconds == 15
