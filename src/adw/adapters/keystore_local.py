"""File-backed key store — **development only**.

A real deployment resolves keys from a managed KMS. That choice waits on the
cloud provider, which `PRODUCT.md` §26 leaves open, so this adapter exists to let
the audit chain store real ciphertext now rather than plaintext it could never
take back — the store is append-only, so anything written unencrypted stays
unencrypted permanently.

It refuses to start outside ``dev``. A development key store surviving into a
deployed environment would be a severe vulnerability, so the refusal is enforced
in code and asserted in tests rather than left to deployment discipline.
"""

from __future__ import annotations

import json
from pathlib import Path
from uuid import UUID

from cryptography.fernet import Fernet, InvalidToken

from adw.config import AppEnv, get_settings
from adw.ports.keystore import EncryptedPayload, KeyUnavailableError

KEY_GENERATION = 1
"""Rotation generation. The key id records it, so a rotated key is
distinguishable from the one it replaced (D25)."""


class LocalKeyStore:
    """Per-tenant Fernet keys held in a local JSON file.

    Destroying a key removes it from the file. Ciphertext encrypted under it
    becomes permanently unreadable, which is the intended shape of erasure.
    """

    def __init__(self, path: Path) -> None:
        settings = get_settings()
        if settings.app_env is not AppEnv.DEV:
            msg = (
                f"LocalKeyStore is development-only and refuses to start in "
                f"{settings.app_env.value!r}; configure a managed key store instead"
            )
            raise RuntimeError(msg)
        self._path = path
        self._path.parent.mkdir(parents=True, exist_ok=True)

    def _load(self) -> dict[str, str]:
        if not self._path.is_file():
            return {}
        loaded: dict[str, str] = json.loads(self._path.read_text(encoding="utf-8"))
        return loaded

    def _save(self, keys: dict[str, str]) -> None:
        self._path.write_text(json.dumps(keys, indent=2), encoding="utf-8")

    @staticmethod
    def key_id_for(tenant_id: UUID) -> str:
        return f"local:{tenant_id}:g{KEY_GENERATION}"

    def encrypt(self, tenant_id: UUID, plaintext: bytes) -> EncryptedPayload:
        keys = self._load()
        key_id = self.key_id_for(tenant_id)
        material = keys.get(key_id)
        if material is None:
            material = Fernet.generate_key().decode("ascii")
            keys[key_id] = material
            self._save(keys)
        ciphertext = Fernet(material.encode("ascii")).encrypt(plaintext)
        return EncryptedPayload(ciphertext=ciphertext, key_id=key_id)

    def decrypt(self, tenant_id: UUID, payload: EncryptedPayload) -> bytes:
        material = self._load().get(payload.key_id)
        if material is None:
            msg = f"key {payload.key_id!r} is unavailable; it was destroyed or never existed"
            raise KeyUnavailableError(msg)
        try:
            return Fernet(material.encode("ascii")).decrypt(payload.ciphertext)
        except InvalidToken as exc:
            msg = f"ciphertext does not authenticate under key {payload.key_id!r}"
            raise KeyUnavailableError(msg) from exc

    def destroy(self, tenant_id: UUID) -> None:
        keys = self._load()
        removed = [k for k in keys if k.startswith(f"local:{tenant_id}:")]
        for key_id in removed:
            del keys[key_id]
        self._save(keys)
