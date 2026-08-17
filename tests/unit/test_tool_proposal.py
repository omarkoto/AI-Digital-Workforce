"""Detecting a proposed tool call — I2.

Detection is deterministic and reviewable here rather than inferred from
behaviour, which is the only reason a pattern is preferable to a judgement.
"""

from __future__ import annotations

import pytest

from adw.runtime.tool_proposal import detect

pytestmark = pytest.mark.unit


@pytest.mark.parametrize(
    ("content", "expected"),
    [
        ("TOOL_CALL: spreadsheet.read", "spreadsheet.read"),
        ("tool_call: spreadsheet.read", "spreadsheet.read"),
        ("TOOL: python.run", "python.run"),
        ("CALL_TOOL = database.query", "database.query"),
        ('Here is my plan.\nTOOL_CALL: chart.create {"series": 3}', "chart.create"),
        ("  TOOL_CALL:   pdf.render  ", "pdf.render"),
    ],
)
def test_a_proposal_is_detected(content: str, expected: str) -> None:
    proposal = detect(content)
    assert proposal is not None
    assert proposal.tool_name == expected


def test_the_matched_line_is_kept_verbatim_as_evidence() -> None:
    proposal = detect('TOOL_CALL: chart.create {"series": 3}')
    assert proposal is not None
    assert proposal.raw == 'TOOL_CALL: chart.create {"series": 3}'


@pytest.mark.parametrize(
    "content",
    [
        "Revenue rose 12% against a 9% plan.",
        "I would need a tool call to read the spreadsheet, but I will work from the data given.",
        "The variance tool_call convention is described in the appendix.",
        "",
    ],
)
def test_prose_about_tools_is_not_a_proposal(content: str) -> None:
    """Anchored to the start of a line, so a tool named inside a sentence stays prose."""
    assert detect(content) is None


def test_only_the_first_proposal_is_returned() -> None:
    """One refusal per turn is enough to tell the agent the channel is closed."""
    proposal = detect("TOOL_CALL: first.tool\nTOOL_CALL: second.tool")
    assert proposal is not None
    assert proposal.tool_name == "first.tool"
