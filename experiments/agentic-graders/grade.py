#!/usr/bin/env python3
"""Offline graders for frozen harness-ab traces and labelled fixtures.

No vendor API key. A loop cap is not added here. The report records whether
the traces showed a material rate of identical-call loops or uncited answers.
"""

from __future__ import annotations

import json
from pathlib import Path

HEREDOC_STUB = "Execute: python3 - <<"
MATERIAL_RATE = 0.20


def grade_fixture(fixture: dict) -> dict:
    """Flag identical tool calls, missing citations, or an obviously wrong tool."""
    flags: list[str] = []
    calls = [str(item) for item in fixture.get("calls") or []]
    if any(left and left == right for left, right in zip(calls, calls[1:])):
        flags.append("identical-tool-calls")
    if fixture.get("expects_citation") and not list(fixture.get("citations") or []):
        flags.append("missing-citations")
    task = str(fixture.get("task") or "").casefold()
    choice = str(fixture.get("tool_choice") or "").casefold()
    if "local file" in task and choice == "web-search":
        flags.append("wrong-tool-choice")
    expect_fail = fixture.get("label") == "fail"
    return {
        "id": fixture.get("id"),
        "flags": flags,
        "ok": expect_fail == bool(flags) if fixture.get("label") in {"fail", "pass"} else not flags,
    }


def grade_fixtures(fixtures: list[dict]) -> list[dict]:
    return [grade_fixture(item) for item in fixtures]


def _tool_lines(text: str) -> list[str]:
    calls: list[str] = []
    in_tools = False
    for line in text.splitlines():
        if line.startswith("## Tools"):
            in_tools = True
            continue
        if line.startswith("## "):
            in_tools = False
            continue
        if in_tools and line.startswith("- "):
            calls.append(line[2:].strip())
    return calls


def _final_uncited(text: str) -> bool:
    prose = text.rsplit("## Assistant", 1)[-1].split("## Tools", 1)[0]
    lowered = prose.casefold()
    claims = any(word in lowered for word in ("passed", "tests run", "failures: 0"))
    cites = ("`" in prose) or ("mvn" in lowered) or ("surefire" in lowered)
    return bool(claims and not cites)


def scan_transcripts(root: Path) -> dict:
    """Count real identical-call streaks. Truncated heredoc headers are not loops."""
    transcripts = sorted(Path(root).glob("*/*/transcript.md"))
    runs = len(transcripts)
    calls = 0
    stub_adjacent = 0
    real_adjacent = 0
    runs_with_real_loop = 0
    uncited = 0
    for path in transcripts:
        text = path.read_text(encoding="utf-8", errors="replace")
        rows = _tool_lines(text)
        calls += len(rows)
        streak = 1
        run_loop = False
        for left, right in zip(rows, rows[1:]):
            if left != right:
                streak = 1
                continue
            if left.startswith(HEREDOC_STUB):
                stub_adjacent += 1
                streak = 1
                continue
            real_adjacent += 1
            streak += 1
            if streak >= 3:
                run_loop = True
        if run_loop:
            runs_with_real_loop += 1
        if _final_uncited(text):
            uncited += 1
    return {
        "runs": runs,
        "calls": calls,
        "stubAdjacent": stub_adjacent,
        "realAdjacent": real_adjacent,
        "runsWithRealLoop": runs_with_real_loop,
        "uncitedFinals": uncited,
    }


def loop_cap_recommended(stats: dict) -> bool:
    """True only when identical-call loops or uncited answers are material."""
    runs = int(stats.get("runs") or 0)
    if runs <= 0:
        return False
    loop_rate = int(stats.get("runsWithRealLoop") or 0) / runs
    uncited_rate = int(stats.get("uncitedFinals") or 0) / runs
    return loop_rate >= MATERIAL_RATE or uncited_rate >= MATERIAL_RATE


def load_fixture_dir(directory: Path) -> list[dict]:
    fixtures = []
    for path in sorted(Path(directory).glob("*.json")):
        fixtures.append(json.loads(path.read_text(encoding="utf-8")))
    return fixtures
