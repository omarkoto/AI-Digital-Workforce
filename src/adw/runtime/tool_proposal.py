"""Detecting a tool call the model asked for — I2.

**The runtime may propose a tool call. It may never perform one.** In Phase 2
there is no Tool Gateway at all, so every proposal is refused. That is not a gap
waiting to be filled in: refusing is the correct behaviour for a runtime with no
gateway, and it stays correct afterwards, because the gateway — not the runtime —
is what will decide whether a proposal is honoured.

A proposal arrives as *text*, because :class:`~adw.ports.llm.CompletionRequest`
carries no tool schema and a provider therefore has no structured channel for
one. Detection is a deterministic pattern match, not a judgement call, so what
counts as a proposal is the same on every run and is reviewable here rather than
inferred from behaviour.

Detection is best-effort and openly so: a model can describe wanting a tool in
prose this will not match. That costs nothing, because an undetected proposal is
just text in a completion — the runtime still cannot execute it. What detection
buys is a *recorded* attempt and a refusal the agent can see, rather than a
silent dead end the agent keeps walking into.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Final

PROPOSAL_PATTERN: Final = re.compile(
    r"^\s*(?:TOOL_CALL|TOOL|CALL_TOOL)\s*[:=]\s*(?P<name>[A-Za-z][\w.\-]*)\s*(?P<args>.*)$",
    re.IGNORECASE | re.MULTILINE,
)
"""Several spellings, because the convention is stated in prose to a model and a
model will paraphrase it. Anchored to the start of a line so a tool named inside
a sentence is prose, not a proposal."""

REFUSAL_NOTICE: Final = (
    "Your request to call a tool was refused. This runtime has no tool gateway, "
    "so no tool can be executed and none will be. The refusal has been recorded. "
    "Answer using only the data you were given, and if the data does not support "
    "an answer, say exactly what is missing."
)
"""Fed back to the agent as untrusted data, like every other tool result would
be. It is a fact about the world, not a new instruction, and it goes in the data
region for the same reason a tool's output would."""


@dataclass(frozen=True, slots=True)
class ToolProposal:
    """A tool the model asked to have invoked."""

    tool_name: str
    raw: str
    """The matched line, recorded verbatim as evidence of what was asked for."""


def detect(content: str) -> ToolProposal | None:
    """Return the first tool proposal in ``content``, or ``None``.

    The first only. One refusal per turn is enough to tell the agent the channel
    is closed, and recording a cascade of proposals from a single confused
    completion adds noise to the record without adding a fact to it.
    """
    match = PROPOSAL_PATTERN.search(content)
    if match is None:
        return None
    return ToolProposal(tool_name=match.group("name"), raw=match.group(0).strip())
