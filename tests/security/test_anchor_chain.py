"""The anchor chain, persisted — D20, I13.

The four tamper scenarios from PHASE-1-IMPLEMENTATION-PLAN §31 are proved here.
Scenario 3 is the one this task exists for: a chain rewritten wholesale verifies
internally and is caught only by the anchors.

Each scenario writes directly to the database with the append-only triggers
disabled, because the threat being modelled is exactly someone who can do that.
"""

from __future__ import annotations

import pytest
from sqlalchemy import Engine, text
from sqlalchemy.exc import DBAPIError, ProgrammingError
from sqlalchemy.orm import Session

from adw.adapters.keystore_local import LocalKeyStore
from adw.domain.chain import ChainRecordHeader, seal
from adw.domain.errors import ChainIntegrityError
from adw.services import anchor_writer, audit_writer
from adw.verification.anchor_verifier import (
    verify_anchor_chain_integrity,
    verify_tenant_against_anchors,
)
from adw.verification.chain_verifier import verify_tenant_chain
from tests.security.conftest import TENANT_A, TENANT_B, commit_chain

pytestmark = pytest.mark.security


def append(session: Session, tenant: object, keystore: LocalKeyStore, count: int = 1) -> None:
    for _ in range(count):
        audit_writer.append(
            session,
            tenant_id=tenant,  # type: ignore[arg-type]
            event_type="task.transitioned",
            actor_id="agent:seed",
            payload={"detail": "x"},
            keystore=keystore,
        )


def unlock(session: Session) -> None:
    """Disable the append-only triggers, as an operator with access would."""
    session.execute(text("ALTER TABLE chain_record DISABLE TRIGGER chain_record_append_only"))
    session.execute(text("ALTER TABLE anchor_record DISABLE TRIGGER anchor_record_append_only"))


def test_anchoring_writes_one_anchor_per_due_tenant(
    chain_session: Session, dev_keystore: LocalKeyStore
) -> None:
    append(chain_session, TENANT_A, dev_keystore, 3)
    chain_session.flush()
    assert anchor_writer.run_anchoring_pass(chain_session) == 1
    assert verify_anchor_chain_integrity(chain_session) == 1


def test_a_second_pass_writes_nothing_when_nothing_advanced(
    chain_session: Session, dev_keystore: LocalKeyStore
) -> None:
    """Effectively idempotent: a tenant whose chain has not moved is not due."""
    append(chain_session, TENANT_A, dev_keystore, 2)
    chain_session.flush()
    assert anchor_writer.run_anchoring_pass(chain_session) == 1
    assert anchor_writer.run_anchoring_pass(chain_session) == 0


def test_anchor_matches_the_tenant_head(
    chain_session: Session, dev_keystore: LocalKeyStore
) -> None:
    append(chain_session, TENANT_A, dev_keystore, 4)
    chain_session.flush()
    anchor_writer.run_anchoring_pass(chain_session)
    assert verify_tenant_against_anchors(chain_session, TENANT_A) == 1


def test_anchors_interleave_across_tenants(
    owner_engine: Engine, anchor_session: Session, dev_keystore: LocalKeyStore
) -> None:
    """Entanglement: one tenant's anchors depend on another's."""
    commit_chain(owner_engine, dev_keystore, TENANT_A, "northwind", 2)
    commit_chain(owner_engine, dev_keystore, TENANT_B, "contoso", 2)

    assert anchor_writer.run_anchoring_pass(anchor_session) == 2
    assert verify_anchor_chain_integrity(anchor_session) == 2

    tenants = (
        anchor_session.execute(text("SELECT tenant_id FROM anchor_record ORDER BY anchor_seq"))
        .scalars()
        .all()
    )
    assert len(set(tenants)) == 2


# --------------------------------------------------------------------------
# The four tamper scenarios
# --------------------------------------------------------------------------


def test_scenario_1_mid_chain_modification(
    chain_session: Session, dev_keystore: LocalKeyStore
) -> None:
    """Detected by the record chain alone."""
    append(chain_session, TENANT_A, dev_keystore, 4)
    chain_session.flush()
    unlock(chain_session)
    chain_session.execute(
        text("UPDATE chain_record SET payload_digest = :d WHERE seq = 2"), {"d": "f" * 64}
    )
    with pytest.raises(ChainIntegrityError, match="seq 2"):
        verify_tenant_chain(chain_session, TENANT_A)


def test_scenario_2_truncation_below_an_anchor(
    chain_session: Session, dev_keystore: LocalKeyStore
) -> None:
    """Deleting anchored records is caught against the anchors."""
    append(chain_session, TENANT_A, dev_keystore, 4)
    chain_session.flush()
    anchor_writer.run_anchoring_pass(chain_session)
    unlock(chain_session)
    chain_session.execute(text("DELETE FROM chain_record WHERE seq > 2"))
    chain_session.execute(
        text(
            "UPDATE chain_head SET seq = 2, head_hash = "
            "(SELECT record_hash FROM chain_record WHERE seq = 2)"
        )
    )
    # The chain and its head now agree, so the local check passes...
    verify_tenant_chain(chain_session, TENANT_A)
    # ...and the anchor catches it.
    with pytest.raises(ChainIntegrityError, match="truncated"):
        verify_tenant_against_anchors(chain_session, TENANT_A)


def test_scenario_3_wholesale_rewrite(chain_session: Session, dev_keystore: LocalKeyStore) -> None:
    """The scenario a chain alone cannot catch — the reason anchoring exists.

    Every record from seq 2 forward is re-sealed so the chain is internally
    consistent and its head agrees. Verification of the chain passes. Only the
    anchor, taken before the rewrite, disagrees.
    """
    append(chain_session, TENANT_A, dev_keystore, 4)
    chain_session.flush()
    anchor_writer.run_anchoring_pass(chain_session)
    unlock(chain_session)

    rows = chain_session.execute(
        text(
            "SELECT seq, prev_hash, event_type, actor_id, event_time, payload_digest, "
            "key_id, hash_algorithm FROM chain_record ORDER BY seq"
        )
    ).all()

    prev = rows[0].prev_hash
    for row in rows:
        actor = "agent:forged" if row.seq >= 2 else row.actor_id
        header = ChainRecordHeader(
            tenant_id=TENANT_A,
            seq=row.seq,
            prev_hash=prev,
            event_type=row.event_type,
            actor_id=actor,
            event_time=row.event_time,
            payload_digest=row.payload_digest,
            key_id=row.key_id,
            hash_algorithm=row.hash_algorithm,
        )
        sealed = seal(header)
        chain_session.execute(
            text(
                "UPDATE chain_record SET prev_hash = :p, actor_id = :a, record_hash = :h "
                "WHERE seq = :s"
            ),
            {"p": prev, "a": actor, "h": sealed.record_hash, "s": row.seq},
        )
        prev = sealed.record_hash
    chain_session.execute(text("UPDATE chain_head SET head_hash = :h"), {"h": prev})

    # Internally consistent — the chain alone sees nothing wrong.
    verify_tenant_chain(chain_session, TENANT_A)
    # The anchor taken before the rewrite disagrees.
    with pytest.raises(ChainIntegrityError, match="rewritten"):
        verify_tenant_against_anchors(chain_session, TENANT_A)


def test_scenario_4_anchor_tampering(
    owner_engine: Engine, anchor_session: Session, dev_keystore: LocalKeyStore
) -> None:
    """Editing an anchor breaks the anchor chain's own entanglement."""
    commit_chain(owner_engine, dev_keystore, TENANT_A, "northwind", 2)
    commit_chain(owner_engine, dev_keystore, TENANT_B, "contoso", 2)
    anchor_writer.run_anchoring_pass(anchor_session)
    anchor_session.commit()

    with Session(owner_engine) as tamper_session:
        unlock(tamper_session)
        tamper_session.execute(
            text("UPDATE anchor_record SET tenant_head_hash = :h WHERE anchor_seq = 1"),
            {"h": "0" * 64},
        )
        tamper_session.commit()

    with Session(owner_engine) as check:
        with pytest.raises(ChainIntegrityError, match="anchor_seq 1"):
            verify_anchor_chain_integrity(check)


def test_repairing_an_anchor_breaks_every_later_one(
    owner_engine: Engine, anchor_session: Session, dev_keystore: LocalKeyStore
) -> None:
    """The cost anchoring imposes, demonstrated.

    An operator who rewrites a tenant chain must edit its anchor to match; the
    edited anchor then no longer links to its successor, and every later anchor —
    including other tenants' — must be rewritten too. That is what makes
    selective tampering expensive rather than merely detectable.
    """
    commit_chain(owner_engine, dev_keystore, TENANT_A, "northwind", 2)
    anchor_writer.run_anchoring_pass(anchor_session)
    anchor_session.commit()
    commit_chain(owner_engine, dev_keystore, TENANT_B, "contoso", 2)
    anchor_writer.run_anchoring_pass(anchor_session)
    anchor_session.commit()
    assert verify_anchor_chain_integrity(anchor_session) == 2

    with Session(owner_engine) as tamper_session:
        unlock(tamper_session)
        tamper_session.execute(
            text("UPDATE anchor_record SET tenant_head_hash = :h WHERE anchor_seq = 1"),
            {"h": "9" * 64},
        )
        tamper_session.commit()

    with Session(owner_engine) as check:
        with pytest.raises(ChainIntegrityError):
            verify_anchor_chain_integrity(check)


# --------------------------------------------------------------------------
# Access control
# --------------------------------------------------------------------------


def test_runtime_role_cannot_read_anchors(app_engine: Engine, migrated_schema: None) -> None:
    """I13: anchors expose which tenants exist and how active each one is."""
    for table in ("anchor_record", "anchor_head"):
        with pytest.raises(ProgrammingError, match="permission denied"), app_engine.begin() as conn:
            conn.execute(text(f"SELECT * FROM {table}"))


def test_anchor_role_can_write_anchors_but_not_read_chain_records(
    anchor_engine: Engine, migrated_schema: None
) -> None:
    with anchor_engine.begin() as conn:
        assert conn.execute(text("SELECT count(*) FROM anchor_record")).scalar_one() == 0
        assert conn.execute(text("SELECT count(*) FROM chain_head")).scalar_one() == 0

    with pytest.raises(ProgrammingError, match="permission denied"), anchor_engine.begin() as conn:
        conn.execute(text("SELECT * FROM chain_record"))


def test_anchors_are_append_only(
    owner_engine: Engine, anchor_session: Session, dev_keystore: LocalKeyStore
) -> None:
    """A row must exist, or a per-row trigger has nothing to fire on."""
    commit_chain(owner_engine, dev_keystore, TENANT_A, "northwind", 2)
    anchor_writer.run_anchoring_pass(anchor_session)
    anchor_session.commit()

    for statement in (
        "UPDATE anchor_record SET anchor_hash = 'forged'",
        "DELETE FROM anchor_record",
    ):
        with pytest.raises(DBAPIError, match="append-only"), owner_engine.begin() as conn:
            conn.execute(text(statement))
