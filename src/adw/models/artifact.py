"""Artifact and Artifact Definition — CLAUDE.md §3, D9, D29, D30, I6.

An **Artifact** is a business work product: the deliverable. It has durable
identity and an ordered list of **immutable versions**. There is no update path —
"updating" an artifact always means appending a new version, and every prior
version stays retrievable forever.

An **Artifact Definition** is the versioned contract a version was validated
against. Platform-curated and outside tenant scope (D30), following the same
identity-plus-versions shape as agent definitions and skills.

Two things are deliberately *not* stored:

* **Content.** It lives in the blob store, encrypted, addressed by the digest of
  its bytes. The relational row holds metadata only.
* **A "current" flag.** Whether a version is current is derived from the highest
  version number, because storing it would require mutating an earlier row —
  which the immutability trigger forbids, and rightly.
"""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import CheckConstraint, ForeignKey, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from adw.domain.ids import new_id
from adw.models.base import Base, CreatedAtMixin, TenantScopedMixin


class ArtifactDefinition(Base, CreatedAtMixin):
    """The durable identity of an artifact type. Platform-curated (D30)."""

    __tablename__ = "artifact_definition"

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True, default=new_id)
    key: Mapped[str] = mapped_column(unique=True, nullable=False)
    name: Mapped[str] = mapped_column(nullable=False)

    versions: Mapped[list[ArtifactDefinitionVersion]] = relationship(
        back_populates="definition",
        order_by="ArtifactDefinitionVersion.version_no",
    )


class ArtifactDefinitionVersion(Base, CreatedAtMixin):
    """One immutable revision of an artifact's contract.

    A gate needs something to check against: an artifact type with no definition
    cannot be validated, and therefore cannot pass a gate. The validation rules
    themselves are declared here and executed by the Gate Engine in Task 9 —
    this declares, it does not run.
    """

    __tablename__ = "artifact_definition_version"
    __table_args__ = (UniqueConstraint("artifact_definition_id", "version_no"),)

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True, default=new_id)
    artifact_definition_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("artifact_definition.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    version_no: Mapped[int] = mapped_column(nullable=False)
    content_type: Mapped[str] = mapped_column(nullable=False)
    """The media type a version of this artifact is expected to carry."""

    schema_json: Mapped[str] = mapped_column(nullable=False)
    """The contract, as canonical JSON. Declarative: the Gate Engine reads it."""

    definition: Mapped[ArtifactDefinition] = relationship(back_populates="versions")


class Artifact(Base, TenantScopedMixin, CreatedAtMixin):
    """A deliverable, with durable identity across its versions."""

    __tablename__ = "artifact"
    __table_args__ = (UniqueConstraint("execution_id", "name"),)

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True, default=new_id)
    execution_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("execution.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    artifact_definition_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("artifact_definition.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    name: Mapped[str] = mapped_column(nullable=False)

    versions: Mapped[list[ArtifactVersion]] = relationship(
        back_populates="artifact",
        order_by="ArtifactVersion.version_no",
    )


class ArtifactVersion(Base, TenantScopedMixin, CreatedAtMixin):
    """One immutable version of an artifact.

    Immutability is enforced in the database, by revoked grants and a trigger,
    not by convention (I6). A version that a Control Gate approved must be the
    same bytes anyone retrieves afterwards, or the approval means nothing.
    """

    __tablename__ = "artifact_version"
    __table_args__ = (
        UniqueConstraint("artifact_id", "version_no"),
        CheckConstraint("version_no >= 1", name="version_no_positive"),
        CheckConstraint("size_bytes >= 0", name="size_not_negative"),
        CheckConstraint("redaction_count >= 0", name="redaction_count_not_negative"),
    )

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True, default=new_id)
    artifact_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("artifact.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    version_no: Mapped[int] = mapped_column(nullable=False)

    producing_task_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("task.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    producing_agent_identity: Mapped[str] = mapped_column(nullable=False)
    """Who produced this. Recorded on the version rather than derived, because
    D4 forbids the producer from approving the gate covering it — and that check
    needs an identity that cannot drift after the fact."""

    artifact_definition_version_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("artifact_definition_version.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    """Pinned (D9/I4): the contract this version was validated against, not
    whichever contract is current when someone later asks."""

    blob_key: Mapped[str] = mapped_column(nullable=False)
    key_id: Mapped[str] = mapped_column(nullable=False)
    content_digest: Mapped[str] = mapped_column(nullable=False)
    """Raw-byte digest of the ciphertext (D29). Canonicalizing first would let
    two byte-different files share a digest, which would allow serving a file
    that is not the one a gate approved."""

    size_bytes: Mapped[int] = mapped_column(nullable=False)
    content_type: Mapped[str] = mapped_column(nullable=False)
    redaction_count: Mapped[int] = mapped_column(nullable=False, default=0)

    artifact: Mapped[Artifact] = relationship(back_populates="versions")
