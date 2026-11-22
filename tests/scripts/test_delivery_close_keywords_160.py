"""Delivery cycle must name GitHub closing keywords and the safe wording."""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CYCLE = ROOT / "references" / "delivery-cycle.md"

KEYWORDS = (
    "close",
    "closes",
    "closed",
    "fix",
    "fixes",
    "fixed",
    "resolve",
    "resolves",
    "resolved",
)

# Longest form first. This source must not place one of those words beside a number.
_ALTERNATION = "|".join(
    (
        "closes",
        "closed",
        "close",
        "fixes",
        "fixed",
        "fix",
        "resolves",
        "resolved",
        "resolve",
    )
)
LIVE_KEYWORD_BEFORE_ISSUE = re.compile(
    rf"(?i)\b(?:{_ALTERNATION})\b\s*:?\s*(?:[\w.-]+/[\w.-]+)?#\d+\b"
)


def test_delivery_cycle_names_keywords_negation_and_safe_example():
    text = CYCLE.read_text(encoding="utf-8")
    assert "negation does not protect" in text
    missing = [word for word in KEYWORDS if re.search(rf"(?i)\b{re.escape(word)}\b", text) is None]
    assert missing == []
    assert re.search(r"#\d+\s+stays open", text)


def test_closing_keyword_must_not_precede_an_issue_number():
    text = CYCLE.read_text(encoding="utf-8")
    match = LIVE_KEYWORD_BEFORE_ISSUE.search(text)
    assert match is None, match.group(0)
