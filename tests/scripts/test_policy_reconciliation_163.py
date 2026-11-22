"""#163 C1–C9: policy files must not contradict each other again."""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CEILING = 18500
BASELINE = 26635


def _read(relative: str) -> str:
    return (ROOT / relative).read_text(encoding="utf-8")


def test_c1_routine_work_proceeds_and_irreversible_work_needs_approval():
    rules = _read("references/permanent-rules.md")
    assert "never for approval" not in rules
    assert "routine in-scope" in rules
    assert "plan approval" in rules
    assert "explicit owner approval" in rules
    for word in ("irreversible", "destructive", "paid-campaign", "externally visible"):
        assert word in rules
    for relative in ("references/router-contract.md", "skills/chaos-engine/SKILL.md"):
        text = _read(relative)
        assert "never for approval" not in text


def test_c2_review_floor_is_one_or_two_not_both_always():
    for relative in ("references/router-contract.md", "references/delivery-cycle.md"):
        text = _read(relative)
        assert "one fresh-context adversarial review" in text
        assert "two independent adversarial reviews" in text
        assert "hard-to-reverse" in text or "hard to reverse" in text
        assert "before orchestrator sign-off" in text or relative.endswith("delivery-cycle.md")
        assert "Run two independent adversarial reviews before orchestrator sign-off." not in text
        assert "Review is the two adversarial" not in text
        assert "always two" not in text.casefold()
        assert "always one" not in text.casefold()
    skill = _read("skills/chaos-engine/SKILL.md")
    assert "one fresh-context adversarial review" in skill
    assert "hard-to-reverse" in skill
    assert "Do not start both reviewers in one step" in skill
    assert "review 1 with the self-accept push" in skill


def test_c3_one_file_fast_path_has_no_multi_page_spec():
    skill = _read("skills/chaos-engine/SKILL.md")
    assert "One file and reversible: one line" in skill
    assert "No plan document" in skill
    assert "tool.py retrieve" in skill
    cycle = _read("references/delivery-cycle.md")
    assert "one-file reversible" in cycle
    assert "read/fix/prove" in cycle
    assert "No multi-page spec" in cycle
    card = _read("references/delegate-card.md")
    assert "One-file reversible" in card
    assert "No multi-page spec" in card
    assert "retrieve-first" in card


def test_c4_vertical_slice_allows_a_named_group_waiver():
    for relative in (
        "references/bot-entry.md",
        "references/permanent-rules.md",
        "skills/kanban/SKILL.md",
    ):
        text = _read(relative)
        assert "~90" in text
        assert "size_waiver" in text
        assert "vertical slice" in text
        assert "batch waiver" in text or "epic or batch waiver" in text
        folded = text.casefold()
        assert "never batch" not in folded
        assert "always one pr per ticket" not in folded
        assert "never one-pr-per-ticket" not in folded


def test_c5_failure_caps_and_pr_babysit_coexist():
    identity = _read("identity.md")
    assert "two failed attempts on one approach" in identity
    cycle = _read("references/delivery-cycle.md")
    assert "at most 3" in cycle
    assert "Two failed attempts on one approach" in cycle
    for relative in ("skills/chaos-engine/SKILL.md", "references/bot-entry.md"):
        text = _read(relative)
        assert "Two failed attempts on one approach" in text or "two failed attempts on one approach" in text
        assert "3 local PDCA" in text or "at most 3" in text
        assert "blocking: unverifiable" in text
        assert "no retry cap" not in text


def test_c6_never_arm_auto_merge():
    for relative in (
        "references/router-contract.md",
        "references/delivery-cycle.md",
        "references/bot-entry.md",
        "references/permanent-rules.md",
    ):
        text = _read(relative)
        assert "Never arm `gh pr merge --auto`" in text
        assert "gh pr merge --squash" in text
        assert "gh pr merge --merge" not in text
        assert "Arm `gh pr merge --auto`" not in text
    cycle = _read("references/delivery-cycle.md")
    assert "required checks" in cycle
    assert "review thread" in cycle


def test_c7_caveman_fragments_are_bot_to_bot_only():
    text = _read("companions/caveman-ultra.md")
    assert "short plain full sentences" in text
    assert "not telegraphic" in text
    fragment_lines = [line for line in text.splitlines() if "Fragments fine" in line]
    assert fragment_lines
    for line in fragment_lines:
        assert "bot-to-bot" in line
        assert "not for humans" in line


def test_c8_python_floor_and_managed_pin_are_both_stated():
    for relative in ("AGENTS.md", "references/bot-entry.md"):
        text = _read(relative)
        assert "3.11" in text
        assert "3.14.0" in text
    contributing = _read("CONTRIBUTING.md")
    assert "3.11" in contributing
    assert "3.14.0" in contributing


def test_c9_overlay_sync_compares_core_commit():
    for relative in ("AGENTS.md", "references/delegate-card.md"):
        text = _read(relative)
        assert ".chaos-engine/" in text
        assert "coreCommit" in text
        assert "tool.py maintain" in text
    card = _read("references/delegate-card.md")
    assert "prefer the source tree when both exist" not in card
    assert "chaos-engine/references/" not in card


def test_always_loaded_budget_matches_the_measured_sum_and_ceiling(tmp_path: Path):
    # A populated store registry says "ready" and is 32 bytes shorter than a
    # clean runner. Isolate the measurement so CI and a workstation match.
    isolated = os.environ.copy()
    isolated["CHAOS_ENGINE_MEMPALACE"] = str(tmp_path / "no-palace")
    isolated["CHAOS_ENGINE_GRAPHIFY_OUT"] = str(tmp_path / "no-graph")
    isolated["CHAOS_ENGINE_STORE_REGISTRY"] = str(tmp_path / "no-registry")
    entry = subprocess.check_output(
        ["python3", "tool.py", "entry", "--full"],
        cwd=ROOT,
        env=isolated,
    )
    bot = (ROOT / "references/bot-entry.md").read_bytes()
    agents = (ROOT / "AGENTS.md").read_bytes()
    measured = len(entry) + len(bot) + len(agents)
    budget = json.loads((ROOT / "always-loaded-budget.json").read_text(encoding="utf-8"))
    assert measured <= CEILING
    assert measured <= int(BASELINE * 0.7)
    assert budget["bytes"] == measured
    assert "26635" in (ROOT / "always-loaded-budget.json").read_text(encoding="utf-8")
