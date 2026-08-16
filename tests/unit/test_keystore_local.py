"""The development key store — D1, D25.

Exists so the audit chain can store real ciphertext now rather than plaintext it
could never take back. Its refusal to run outside ``dev`` is the security
property worth pinning: a development key store surviving into a deployed
environment would be severe.
"""

from __future__ import annotations

from pathlib import Path
from uuid import uuid4

import pytest

from adw import config
from adw.adapters.keystore_local import LocalKeyStore
from adw.ports.keystore import EncryptedPayload, KeyStore, KeyUnavailableError


@pytest.fixture
def keystore(env_settings: None, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> LocalKeyStore:
    monkeypatch.setenv("ADW_APP_ENV", "dev")
    config.get_settings.cache_clear()
    return LocalKeyStore(tmp_path / "keys.json")


@pytest.mark.unit
def test_refuses_to_start_outside_dev(env_settings: None, tmp_path: Path) -> None:
    """env_settings sets ADW_APP_ENV=test, so construction must fail."""
    with pytest.raises(RuntimeError, match="development-only"):
        LocalKeyStore(tmp_path / "keys.json")


@pytest.mark.unit
def test_satisfies_the_keystore_protocol(keystore: LocalKeyStore) -> None:
    assert isinstance(keystore, KeyStore)


@pytest.mark.unit
def test_round_trip(keystore: LocalKeyStore) -> None:
    tenant = uuid4()
    payload = keystore.encrypt(tenant, b"actuals for March")
    assert keystore.decrypt(tenant, payload) == b"actuals for March"


@pytest.mark.unit
def test_ciphertext_does_not_contain_the_plaintext(keystore: LocalKeyStore) -> None:
    payload = keystore.encrypt(uuid4(), b"marketing overspend")
    assert b"marketing overspend" not in payload.ciphertext


@pytest.mark.unit
def test_key_id_is_recorded_with_every_ciphertext(keystore: LocalKeyStore) -> None:
    """D25: without it, rotation is impossible and erasure becomes guesswork."""
    tenant = uuid4()
    payload = keystore.encrypt(tenant, b"x")
    assert str(tenant) in payload.key_id
    assert payload.key_id.endswith("g1")


@pytest.mark.unit
def test_each_tenant_gets_a_distinct_key(keystore: LocalKeyStore) -> None:
    a, b = uuid4(), uuid4()
    first = keystore.encrypt(a, b"same plaintext")
    second = keystore.encrypt(b, b"same plaintext")
    assert first.key_id != second.key_id
    with pytest.raises(KeyUnavailableError):
        keystore.decrypt(a, EncryptedPayload(ciphertext=second.ciphertext, key_id=first.key_id))


@pytest.mark.unit
def test_destroying_a_key_makes_ciphertext_unreadable(keystore: LocalKeyStore) -> None:
    """Crypto-shredding: the record survives, the content does not."""
    tenant = uuid4()
    payload = keystore.encrypt(tenant, b"confidential")
    keystore.destroy(tenant)
    with pytest.raises(KeyUnavailableError):
        keystore.decrypt(tenant, payload)


@pytest.mark.unit
def test_destroying_one_tenant_does_not_affect_another(keystore: LocalKeyStore) -> None:
    a, b = uuid4(), uuid4()
    kept = keystore.encrypt(b, b"still readable")
    keystore.encrypt(a, b"about to go")
    keystore.destroy(a)
    assert keystore.decrypt(b, kept) == b"still readable"


@pytest.mark.unit
def test_decrypt_rejects_ciphertext_that_does_not_authenticate(keystore: LocalKeyStore) -> None:
    tenant = uuid4()
    payload = keystore.encrypt(tenant, b"authentic")
    tampered = EncryptedPayload(ciphertext=payload.ciphertext[:-4] + b"AAAA", key_id=payload.key_id)
    with pytest.raises(KeyUnavailableError):
        keystore.decrypt(tenant, tampered)
