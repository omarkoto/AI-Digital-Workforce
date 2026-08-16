"""Artifacts and their immutability — CLAUDE.md §3, D9, D29, D30, I6.

The deliverable is the point of the platform. A version a Control Gate approved
must be the same bytes anyone retrieves afterwards, or the approval means
nothing — so immutability is enforced in the database and proved here against
the runtime role *and* the owner.
"""

from __future__ import annotations

from uuid import uuid4

import pytest
from sqlalchemy import Engine, text
from sqlalchemy.exc import DBAPIError, IntegrityError, ProgrammingError
from sqlalchemy.orm import Session

from adw.adapters.blobstore_local import LocalBlobStore
from adw.adapters.keystore_local import LocalKeyStore
from adw.domain.hashing import digest_content
from adw.domain.states import TaskState
from adw.models.artifact import Artifact, ArtifactDefinitionVersion, ArtifactVersion
from adw.models.task import Task
from adw.ports.keystore import KeyUnavailableError
from adw.services import artifact_service
from tests.security.conftest import TENANT_A

pytestmark = pytest.mark.security

ACTOR = "agent:report-assembly"
AGENT = "agent:data-preparation"


@pytest.fixture
def scaffolding(chain_session: Session) -> dict[str, object]:
    """An execution, a task, and an artifact definition with two versions."""
    agent_id, agent_version_id, execution_id = uuid4(), uuid4(), uuid4()
    chain_session.execute(
        text("INSERT INTO agent_definition (id, key, name) VALUES (:i, 'prep', 'Prep')"),
        {"i": agent_id},
    )
    chain_session.execute(
        text(
            "INSERT INTO agent_definition_version "
            "(id, agent_definition_id, version_no, instructions) VALUES (:i, :d, 1, 'go')"
        ),
        {"i": agent_version_id, "d": agent_id},
    )
    chain_session.execute(
        text(
            "INSERT INTO execution (id, tenant_id, requester_identity, state) "
            "VALUES (:i, :t, 'amira@northwind', 'running')"
        ),
        {"i": execution_id, "t": TENANT_A},
    )
    task = Task(
        tenant_id=TENANT_A,
        execution_id=execution_id,
        sequence=1,
        agent_definition_version_id=agent_version_id,
        state=TaskState.PRODUCING,
        attempt_no=1,
    )
    chain_session.add(task)

    definition_id = uuid4()
    chain_session.execute(
        text(
            "INSERT INTO artifact_definition (id, key, name) "
            "VALUES (:i, 'variance.commentary', 'Variance commentary')"
        ),
        {"i": definition_id},
    )
    version_ids = [uuid4(), uuid4()]
    for index, version_id in enumerate(version_ids, start=1):
        chain_session.execute(
            text(
                "INSERT INTO artifact_definition_version "
                "(id, artifact_definition_id, version_no, content_type, schema_json) "
                "VALUES (:i, :d, :v, 'text/markdown', :s)"
            ),
            {"i": version_id, "d": definition_id, "v": index, "s": f'{{"revision":{index}}}'},
        )
    chain_session.flush()

    return {
        "execution_id": execution_id,
        "task": task,
        "definition_id": definition_id,
        "definition_v1": chain_session.get(ArtifactDefinitionVersion, version_ids[0]),
        "definition_v2": chain_session.get(ArtifactDefinitionVersion, version_ids[1]),
    }


@pytest.fixture
def artifact(chain_session: Session, scaffolding: dict[str, object]) -> Artifact:
    return artifact_service.create_artifact(
        chain_session,
        tenant_id=TENANT_A,
        execution_id=scaffolding["execution_id"],  # type: ignore[arg-type]
        artifact_definition_id=scaffolding["definition_id"],  # type: ignore[arg-type]
        name="variance-commentary",
    )


def append(
    session: Session,
    artifact: Artifact,
    scaffolding: dict[str, object],
    keystore: LocalKeyStore,
    blobstore: LocalBlobStore,
    content: bytes = b"Marketing overspend of 1,243,880 against budget.",
    definition_key: str = "definition_v1",
) -> ArtifactVersion:
    return artifact_service.append_version(
        session,
        artifact=artifact,
        content=content,
        content_type="text/markdown",
        producing_task=scaffolding["task"],  # type: ignore[arg-type]
        producing_agent_identity=AGENT,
        definition_version=scaffolding[definition_key],  # type: ignore[arg-type]
        keystore=keystore,
        blobstore=blobstore,
        actor_id=ACTOR,
    )


# --------------------------------------------------------------------------
# Append-only versioning
# --------------------------------------------------------------------------


def test_first_version_is_number_one(
    chain_session: Session,
    artifact: Artifact,
    scaffolding: dict[str, object],
    dev_keystore: LocalKeyStore,
    dev_blobstore: LocalBlobStore,
) -> None:
    version = append(chain_session, artifact, scaffolding, dev_keystore, dev_blobstore)
    assert version.version_no == 1


def test_updating_means_appending(
    chain_session: Session,
    artifact: Artifact,
    scaffolding: dict[str, object],
    dev_keystore: LocalKeyStore,
    dev_blobstore: LocalBlobStore,
) -> None:
    """CLAUDE.md §3: artifact updates are append-only new versions."""
    first = append(chain_session, artifact, scaffolding, dev_keystore, dev_blobstore, b"1.2m")
    second = append(chain_session, artifact, scaffolding, dev_keystore, dev_blobstore, b"1,243,880")
    assert (first.version_no, second.version_no) == (1, 2)
    assert first.content_digest != second.content_digest


def test_prior_versions_stay_retrievable(
    chain_session: Session,
    artifact: Artifact,
    scaffolding: dict[str, object],
    dev_keystore: LocalKeyStore,
    dev_blobstore: LocalBlobStore,
) -> None:
    """The G4 correction in the worked example depends on this."""
    first = append(chain_session, artifact, scaffolding, dev_keystore, dev_blobstore, b"1.2m")
    append(chain_session, artifact, scaffolding, dev_keystore, dev_blobstore, b"1,243,880")

    assert (
        artifact_service.read_content(first, keystore=dev_keystore, blobstore=dev_blobstore)
        == b"1.2m"
    )


def test_current_version_is_derived_not_flagged(
    chain_session: Session,
    artifact: Artifact,
    scaffolding: dict[str, object],
    dev_keystore: LocalKeyStore,
    dev_blobstore: LocalBlobStore,
) -> None:
    """Storing a current flag would mean mutating the previous version."""
    append(chain_session, artifact, scaffolding, dev_keystore, dev_blobstore)
    second = append(chain_session, artifact, scaffolding, dev_keystore, dev_blobstore, b"newer")
    assert artifact_service.current_version(chain_session, artifact) is second

    columns = (
        chain_session.execute(
            text(
                "SELECT column_name FROM information_schema.columns "
                "WHERE table_name = 'artifact_version'"
            )
        )
        .scalars()
        .all()
    )
    assert not {"is_current", "superseded", "is_latest"} & set(columns)


def test_duplicate_version_numbers_are_refused(
    chain_session: Session,
    artifact: Artifact,
    scaffolding: dict[str, object],
    dev_keystore: LocalKeyStore,
    dev_blobstore: LocalBlobStore,
) -> None:
    version = append(chain_session, artifact, scaffolding, dev_keystore, dev_blobstore)
    with pytest.raises(IntegrityError), chain_session.begin_nested():
        chain_session.add(
            ArtifactVersion(
                tenant_id=TENANT_A,
                artifact_id=artifact.id,
                version_no=version.version_no,
                producing_task_id=version.producing_task_id,
                producing_agent_identity=AGENT,
                artifact_definition_version_id=version.artifact_definition_version_id,
                blob_key="k",
                key_id="key",
                content_digest="d",
                size_bytes=1,
                content_type="text/markdown",
            )
        )
        chain_session.flush()


# --------------------------------------------------------------------------
# Immutability
# --------------------------------------------------------------------------


def test_artifact_versions_cannot_be_updated_or_deleted(
    chain_session: Session,
    artifact: Artifact,
    scaffolding: dict[str, object],
    dev_keystore: LocalKeyStore,
    dev_blobstore: LocalBlobStore,
) -> None:
    """I6, proved against the owner — there is no privileged writer."""
    append(chain_session, artifact, scaffolding, dev_keystore, dev_blobstore)
    chain_session.flush()
    for statement in (
        "UPDATE artifact_version SET content_digest = 'forged'",
        "DELETE FROM artifact_version",
    ):
        with pytest.raises(DBAPIError, match="immutable"), chain_session.begin_nested():
            chain_session.execute(text(statement))


def test_runtime_role_cannot_mutate_artifact_versions(
    app_engine: Engine, migrated_schema: None
) -> None:
    with pytest.raises(ProgrammingError, match="permission denied"), app_engine.begin() as conn:
        conn.execute(text("SELECT set_config('app.tenant_id', :t, true)"), {"t": str(TENANT_A)})
        conn.execute(text("DELETE FROM artifact_version"))


def test_artifact_definition_versions_are_immutable(
    chain_session: Session, scaffolding: dict[str, object]
) -> None:
    """D9: a contract an artifact was validated against cannot change."""
    with pytest.raises(DBAPIError, match="immutable"), chain_session.begin_nested():
        chain_session.execute(text("UPDATE artifact_definition_version SET schema_json = '{}'"))


def test_runtime_role_cannot_write_artifact_definitions(
    app_engine: Engine, migrated_schema: None
) -> None:
    """D30: definitions are platform-curated; the application reads them."""
    with pytest.raises(ProgrammingError, match="permission denied"), app_engine.begin() as conn:
        conn.execute(
            text("INSERT INTO artifact_definition (id, key, name) VALUES (:i, 'x', 'X')"),
            {"i": uuid4()},
        )


# --------------------------------------------------------------------------
# Pinning, content, and audit
# --------------------------------------------------------------------------


def test_the_definition_version_is_pinned(
    chain_session: Session,
    artifact: Artifact,
    scaffolding: dict[str, object],
    dev_keystore: LocalKeyStore,
    dev_blobstore: LocalBlobStore,
) -> None:
    """D9/I4: pinned to what validated it, not to whatever is current later."""
    first = append(chain_session, artifact, scaffolding, dev_keystore, dev_blobstore)
    second = append(
        chain_session,
        artifact,
        scaffolding,
        dev_keystore,
        dev_blobstore,
        b"later",
        definition_key="definition_v2",
    )
    assert first.artifact_definition_version_id != second.artifact_definition_version_id
    pinned = chain_session.get(ArtifactDefinitionVersion, first.artifact_definition_version_id)
    assert pinned is not None
    assert pinned.version_no == 1


def test_producing_identity_is_recorded(
    chain_session: Session,
    artifact: Artifact,
    scaffolding: dict[str, object],
    dev_keystore: LocalKeyStore,
    dev_blobstore: LocalBlobStore,
) -> None:
    """D4 needs an identity that cannot drift: the producer may never approve."""
    version = append(chain_session, artifact, scaffolding, dev_keystore, dev_blobstore)
    task = scaffolding["task"]
    assert isinstance(task, Task)
    assert version.producing_agent_identity == AGENT
    assert version.producing_task_id == task.id


def test_content_is_stored_encrypted_and_digested_raw(
    chain_session: Session,
    artifact: Artifact,
    scaffolding: dict[str, object],
    dev_keystore: LocalKeyStore,
    dev_blobstore: LocalBlobStore,
) -> None:
    version = append(
        chain_session, artifact, scaffolding, dev_keystore, dev_blobstore, b"MARCH-COMMENTARY"
    )
    raw = dev_blobstore.get(TENANT_A, version.blob_key)
    assert b"MARCH-COMMENTARY" not in raw
    assert version.content_digest == digest_content(raw)


def test_secrets_in_text_content_are_redacted(
    chain_session: Session,
    artifact: Artifact,
    scaffolding: dict[str, object],
    dev_keystore: LocalKeyStore,
    dev_blobstore: LocalBlobStore,
) -> None:
    version = append(
        chain_session,
        artifact,
        scaffolding,
        dev_keystore,
        dev_blobstore,
        b"connection used postgresql://svc:hunter2@db:5432/x",
    )
    stored = artifact_service.read_content(version, keystore=dev_keystore, blobstore=dev_blobstore)
    assert b"hunter2" not in stored
    assert version.redaction_count >= 1


def test_binary_content_passes_through_unredacted(
    chain_session: Session,
    artifact: Artifact,
    scaffolding: dict[str, object],
    dev_keystore: LocalKeyStore,
    dev_blobstore: LocalBlobStore,
) -> None:
    """A documented limitation: XLSX and PDF have no text to scan.

    The backstop is encryption plus key destruction, exactly as for a redaction
    miss. Recorded here so the gap is visible rather than assumed away.
    """
    binary = b"\x50\x4b\x03\x04\xff\xfe\x00\x01payload"
    version = append(chain_session, artifact, scaffolding, dev_keystore, dev_blobstore, binary)
    assert version.redaction_count == 0
    assert (
        artifact_service.read_content(version, keystore=dev_keystore, blobstore=dev_blobstore)
        == binary
    )


def test_each_version_writes_one_audit_record(
    chain_session: Session,
    artifact: Artifact,
    scaffolding: dict[str, object],
    dev_keystore: LocalKeyStore,
    dev_blobstore: LocalBlobStore,
) -> None:
    before = chain_session.execute(text("SELECT count(*) FROM chain_record")).scalar_one()
    append(chain_session, artifact, scaffolding, dev_keystore, dev_blobstore)
    append(chain_session, artifact, scaffolding, dev_keystore, dev_blobstore, b"v2")
    after = chain_session.execute(text("SELECT count(*) FROM chain_record")).scalar_one()
    assert after - before == 2


def test_destroying_the_key_leaves_the_version_record(
    chain_session: Session,
    artifact: Artifact,
    scaffolding: dict[str, object],
    dev_keystore: LocalKeyStore,
    dev_blobstore: LocalBlobStore,
) -> None:
    """D1: erasure removes readability, never the record that it existed."""
    version = append(chain_session, artifact, scaffolding, dev_keystore, dev_blobstore)
    digest = version.content_digest
    dev_keystore.destroy(TENANT_A)

    with pytest.raises(KeyUnavailableError):
        artifact_service.read_content(version, keystore=dev_keystore, blobstore=dev_blobstore)
    still_there = chain_session.get(ArtifactVersion, version.id)
    assert still_there is not None
    assert still_there.content_digest == digest


def test_artifacts_are_tenant_isolated(app_engine: Engine, migrated_schema: None) -> None:
    with app_engine.begin() as conn:
        for table in ("artifact", "artifact_version"):
            assert conn.execute(text(f"SELECT count(*) FROM {table}")).scalar_one() == 0
