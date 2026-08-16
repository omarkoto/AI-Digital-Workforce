"""Blob store port.

Evidence payloads and artifact content are large, immutable, and addressed by
the digest of their bytes. That is a poor fit for the relational store, so they
live here instead — but the *metadata* stays in the database, so the record
still knows what exists even when a blob has been shredded.

Content arriving here is already redacted (D12) and already encrypted (D1). The
store sees ciphertext and never decides anything about it.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable
from uuid import UUID


class BlobNotFoundError(Exception):
    """No blob exists at the given key.

    Expected after retention expiry or key destruction, not necessarily a fault.
    """


@runtime_checkable
class BlobStore(Protocol):
    """Content-addressed storage for encrypted payloads."""

    def put(self, tenant_id: UUID, digest: str, ciphertext: bytes) -> str:
        """Store ``ciphertext`` and return its key.

        Keys are tenant-prefixed so that a tenant's blobs can be located and
        destroyed as a unit.
        """
        ...

    def get(self, tenant_id: UUID, key: str) -> bytes:
        """Return the ciphertext at ``key``.

        Raises:
            BlobNotFoundError: if nothing is stored there.
        """
        ...

    def destroy_tenant(self, tenant_id: UUID) -> int:
        """Remove every blob belonging to ``tenant_id`` and return the count."""
        ...
