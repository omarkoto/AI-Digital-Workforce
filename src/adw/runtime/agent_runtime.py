"""The Agent Runtime — `ARCHITECTURE.md` §10, `PHASE-2-IMPLEMENTATION-PLAN.md` §2.5.

Executes **one task** under **one pinned Agent Definition version**: assemble
context, call the model, interpret the answer, record everything, and stop when
the work is done or a limit trips.

This is the least-trusted component in the system, and the constraints on it are
the point rather than the paperwork:

* **It holds no credentials.** It gets a session and a provider, both already
  constructed. It cannot open a connection, and it never sees an API key.
* **It executes nothing** (I2). A tool call is detected, recorded, and refused.
* **Model output is data.** A completion is recorded and returned; it is never
  fed back as instruction, and the instruction region is a pure function of
  pinned content (see :mod:`adw.runtime.context`).
* **It does not survive its task.** No state persists in the object between runs;
  everything that matters is in the database before the call returns.
* **It never claims completion without evidence.** Every turn is an Action with
  the prompt and the completion recorded, and the run's outcome is derived from
  those records rather than from anything the model asserted about itself.

It also does not decide whether the work was *good*. That is a Control Gate's
job, and an agent judging its own output would be the self-approval D4 forbids.
The runtime reports what happened; the gate decides what it was worth.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from enum import StrEnum

from sqlalchemy.orm import Session

from adw.models.definition import AgentDefinitionVersion, SkillVersion
from adw.models.task import Task
from adw.ports.blobstore import BlobStore
from adw.ports.keystore import KeyStore
from adw.ports.llm import LLMProvider
from adw.runtime import model_call, tool_proposal
from adw.runtime.context import UntrustedInput, assemble
from adw.services import action_recorder, audit_writer, cost_service, evidence_recorder

EVENT_TOOL_PROPOSAL_REFUSED = "tool.proposal_refused"
EVIDENCE_TOOL_PROPOSAL = "llm.tool_proposal"

DEFAULT_MAX_TURNS = 3
"""A hard stop, not a target. `PRODUCT.md` §25 makes limits hard stops rather
than alerts, and an agent loop is one of the two unbounded spend paths."""


class StopReason(StrEnum):
    """Why a run ended. Persisted vocabulary, not a log string."""

    COMPLETED = "completed"
    """The model answered without asking for a tool."""

    EMPTY_COMPLETION = "empty_completion"
    """The model answered with nothing. Not success — an agent that said nothing
    and an agent that answered are different facts."""

    PROVIDER_FAILED = "provider_failed"
    """The call did not produce a completion. The failure is recorded as a failed
    Action with its evidence."""

    TURN_LIMIT = "turn_limit"
    """The run hit its ceiling. Never presented as success: work stopped short of
    an answer, and saying otherwise would be the claim `CLAUDE.md` §3 forbids."""

    BUDGET_EXHAUSTED = "budget_exhausted"
    """The execution's token ceiling was reached. The run paused *before* making
    a call rather than truncating one, so the record says "we stopped" instead of
    presenting a half-written answer as a whole one (`PRODUCT.md` §25)."""


@dataclass(frozen=True, slots=True)
class AgentRun:
    """What one task's execution produced, derived from the records it wrote."""

    task: Task
    stop_reason: StopReason
    turns: tuple[model_call.RecordedCompletion, ...] = field(default=())
    refused_proposals: tuple[tool_proposal.ToolProposal, ...] = field(default=())
    budget: cost_service.BudgetReading | None = None
    """Spend against the ceiling as of the moment the run ended."""

    @property
    def succeeded(self) -> bool:
        return self.stop_reason is StopReason.COMPLETED

    @property
    def output(self) -> str | None:
        """The final completion, or ``None`` if the run produced no answer.

        ``None`` rather than an empty string, so a caller cannot accidentally
        treat "no answer" as "an empty answer" and write it into an artifact.
        """
        if not self.succeeded or not self.turns:
            return None
        response = self.turns[-1].response
        return response.content if response is not None else None

    @property
    def prompt_tokens(self) -> int:
        return sum(
            turn.response.usage.prompt_tokens for turn in self.turns if turn.response is not None
        )

    @property
    def completion_tokens(self) -> int:
        return sum(
            turn.response.usage.completion_tokens
            for turn in self.turns
            if turn.response is not None
        )

    @property
    def total_tokens(self) -> int:
        return self.prompt_tokens + self.completion_tokens


def _record_refusal(
    session: Session,
    *,
    task: Task,
    sequence: int,
    proposal: tool_proposal.ToolProposal,
    keystore: KeyStore,
    blobstore: BlobStore,
    actor_id: str,
) -> None:
    """Record a proposed tool call that was refused.

    The Action stays at ``planned`` and never moves. That is the literal truth:
    the plan — the model's, in this case — said this should occur, and it never
    became an attempt. ``failed`` would be wrong, because `CLAUDE.md` §3 defines
    it as having run and not met its criteria, and nothing ran.
    """
    action = action_recorder.plan_action(
        session, task=task, sequence=sequence, tool_name=proposal.tool_name
    )
    evidence_recorder.record_for_action(
        session,
        action=action,
        kind=EVIDENCE_TOOL_PROPOSAL,
        payload={
            "tool_name": proposal.tool_name,
            "proposal": proposal.raw,
            "outcome": "refused",
            "reason": (
                "no tool gateway exists; the runtime may propose a tool call, never perform one"
            ),
        },
        keystore=keystore,
        blobstore=blobstore,
    )
    audit_writer.append(
        session,
        tenant_id=task.tenant_id,
        event_type=EVENT_TOOL_PROPOSAL_REFUSED,
        actor_id=actor_id,
        payload={
            "task_id": str(task.id),
            "action_id": str(action.id),
            "tool_name": proposal.tool_name,
        },
        keystore=keystore,
    )


def run_task(
    session: Session,
    *,
    task: Task,
    agent_version: AgentDefinitionVersion,
    skill_versions: Sequence[SkillVersion] = (),
    inputs: Sequence[UntrustedInput] = (),
    task_instruction: str | None = None,
    provider: LLMProvider,
    keystore: KeyStore,
    blobstore: BlobStore,
    actor_id: str,
    max_turns: int = DEFAULT_MAX_TURNS,
    max_output_tokens: int | None = None,
    temperature: float | None = None,
) -> AgentRun:
    """Run one task to an answer, a refusal, or a limit.

    Must be called inside a transaction already scoped to ``task.tenant_id``.
    Does not move the Task's state — that belongs to ``task_service`` and to the
    gate that judges the result, so a run cannot mark its own work finished.

    ``agent_version`` and ``skill_versions`` are the *pinned* versions the task
    carries. They are passed as resolved objects rather than looked up here, so
    that the runtime cannot silently pick up newer instructions than the ones the
    record says governed this task (D9/I4).
    """
    if max_turns < 1:
        msg = "max_turns must be at least 1"
        raise ValueError(msg)

    turns: list[model_call.RecordedCompletion] = []
    refused: list[tool_proposal.ToolProposal] = []
    conversation = list(inputs)
    # Continue the task's action sequence rather than restarting it. A task that
    # failed a gate and came back for rework runs this method again, and the
    # record has to be able to say what happened first.
    sequence = action_recorder.next_sequence(session, task) - 1

    for _ in range(max_turns):
        # Checked before the call, never after. A stop that happens before a
        # request is an honest "we stopped"; one that cuts a response short
        # leaves an answer that looks complete and is not (`PRODUCT.md` §25).
        budget = cost_service.check_before_spending(
            session,
            tenant_id=task.tenant_id,
            execution_id=task.execution_id,
            keystore=keystore,
            actor_id=actor_id,
        )
        if not budget.may_continue:
            return AgentRun(
                task=task,
                stop_reason=StopReason.BUDGET_EXHAUSTED,
                turns=tuple(turns),
                refused_proposals=tuple(refused),
                budget=budget,
            )

        sequence += 1
        outcome = model_call.invoke(
            session,
            task=task,
            sequence=sequence,
            provider=provider,
            request=assemble(
                agent_version=agent_version,
                skill_versions=skill_versions,
                inputs=conversation,
                task_instruction=task_instruction,
                max_output_tokens=max_output_tokens,
                temperature=temperature,
            ),
            keystore=keystore,
            blobstore=blobstore,
            actor_id=actor_id,
        )
        turns.append(outcome)

        if outcome.response is None:
            return AgentRun(
                task=task,
                stop_reason=StopReason.PROVIDER_FAILED,
                turns=tuple(turns),
                refused_proposals=tuple(refused),
                budget=budget,
            )

        # Recorded immediately, so the next turn's check sees this turn's spend.
        # A budget that only totals up at the end cannot stop anything.
        cost_service.record_usage(
            session,
            action=outcome.action,
            execution_id=task.execution_id,
            response=outcome.response,
        )

        content = outcome.response.content
        proposal = tool_proposal.detect(content)
        if proposal is not None:
            sequence += 1
            _record_refusal(
                session,
                task=task,
                sequence=sequence,
                proposal=proposal,
                keystore=keystore,
                blobstore=blobstore,
                actor_id=actor_id,
            )
            refused.append(proposal)
            # The refusal goes back as *data*, in the same fenced region a real
            # tool result would occupy. It is a fact about the world, not a new
            # instruction, and the instruction region stays untouched.
            conversation = [
                *conversation,
                UntrustedInput(
                    label=f"platform notice: refused tool call {proposal.tool_name!r}",
                    content=tool_proposal.REFUSAL_NOTICE,
                ),
            ]
            continue

        if not content.strip():
            return AgentRun(
                task=task,
                stop_reason=StopReason.EMPTY_COMPLETION,
                turns=tuple(turns),
                refused_proposals=tuple(refused),
                budget=cost_service.read_budget(session, task.execution_id),
            )

        return AgentRun(
            task=task,
            stop_reason=StopReason.COMPLETED,
            turns=tuple(turns),
            refused_proposals=tuple(refused),
            budget=cost_service.read_budget(session, task.execution_id),
        )

    return AgentRun(
        task=task,
        stop_reason=StopReason.TURN_LIMIT,
        turns=tuple(turns),
        refused_proposals=tuple(refused),
        budget=cost_service.read_budget(session, task.execution_id),
    )
