"""The only writer of artifacts — CLAUDE.md §3, D9, D12, D29, I6.

There is no update path, only :func:`append_version`. That is not a convenience
of the API: `CLAUDE.md` §3 requires artifact updates to be append-only new
versions, and the database enforces it, so an update path could not exist even
if someone wrote one.

Each version writes its audit chain record in the same transaction (G2), so an
artifact cannot exist without the record of its creation.

**On redaction of artifact content.** D12 covers artifacts as well as evidence,
but an artifact is deliberate business output rather than a captured payload, and
most artifact types are binary — XLSX, PDF, PNG have no text to scan. Content
that decodes as UTF-8 is redacted; content that does not is stored unchanged and
recorded with a redaction count of zero. That limitation is real and stated
rather than hidden: for binary artifacts the backstop is encryption at rest plus
key destruction (D1), exactly as it is for a redaction miss.
"""

from __future__ import annotations

from typing import Final
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from adw.domain.hashing import digest_content
from adw.models.artifact import Artifact, ArtifactDefinitionVersion, ArtifactVersion
from adw.models.task import Task
from adw.ports.blobstore import BlobStore
from adw.ports.keystore import EncryptedPayload, KeyStore
from adw.services import audit_writer
from adw.services.redaction import redact

EVENT_ARTIFACT_VERSION_CREATED: Final = "artifact.version_created"
FIRST_VERSION: Final = 1


def create_artifact(
    session: Session,
    *,
    tenant_id: UUID,
    execution_id: UUID,
    artifact_definition_id: UUID,
    name: str,
) -> Artifact:
    """Register a deliverable. Versions are appended separately."""
    artifact = Artifact(
        tenant_id=tenant_id,
        execution_id=execution_id,
        artifact_definition_id=artifact_definition_id,
        name=name,
    )
    session.add(artifact)
    session.flush()
    return artifact


def _redact_content(content: bytes) -> tuple[bytes, int]:
    """Redact text content; pass binary through. See the module docstring."""
    try:
        text = content.decode("utf-8")
    except UnicodeDecodeError:
        return content, 0
    result = redact(text)
    return str(result.value).encode("utf-8"), result.count


def next_version_no(session: Session, artifact: Artifact) -> int:
    highest = session.execute(
        select(func.max(ArtifactVersion.version_no)).where(
            ArtifactVersion.artifact_id == artifact.id
        )
    ).scalar_one_or_none()
    return FIRST_VERSION if highest is None else int(highest) + 1


def current_version(session: Session, artifact: Artifact) -> ArtifactVersion | None:
    """Return the highest-numbered version, or ``None``.

    Derived rather than flagged: marking a version current would mean unmarking
    the previous one, and prior versions are immutable.
    """
    return session.scalar(
        select(ArtifactVersion)
        .where(ArtifactVersion.artifact_id == artifact.id)
        .order_by(ArtifactVersion.version_no.desc())
        .limit(1)
    )


def append_version(
    session: Session,
    *,
    artifact: Artifact,
    content: bytes,
    content_type: str,
    producing_task: Task,
    producing_agent_identity: str,
    definition_version: ArtifactDefinitionVersion,
    keystore: KeyStore,
    blobstore: BlobStore,
    actor_id: str,
) -> ArtifactVersion:
    """Append an immutable version and record it in the audit chain.

    Must be called inside a transaction already scoped to the artifact's tenant.
    """
    tenant_id = artifact.tenant_id

    cleaned, redaction_count = _redact_content(content)
    encrypted = keystore.encrypt(tenant_id, cleaned)
    digest = digest_content(encrypted.ciphertext)
    blob_key = blobstore.put(tenant_id, digest, encrypted.ciphertext)

    version = ArtifactVersion(
        tenant_id=tenant_id,
        artifact_id=artifact.id,
        version_no=next_version_no(session, artifact),
        producing_task_id=producing_task.id,
        producing_agent_identity=producing_agent_identity,
        artifact_definition_version_id=definition_version.id,
        blob_key=blob_key,
        key_id=encrypted.key_id,
        content_digest=digest,
        size_bytes=len(encrypted.ciphertext),
        content_type=content_type,
        redaction_count=redaction_count,
    )
    session.add(version)
    session.flush()

    audit_writer.append(
        session,
        tenant_id=tenant_id,
        event_type=EVENT_ARTIFACT_VERSION_CREATED,
        actor_id=actor_id,
        payload={
            "artifact_id": str(artifact.id),
            "artifact_name": artifact.name,
            "version_no": version.version_no,
            "producing_task_id": str(producing_task.id),
            "producing_agent_identity": producing_agent_identity,
            "artifact_definition_version_id": str(definition_version.id),
            "content_digest": digest,
            "size_bytes": version.size_bytes,
        },
        keystore=keystore,
    )
    return version


def read_content(
    version: ArtifactVersion,
    *,
    keystore: KeyStore,
    blobstore: BlobStore,
) -> bytes:
    """Return the decrypted bytes of ``version``.

    Raises:
        KeyUnavailableError: after the tenant key is destroyed. The version row
            and its digest remain, so the record still shows what existed.
    """
    ciphertext = blobstore.get(version.tenant_id, version.blob_key)
    return keystore.decrypt(
        version.tenant_id, EncryptedPayload(ciphertext=ciphertext, key_id=version.key_id)
    )
