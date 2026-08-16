"""Filesystem blob store — **development only**.

A real deployment uses object storage behind the same port. That choice waits on
the cloud provider, which `PRODUCT.md` §26 leaves open.

Refuses to start outside ``dev``, for the same reason the local key store does:
a development adapter surviving into a deployed environment would be severe, so
the refusal is enforced in code and asserted in tests.
"""

from __future__ import annotations

import shutil
from pathlib import Path
from uuid import UUID

from adw.config import AppEnv, get_settings
from adw.ports.blobstore import BlobNotFoundError


class LocalBlobStore:
    """Content-addressed blobs under a local directory, one subtree per tenant."""

    def __init__(self, root: Path) -> None:
        settings = get_settings()
        if settings.app_env is not AppEnv.DEV:
            msg = (
                f"LocalBlobStore is development-only and refuses to start in "
                f"{settings.app_env.value!r}; configure object storage instead"
            )
            raise RuntimeError(msg)
        self._root = root
        self._root.mkdir(parents=True, exist_ok=True)

    def _tenant_root(self, tenant_id: UUID) -> Path:
        return self._root / str(tenant_id)

    def _path_for(self, tenant_id: UUID, digest: str) -> Path:
        # Two-level fan-out, as object stores and content-addressed caches do,
        # so a tenant with many blobs does not produce one enormous directory.
        return self._tenant_root(tenant_id) / digest[:2] / digest[2:4] / digest

    def put(self, tenant_id: UUID, digest: str, ciphertext: bytes) -> str:
        path = self._path_for(tenant_id, digest)
        path.parent.mkdir(parents=True, exist_ok=True)
        # Content-addressed: identical bytes produce an identical path, so a
        # rewrite is a no-op rather than a conflict.
        path.write_bytes(ciphertext)
        return f"{tenant_id}/{digest}"

    def get(self, tenant_id: UUID, key: str) -> bytes:
        digest = key.rsplit("/", 1)[-1]
        path = self._path_for(tenant_id, digest)
        if not path.is_file():
            msg = f"no blob stored at {key!r}"
            raise BlobNotFoundError(msg)
        return path.read_bytes()

    def destroy_tenant(self, tenant_id: UUID) -> int:
        root = self._tenant_root(tenant_id)
        if not root.is_dir():
            return 0
        count = sum(1 for path in root.rglob("*") if path.is_file())
        shutil.rmtree(root)
        return count
