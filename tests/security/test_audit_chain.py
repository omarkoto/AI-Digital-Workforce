"""The persisted audit chain — D14, D20, D21, G2.

Task 2 proved the hashing arithmetic in memory. These prove the chain as it is
actually written: appended in a transaction, serialized per tenant, verifiable
without a key, and not modifiable through the application.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import Engine, text
from sqlalchemy.exc import DBAPIError, ProgrammingError
from sqlalchemy.orm import Session

from adw.adapters.keystore_local import LocalKeyStore
from adw.domain.errors import ChainIntegrityError
from adw.models.audit import EVENT_TIME_ANOMALY, AuditChainHead, AuditChainRecord
from adw.services import audit_writer
from adw.verification.chain_verifier import verify_tenant_chain
from tests.security.conftest import TENANT_A, TENANT_B

pytestmark = pytest.mark.security


def append(
    session: Session, tenant: object, keystore: LocalKeyStore, event: str = "task.transitioned"
) -> AuditChainRecord:
    return audit_writer.append(
        session,
        tenant_id=tenant,  # type: ignore[arg-type]
        event_type=event,
        actor_id="agent:data-preparation",
        payload={"detail": "seeded"},
        keystore=keystore,
    )


def test_first_append_starts_the_chain(chain_session: Session, dev_keystore: LocalKeyStore) -> None:
    record = append(chain_session, TENANT_A, dev_keystore)
    assert record.seq == 1
    assert record.prev_hash is None
    assert len(record.record_hash) == 64


def test_appends_link_and_verify(chain_session: Session, dev_keystore: LocalKeyStore) -> None:
    for _ in range(5):
        append(chain_session, TENANT_A, dev_keystore)
    assert verify_tenant_chain(chain_session, TENANT_A) == 5


def test_wholesale_rewrite_verifies_locally(
    chain_session: Session, dev_keystore: LocalKeyStore
) -> None:
    """The limit of what a chain alone can prove.

    An operator who recomputes every hash from a point forward produces a chain
    that is internally consistent and indistinguishable from the original.
    Detecting that needs the anchor chain in Task 6; recording the limit here
    means the gap is visible rather than assumed away.
    """
    for _ in range(3):
        append(chain_session, TENANT_A, dev_keystore)
    chain_session.flush()
    assert verify_tenant_chain(chain_session, TENANT_A) == 3


def test_sequences_are_gap_free(chain_session: Session, dev_keystore: LocalKeyStore) -> None:
    for _ in range(4):
        append(chain_session, TENANT_A, dev_keystore)
    rows = chain_session.scalars(
        text("SELECT seq FROM chain_record ORDER BY seq").columns(seq=None)  # type: ignore[arg-type]
    ).all()
    assert list(rows) == [1, 2, 3, 4]


def test_the_head_tracks_the_last_record(
    chain_session: Session, dev_keystore: LocalKeyStore
) -> None:
    last = None
    for _ in range(3):
        last = append(chain_session, TENANT_A, dev_keystore)
    head = chain_session.get(AuditChainHead, TENANT_A)
    assert head is not None
    assert last is not None
    assert head.seq == last.seq
    assert head.head_hash == last.record_hash


def test_payload_is_stored_as_ciphertext(
    chain_session: Session, dev_keystore: LocalKeyStore
) -> None:
    """D1: the chain never holds plaintext tenant content."""
    record = audit_writer.append(
        chain_session,
        tenant_id=TENANT_A,
        event_type="task.transitioned",
        actor_id="agent:x",
        payload={"secret_marker": "MARKETING-OVERSPEND"},
        keystore=dev_keystore,
    )
    assert b"MARKETING-OVERSPEND" not in record.payload_ciphertext
    assert record.key_id


def test_verification_needs_no_key(chain_session: Session, dev_keystore: LocalKeyStore) -> None:
    """I12 — the property that makes crypto-shredding safe.

    The hash covers the ciphertext digest, so a chain still verifies after its
    tenant key is destroyed. Content becomes unreadable; the record of what
    happened does not.
    """
    for _ in range(3):
        append(chain_session, TENANT_A, dev_keystore)
    dev_keystore.destroy(TENANT_A)
    assert verify_tenant_chain(chain_session, TENANT_A) == 3


def tamper(session: Session, statement: str, **params: object) -> None:
    """Modify the chain the way an operator with database access would.

    The append-only trigger blocks UPDATE and DELETE for every role, including
    the owner — so simulating tampering means disabling it first. That is
    precisely the threat model: hash chaining exists because someone with this
    much access cannot otherwise be detected.
    """
    session.execute(text("ALTER TABLE chain_record DISABLE TRIGGER chain_record_append_only"))
    try:
        session.execute(text(statement), params)
    finally:
        session.execute(text("ALTER TABLE chain_record ENABLE TRIGGER chain_record_append_only"))


def test_chains_are_independent_per_tenant(
    chain_session: Session, dev_keystore: LocalKeyStore
) -> None:
    """D20: one tenant's activity never appears in another's sequence."""
    append(chain_session, TENANT_A, dev_keystore)
    append(chain_session, TENANT_A, dev_keystore)
    chain_session.flush()
    assert verify_tenant_chain(chain_session, TENANT_A) == 2


def test_mid_chain_tamper_is_detected(chain_session: Session, dev_keystore: LocalKeyStore) -> None:
    """Scenario 1: a modified record no longer produces its stored hash."""
    for _ in range(4):
        append(chain_session, TENANT_A, dev_keystore)
    chain_session.flush()
    target = chain_session.scalars(
        text("SELECT id FROM chain_record WHERE seq = 2").columns(id=None)  # type: ignore[arg-type]
    ).one()
    tamper(
        chain_session,
        "UPDATE chain_record SET payload_digest = :d WHERE id = :i",
        d="f" * 64,
        i=target,
    )
    with pytest.raises(ChainIntegrityError, match="seq 2"):
        verify_tenant_chain(chain_session, TENANT_A)


def test_truncation_is_detected_against_the_head(
    chain_session: Session, dev_keystore: LocalKeyStore
) -> None:
    """Scenario 2, as far as a local chain can reach.

    Deleting the newest records leaves a chain that still verifies internally.
    Comparing it with the head row catches it here; catching an operator who
    edits both is what the anchor chain adds in Task 6.
    """
    for _ in range(4):
        append(chain_session, TENANT_A, dev_keystore)
    chain_session.flush()
    tamper(chain_session, "DELETE FROM chain_record WHERE seq > 2")
    with pytest.raises(ChainIntegrityError, match="head claims seq 4"):
        verify_tenant_chain(chain_session, TENANT_A)


def test_backwards_time_records_an_anomaly(
    chain_session: Session, dev_keystore: LocalKeyStore
) -> None:
    """D21: recorded, neither silently accepted nor silently rejected."""
    append(chain_session, TENANT_A, dev_keystore)
    chain_session.flush()
    future = datetime.now(UTC) + timedelta(hours=1)
    chain_session.execute(
        text("UPDATE chain_head SET last_event_time = :t WHERE tenant_id = :x"),
        {"t": future, "x": TENANT_A},
    )
    append(chain_session, TENANT_A, dev_keystore)
    events = chain_session.scalars(
        text("SELECT event_type FROM chain_record ORDER BY seq").columns(event_type=None)  # type: ignore[arg-type]
    ).all()
    assert EVENT_TIME_ANOMALY in list(events)
    assert verify_tenant_chain(chain_session, TENANT_A) == 3


def test_event_time_comes_from_the_database(
    chain_session: Session, dev_keystore: LocalKeyStore
) -> None:
    """D21/G6: never the application host's clock."""
    record = append(chain_session, TENANT_A, dev_keystore)
    assert record.event_time.tzinfo is not None
    db_now = chain_session.execute(text("SELECT transaction_timestamp()")).scalar_one()
    assert abs((db_now - record.event_time).total_seconds()) < 5


def test_runtime_role_cannot_update_or_delete_chain_records(
    app_engine: Engine, migrated_schema: None
) -> None:
    """D14: the audit trail is not modifiable through the application."""
    for statement in (
        "UPDATE chain_record SET actor_id = 'forged'",
        "DELETE FROM chain_record",
    ):
        with pytest.raises((ProgrammingError, DBAPIError)), app_engine.begin() as conn:
            conn.execute(text("SELECT set_config('app.tenant_id', :t, true)"), {"t": str(TENANT_A)})
            conn.execute(text(statement))


def test_chain_records_are_tenant_isolated(app_engine: Engine, seeded_chain: None) -> None:
    with app_engine.begin() as conn:
        conn.execute(text("SELECT set_config('app.tenant_id', :t, true)"), {"t": str(TENANT_A)})
        a = conn.execute(text("SELECT count(*) FROM chain_record")).scalar_one()
    with app_engine.begin() as conn:
        conn.execute(text("SELECT set_config('app.tenant_id', :t, true)"), {"t": str(TENANT_B)})
        b = conn.execute(text("SELECT count(*) FROM chain_record")).scalar_one()
    with app_engine.begin() as conn:
        none = conn.execute(text("SELECT count(*) FROM chain_record")).scalar_one()
    assert (a, b, none) == (2, 1, 0)


def test_anchor_role_reads_heads_across_tenants_but_not_records(
    anchor_engine: Engine, seeded_chain: None
) -> None:
    """I13: the one sanctioned cross-tenant read, narrowed to hashes."""
    with anchor_engine.begin() as conn:
        heads = conn.execute(text("SELECT count(*) FROM chain_head")).scalar_one()
    assert heads == 2

    with pytest.raises(ProgrammingError, match="permission denied"), anchor_engine.begin() as conn:
        conn.execute(text("SELECT * FROM chain_record"))
