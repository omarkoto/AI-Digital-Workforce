"""The only writer of evidence — D12, D25, D29, I3.

Order of operations, which is not interchangeable and is the whole point of
routing every write through here:

1. **Redact** (D12). Before anything else, and before anything is persisted.
2. Canonicalize (D23).
3. **Encrypt** under the tenant key (D1).
4. Digest the **ciphertext**, over raw bytes (D29).
5. Store inline or as a blob, depending on size.
6. Persist the metadata row.

A payload that reaches step 3 has already been through step 1. There is no path
that persists first and hides later, because the store is append-only and hiding
later leaves the secret in it forever.
"""

from __future__ import annotations

from datetime import datetime
from typing import Final
from uuid import UUID

from sqlalchemy.orm import Session

from adw.domain.canonical import canonicalize
from adw.domain.hashing import digest_content
from adw.models.action import Action, Evidence
from adw.ports.blobstore import BlobStore
from adw.ports.keystore import KeyStore
from adw.services.redaction import redact

INLINE_THRESHOLD_BYTES: Final = 64 * 1024
"""Open decision I, proposed default. Below this, evidence lives in the row;
above it, in the blob store. Tuning it changes nothing about correctness."""


def record_for_action(
    session: Session,
    *,
    action: Action,
    kind: str,
    payload: object,
    keystore: KeyStore,
    blobstore: BlobStore,
    recorded_at: datetime | None = None,
) -> Evidence:
    """Redact, encrypt, store, and persist one piece of evidence for an action.

    Must be called inside a transaction already scoped to the action's tenant.
    """
    tenant_id = action.tenant_id

    # 1. Redaction, first and unconditionally.
    cleaned = redact(payload)

    # 2-4. Canonicalize, encrypt, digest the ciphertext.
    encrypted = keystore.encrypt(tenant_id, canonicalize(cleaned.value))
    digest = digest_content(encrypted.ciphertext)
    size = len(encrypted.ciphertext)

    # 5. Inline or blob.
    inline: bytes | None = None
    blob_key: str | None = None
    if size <= INLINE_THRESHOLD_BYTES:
        inline = encrypted.ciphertext
    else:
        blob_key = blobstore.put(tenant_id, digest, encrypted.ciphertext)

    # 6. Metadata.
    evidence = Evidence(
        tenant_id=tenant_id,
        action_id=action.id,
        kind=kind,
        inline_ciphertext=inline,
        blob_key=blob_key,
        key_id=encrypted.key_id,
        content_digest=digest,
        size_bytes=size,
        redaction_count=cleaned.count,
        recorded_at=recorded_at,
    )
    session.add(evidence)
    session.flush()
    return evidence


def read_payload(
    evidence: Evidence,
    *,
    tenant_id: UUID,
    keystore: KeyStore,
    blobstore: BlobStore,
) -> bytes:
    """Return the decrypted, canonical bytes of ``evidence``.

    Raises:
        KeyUnavailableError: after the tenant key is destroyed. That is erasure
            working, not a fault — the metadata row and its digest remain, so the
            record still shows the evidence existed.
    """
    from adw.ports.keystore import EncryptedPayload

    ciphertext = (
        evidence.inline_ciphertext
        if evidence.inline_ciphertext is not None
        else blobstore.get(tenant_id, str(evidence.blob_key))
    )
    return keystore.decrypt(
        tenant_id, EncryptedPayload(ciphertext=ciphertext, key_id=evidence.key_id)
    )
