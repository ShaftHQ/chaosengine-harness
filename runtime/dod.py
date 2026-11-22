#!/usr/bin/env python3
"""Machine-checked Kanban Definition of Done for one pull request (#6412)."""

from __future__ import annotations

import json
import re
import shutil
import subprocess  # nosec B404 - fixed gh argv only.
import sys

RELEASE_NOTE_LABELS = frozenset({"breaking-change", "enhancement", "bug", "skip-release-notes"})
LINKED_ISSUE = re.compile(r"\b(?:close[sd]?|fix(?:e[sd])?|resolve[sd]?)\s+#\d+", re.I)
SOURCE = re.compile(r"(^|/)src/main/|\.py$")
TEST = re.compile(r"(^|/)src/test/|(^|/)tests?/|test_[^/]*\.py$|Test\.java$")
GREEN = frozenset({"SUCCESS", "SKIPPED", "NEUTRAL", "pass", "skipping"})
AGENTIC = "chaos-engine:agentic"
DONE_GATE = re.compile(r"done-gate:\s*pass\b", re.I)


def agentic_problems(body: str, *, human: bool = False) -> list[str]:
    """An agentic PR without a done-gate pass fails. Human PRs are exempt."""
    if human or AGENTIC not in (body or ""):
        return []
    if not DONE_GATE.search(body or ""):
        return ["agentic PR missing done-gate pass"]
    return []


def apply_wired_rules(payload: object) -> list[str]:
    """Same rule bridge the pre-done gate calls."""
    import pre_done_review

    return pre_done_review.apply_wired_rules(payload)


def flow_times(item: dict) -> dict:
    """Lead, blocked, and queue seconds from the task ledger."""
    import task_ledger

    return task_ledger.flow_times(item)


def next_pull(document: object) -> dict:
    """A repeated defect class blocks the next pull until a preventive check exists."""
    import task_ledger

    gate = task_ledger.defect_ratchet(document)
    return {
        "ok": gate["ok"],
        "blocked": list(gate["blocked"]),
        "reasons": list(gate["reasons"]),
    }


def evaluate(data: dict) -> list[tuple[str, str, str]]:
    """Return (criterion, ok|gap, detail) rows from gh PR and required-check JSON."""
    pr = data["pr"]
    labels = [label["name"] for label in pr.get("labels", [])]
    notes = [name for name in labels if name in RELEASE_NOTE_LABELS]
    files = [item["path"] for item in pr.get("files", [])]
    tests = [path for path in files if TEST.search(path)]
    sources = [path for path in files if SOURCE.search(path) and path not in tests]
    red = [c["name"] for c in data.get("checks", []) if c.get("state") not in GREEN]
    gate = agentic_problems(pr.get("body") or "", human=bool(data.get("human")))
    rows = [
        ("release-note label", "ok" if len(notes) == 1 else "gap", ",".join(notes) or "none"),
        ("linked issue", "ok" if LINKED_ISSUE.search(pr.get("body") or "") else "gap", "Fixes #N in body"),
        ("tests changed", "ok" if tests or not sources else "gap", f"{len(sources)} source, {len(tests)} test"),
        ("required checks", "ok" if not red else "gap", ",".join(red) or "all green"),
        ("done-gate", "ok" if not gate else "gap", gate[0] if gate else "n/a"),
    ]
    if "rules" in data:
        findings = apply_wired_rules(data.get("rules"))
        rows.append(("wired rules", "ok" if not findings else "gap", ",".join(findings) or "none"))
    return rows


def render(rows: list[tuple[str, str, str]]) -> str:
    """Markdown table, one row per criterion."""
    lines = ["| Criterion | Status | Detail |", "|---|---|---|"]
    lines += [f"| {name} | {status} | {detail} |" for name, status, detail in rows]
    return "\n".join(lines) + "\n"


def exit_code(rows: list[tuple[str, str, str]]) -> int:
    """1 when any criterion has a gap."""
    return 1 if any(status == "gap" for _, status, _ in rows) else 0


def fetch(number: str) -> dict:
    """Read the PR and its required checks through gh."""
    gh = shutil.which("gh")
    if gh is None:
        raise ValueError("gh is required for tool.py dod")

    def run(*args: str) -> str:
        return subprocess.run([gh, *args], capture_output=True, text=True, check=False).stdout or "[]"  # nosec B603

    pr = json.loads(run("pr", "view", number, "--json", "labels,body,files"))
    checks = json.loads(run("pr", "checks", number, "--required", "--json", "name,state"))
    return {"pr": pr, "checks": checks}


def main(argv: list[str]) -> int:
    if len(argv) != 1:
        print("usage: tool.py dod <PR number>", file=sys.stderr)
        return 2
    rows = evaluate(fetch(argv[0]))
    print(render(rows), end="")
    return exit_code(rows)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
