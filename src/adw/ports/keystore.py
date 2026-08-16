"""Key store port — D1, D25.

Erasure works by destroying a tenant's key, not by deleting rows: the record of
*what happened* survives, the *content* does not. That only holds if every
ciphertext records which key produced it, so :class:`EncryptedPayload` carries a
``key_id`` and the chain persists it.

The port deliberately exposes no way to enumerate or export key material. A
caller can encrypt, decrypt, and destroy — nothing else.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, runtime_checkable
from uuid import UUID


@dataclass(frozen=True, slots=True)
class EncryptedPayload:
    """Ciphertext together with the identifier of the key that produced it."""

    ciphertext: bytes
    key_id: str


@runtime_checkable
class KeyStore(Protocol):
    """Per-tenant encryption, with destruction as the erasure mechanism."""

    def encrypt(self, tenant_id: UUID, plaintext: bytes) -> EncryptedPayload:
        """Encrypt ``plaintext`` under ``tenant_id``'s current key."""
        ...

    def decrypt(self, tenant_id: UUID, payload: EncryptedPayload) -> bytes:
        """Decrypt ``payload``.

        Raises:
            KeyUnavailableError: if the key has been destroyed. This is the
                expected outcome after erasure, not a fault.
        """
        ...

    def destroy(self, tenant_id: UUID) -> None:
        """Destroy a tenant's key material, rendering its ciphertext unreadable.

        The chain remains verifiable afterwards, because record hashes cover the
        ciphertext digest rather than the plaintext (I12).
        """
        ...


class KeyUnavailableError(Exception):
    """The key needed to decrypt a payload does not exist or was destroyed."""
