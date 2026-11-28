#!/usr/bin/env python3
"""Report check and dispatch width cap for delegate returns.

The 16_000/N course budget is a reference point only. This cap is 4_000 bytes
for one report. Width default is 6 prompts. An unusable report is not a finding.
"""

from __future__ import annotations

import re

DEFAULT_CAP = 4000
DEFAULT_WIDTH = 6
CITATION = re.compile(r"(?:https?://\S+)|(?:\b[\w./-]+:\d+\b)")


def check_report(text: str, *, cap: int = DEFAULT_CAP) -> dict[str, str]:
    body = text or ""
    if not body.strip():
        return {"status": "unusable", "reason": "empty"}
    if len(body.encode("utf-8")) > cap:
        return {"status": "unusable", "reason": "over-cap"}
    if CITATION.search(body) is None:
        return {"status": "unusable", "reason": "no-citation"}
    return {"status": "usable", "reason": "cited"}


def adjudicate(text: str, *, attempt: int, cap: int = DEFAULT_CAP) -> dict[str, str | bool]:
    """First unusable redispatch. Second records no usable report and is not a finding."""
    verdict = check_report(text, cap=cap)
    if verdict["status"] == "usable":
        return {**verdict, "action": "accept", "finding": False, "note": ""}
    if attempt <= 1:
        return {
            **verdict,
            "action": "redispatch",
            "finding": False,
            "note": "Return one short report with a path:line citation.",
        }
    return {**verdict, "action": "record", "finding": False, "note": "no usable report"}


def check_width(count: int, *, cap: int = DEFAULT_WIDTH) -> dict[str, str | bool]:
    if not isinstance(count, int) or isinstance(count, bool) or count < 0:
        raise ValueError("count must be an integer >= 0")
    if count > cap:
        return {"ok": False, "correction": f"correction: width cap is {cap}"}
    return {"ok": True, "correction": ""}
