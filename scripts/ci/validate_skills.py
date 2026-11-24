#!/usr/bin/env python3
"""Skill roots the harness lints. Layout is the repository root, not chaos-engine/."""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SKILLS_ROOTS = ("skills", "vendor/*/skills")


def skill_dirs(root: Path = ROOT) -> list[Path]:
    """Every skill directory under the configured roots (globs allowed)."""
    found: list[Path] = []
    for pattern in SKILLS_ROOTS:
        for skills_root in sorted(root.glob(pattern)):
            if skills_root.is_dir():
                found.extend(sorted(path for path in skills_root.iterdir() if path.is_dir()))
    return found


def _skill_listing_chars():
    """The shipped counter. Insert the repo root so a direct script run can import it."""
    repo = str(ROOT)
    if repo not in sys.path:
        sys.path.insert(0, repo)
    from scripts.ci.validate_agent_guidance import skill_listing_chars

    return skill_listing_chars


def check_listing_budget(root: Path = ROOT) -> list[str]:
    """Return listing-budget findings. Empty means every configured host is within the cap.

    Counts frontmatter ``name`` and ``description`` with the agent-guidance counter
    over ``host_skill_metadata_globs``. Vendor trees stay out of those globs.
    """
    budget_path = root / "scripts/ci/agent_guidance_budget.json"
    if not budget_path.is_file():
        return ["missing skill listing budget: scripts/ci/agent_guidance_budget.json"]
    budget = json.loads(budget_path.read_text(encoding="utf-8"))
    ceiling = budget.get("max_skill_listing_chars")
    hosts = budget.get("host_skill_metadata_globs")
    if not isinstance(ceiling, int) or not isinstance(hosts, dict) or not hosts:
        return [
            "skill listing budget is not configured: "
            "max_skill_listing_chars and host_skill_metadata_globs"
        ]
    count_chars = _skill_listing_chars()
    findings: list[str] = []
    for host, patterns in hosts.items():
        if not isinstance(patterns, list) or not patterns:
            findings.append(f"listing budget: host={host} has no skill metadata globs")
            continue
        count = count_chars(root, patterns)
        if count > ceiling:
            findings.append(f"listing overflow: host={host} count={count} ceiling={ceiling}")
    return findings


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if args != ["--check"]:
        print("usage: python3 scripts/ci/validate_skills.py --check", file=sys.stderr)
        return 2
    findings = check_listing_budget()
    for item in findings:
        print(item, file=sys.stderr)
    return 1 if findings else 0


if __name__ == "__main__":
    raise SystemExit(main())
