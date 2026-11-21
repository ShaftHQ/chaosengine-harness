"""Contract test for the dual-audience spec template (#155)."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
TEMPLATE = ROOT / "references" / "spec-template.md"
SKILL = ROOT / "skills" / "work-item" / "SKILL.md"
CONTRACT = ROOT / "references" / "work-item.md"

REQUIRED = (
    "## TL;DR",
    "## Evidence",
    "## Defect inventory",
    "## Agent brief",
    "### Goal and role",
    "### Context",
    "### File scope",
    "### Steps",
    "### Constraints and non-goals",
    "### Stop and ask when",
    "### Report back",
    "## User Scenarios & Testing",
    "## Edge Cases",
    "## Functional Requirements",
    "## Success Criteria",
    "## Assumptions or Out of scope",
    "## Verify",
    "## Definition of done",
)


def missing_headings(text: str) -> list[str]:
    return [heading for heading in REQUIRED if heading not in text]


def brief_lines(text: str) -> int:
    start = text.index("## Agent brief")
    end = text.index("## User Scenarios & Testing")
    return len(text[start:end].splitlines())


def test_template_has_required_headings():
    text = TEMPLATE.read_text(encoding="utf-8")
    assert missing_headings(text) == []
    assert brief_lines(text) <= 150
    assert "≤5" in text or "at most 5" in text
    assert "150" in text


def test_removed_heading_fails_the_contract():
    text = TEMPLATE.read_text(encoding="utf-8").replace("## Evidence", "## Notes", 1)
    missing = missing_headings(text)
    assert "## Evidence" in missing


def test_work_item_points_at_shaft_engine_not_this_repo():
    skill = SKILL.read_text(encoding="utf-8")
    contract = CONTRACT.read_text(encoding="utf-8")
    for text in (skill, contract):
        assert "ShaftHQ/SHAFT_ENGINE" in text
        assert "not in this repository" in text or "not in this repo" in text
    assert "hypothesis" in skill
    assert "1:1" in skill or "1:1" in contract
    assert "spec-template.md" in skill
