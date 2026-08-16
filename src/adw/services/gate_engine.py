"""The Gate Engine — D4, D13, I5.

Produces verdicts. Never fixes anything, never produces artifacts, and never
overrides a human verdict.

Deterministic evaluators are the platform's primary compensating control against
prompt injection: **an injected instruction cannot persuade a deterministic check
to pass**. A model can be talked into anything; a reconciliation check cannot.
That is why D13 leans on gates, and why every evaluator here is a plain function
over recorded values.

Phase 1 ships two evaluators. They exist to prove the mechanism and the FAIL
path, and are **not** the Finance gates — those belong to the Finance vertical,
which `PRODUCT.md` §12 places outside MVP platform work.
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Final
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from adw.domain.errors import DomainError
from adw.domain.states import GateEvaluationKind, GateVerdict
from adw.models.artifact import ArtifactVersion
from adw.models.gate import GateDecision, GateDefinitionVersion
from adw.ports.blobstore import BlobStore
from adw.ports.keystore import KeyStore
from adw.services import artifact_service, audit_writer

EVENT_GATE_DECIDED: Final = "gate.decided"

NUMBER_PATTERN: Final = re.compile(r"-?\d[\d,]*\.?\d*")


class SelfApprovalError(DomainError):
    """The producer of an artifact attempted to approve the gate covering it.

    D4: enforced in code, not by prompt instruction. The database refuses the row
    as well; this refusal exists so the caller gets an explanation rather than a
    constraint violation.
    """


class UnknownRuleError(DomainError):
    """A gate definition names an evaluator that is not registered."""


@dataclass(frozen=True, slots=True)
class Evaluation:
    """The outcome of running one evaluator."""

    passed: bool
    detail: str | None = None


Evaluator = Callable[[object, Mapping[str, object]], Evaluation]


def _normalise(token: str) -> str:
    return token.replace(",", "").rstrip(".")


def required_fields_present(content: object, config: Mapping[str, object]) -> Evaluation:
    """Every field named in the config appears, non-empty, in the content."""
    declared = config.get("required_fields", [])
    required = [str(name) for name in declared] if isinstance(declared, list) else []
    if not isinstance(content, Mapping):
        return Evaluation(passed=False, detail="content is not a mapping")
    missing = [name for name in required if not content.get(name)]
    if missing:
        return Evaluation(passed=False, detail=f"missing or empty fields: {sorted(missing)}")
    return Evaluation(passed=True)


def figures_traceable(content: object, config: Mapping[str, object]) -> Evaluation:
    """Every figure in the narrative resolves to a value in the source dataset.

    The characteristic failure of a language model asked to write about numbers
    is a plausible figure with no source. It is also mechanically detectable,
    which is the whole argument for deterministic gates.
    """
    if not isinstance(content, Mapping):
        return Evaluation(passed=False, detail="content is not a mapping")

    narrative = str(content.get(str(config.get("narrative_field", "narrative")), ""))
    dataset = content.get(str(config.get("dataset_field", "dataset")), [])
    known = {
        _normalise(str(value))
        for row in (dataset if isinstance(dataset, list) else [])
        if isinstance(row, Mapping)
        for value in row.values()
    }

    unsourced = [
        token
        for token in (_normalise(m.group()) for m in NUMBER_PATTERN.finditer(narrative))
        if token not in known
    ]
    if unsourced:
        return Evaluation(
            passed=False,
            detail=f"figures not present in the source dataset: {sorted(set(unsourced))}",
        )
    return Evaluation(passed=True)


EVALUATORS: Final[Mapping[str, Evaluator]] = {
    "required_fields_present": required_fields_present,
    "figures_traceable": figures_traceable,
}


def _database_now(session: Session) -> datetime:
    now: datetime = session.execute(select(func.transaction_timestamp())).scalar_one()
    return now


def evaluate(
    session: Session,
    *,
    artifact_version: ArtifactVersion,
    gate_definition_version: GateDefinitionVersion,
    task_id: UUID,
    decided_by_identity: str,
    keystore: KeyStore,
    blobstore: BlobStore,
    actor_id: str,
) -> GateDecision:
    """Run a deterministic gate and record its verdict.

    Raises:
        SelfApprovalError: if the decider is the artifact's producer (D4/I5).
        UnknownRuleError: if the pinned rule has no registered evaluator.
    """
    if decided_by_identity == artifact_version.producing_agent_identity:
        msg = (
            f"{decided_by_identity!r} produced this artifact version and cannot decide the "
            "gate covering it"
        )
        raise SelfApprovalError(msg)

    evaluator = EVALUATORS.get(gate_definition_version.rule_id)
    if evaluator is None:
        msg = f"no evaluator registered for rule {gate_definition_version.rule_id!r}"
        raise UnknownRuleError(msg)

    raw = artifact_service.read_content(artifact_version, keystore=keystore, blobstore=blobstore)
    content = json.loads(raw.decode("utf-8"))
    config = json.loads(gate_definition_version.config_json)
    outcome = evaluator(content, config)

    return record_decision(
        session,
        artifact_version=artifact_version,
        gate_definition_version=gate_definition_version,
        task_id=task_id,
        verdict=GateVerdict.PASS if outcome.passed else GateVerdict.FAIL,
        decided_by_identity=decided_by_identity,
        failure_detail=outcome.detail,
        keystore=keystore,
        actor_id=actor_id,
    )


def record_decision(
    session: Session,
    *,
    artifact_version: ArtifactVersion,
    gate_definition_version: GateDefinitionVersion,
    task_id: UUID,
    verdict: GateVerdict,
    decided_by_identity: str,
    keystore: KeyStore,
    actor_id: str,
    failure_detail: str | None = None,
    waiver_reason: str | None = None,
) -> GateDecision:
    """Persist a verdict and record it in the audit chain.

    Used by :func:`evaluate` for deterministic gates and by the approval service
    for human ones, so every verdict reaches the record the same way.
    """
    if decided_by_identity == artifact_version.producing_agent_identity:
        msg = (
            f"{decided_by_identity!r} produced this artifact version and cannot decide the "
            "gate covering it"
        )
        raise SelfApprovalError(msg)

    decision = GateDecision(
        tenant_id=artifact_version.tenant_id,
        gate_definition_version_id=gate_definition_version.id,
        artifact_version_id=artifact_version.id,
        task_id=task_id,
        verdict=verdict,
        decided_by_identity=decided_by_identity,
        producer_identity=artifact_version.producing_agent_identity,
        decided_at=_database_now(session),
        rule_id=gate_definition_version.rule_id,
        evaluation_kind=gate_definition_version.evaluation_kind,
        failure_detail=failure_detail,
        waiver_reason=waiver_reason,
    )
    session.add(decision)
    session.flush()

    audit_writer.append(
        session,
        tenant_id=artifact_version.tenant_id,
        event_type=EVENT_GATE_DECIDED,
        actor_id=actor_id,
        payload={
            "gate_decision_id": str(decision.id),
            "artifact_version_id": str(artifact_version.id),
            "artifact_version_no": artifact_version.version_no,
            "verdict": verdict.value,
            "decided_by_identity": decided_by_identity,
            "producer_identity": artifact_version.producing_agent_identity,
            "rule_id": gate_definition_version.rule_id,
            "evaluation_kind": gate_definition_version.evaluation_kind.value,
            "failure_detail": failure_detail,
            "waiver_reason": waiver_reason,
        },
        keystore=keystore,
    )
    return decision


def is_deterministic(decision: GateDecision) -> bool:
    """Whether a verdict came from a check that cannot be argued with.

    `DESIGN.md` §11.5 requires a model-assessed verdict never to be presented
    with the same finality as a deterministic one.
    """
    return decision.evaluation_kind is GateEvaluationKind.DETERMINISTIC
