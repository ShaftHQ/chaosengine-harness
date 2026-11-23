"""Always-loaded size, one-hop skill links, and merge-policy contradictions."""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts" / "ci"))

import harness_reachability as reach  # noqa: E402

CORE = "skills/chaos-engine/SKILL.md"
INSTALLER_SENTENCE = (
    "If the pull-request diff touches `install.py`, `bootstrap.py`, "
    "`runtime/dependencies.py`, `install.sh`, or `install.ps1`, a failed, "
    "cancelled, or pending `installer-contract` check blocks squash-merge "
    "even when another required check is green."
)


def _text(relative: str) -> str:
    return (ROOT / relative).read_text(encoding="utf-8")


def test_every_skill_is_linked_from_the_entry_point_and_the_walk_is_clean() -> None:
    core = ROOT / CORE
    index = json.loads((ROOT / "harness-index.json").read_text(encoding="utf-8"))
    by_path = {entry["path"]: entry for entry in index["entries"]}
    core_links = set()
    for raw in reach.MARKDOWN_LINK.findall(core.read_text(encoding="utf-8")):
        target = raw.strip().strip("<>").split("#", 1)[0]
        if not target or reach.URI_SCHEME.match(target):
            continue
        resolved = (core.parent / target).resolve()
        try:
            core_links.add(resolved.relative_to(ROOT.resolve()).as_posix())
        except ValueError:
            continue
    assert "references/level-1-catalog.md" in core_links
    assert "references/catalog.md" in core_links
    l1_text = _text("references/level-1-catalog.md")
    cat_text = _text("references/catalog.md")
    skills = sorted(
        path.relative_to(ROOT).as_posix()
        for path in (ROOT / "skills").glob("*/SKILL.md")
    )
    assert skills
    for path in skills:
        if path == CORE:
            continue
        entry = by_path[path]
        if entry.get("family") != "on-demand" or entry["name"] == "security-audit":
            assert path in core_links, f"core skill missing from SKILL.md: {path}"
        else:
            assert f"../{path}" in l1_text, f"on-demand skill missing from level-1-catalog.md: {path}"
            assert f"../{path}" in cat_text, f"on-demand skill missing from catalog.md: {path}"
    reached, broken = reach.link_walk(ROOT, CORE)
    assert broken == []
    assert set(skills) <= reached


def test_core_card_and_always_loaded_budget_stay_under_ceiling() -> None:
    assert len((ROOT / CORE).read_bytes()) <= 7168
    budget = json.loads((ROOT / "always-loaded-budget.json").read_text(encoding="utf-8"))
    assert budget["bytes"] < 17501


def test_merge_queue_enqueues_without_a_strategy_flag() -> None:
    text = _text("references/delivery-cycle.md")
    assert "merge_queue" in text
    assert "pass no strategy flag (`--merge`, `--squash`, or `--rebase`)" in text
    assert "gh pr merge --squash" in text
    assert "gh pr merge --merge" not in text
    assert "Never arm `gh pr merge --auto`" in text


def test_installer_contract_blocks_squash_merge_for_installer_paths() -> None:
    text = _text("references/delivery-cycle.md")
    assert INSTALLER_SENTENCE in text


def test_permanent_rules_have_no_merge_contradiction_or_stale_headroom_footnote() -> None:
    text = _text("references/permanent-rules.md")
    for line in text.splitlines():
        if "MERGE method" in line:
            assert "--squash" not in line
    assert "Headroom installs by default" not in text


def test_default_reviewer_is_not_hardcoded_to_grok() -> None:
    text = _text("references/delivery-cycle.md")
    assert "The default reviewer is the same local Grok path" not in text
    assert "grok" not in text.casefold()
    assert "any AI client" in text


def test_work_github_playbook_matches_merge_policy() -> None:
    playbook = _text("references/work-github-playbook.md")
    planning = _text("references/work-github-planning.md")
    router = _text("references/router-contract.md")
    for text in (playbook, planning):
        assert "Never arm `gh pr merge --auto`" in text
        assert "Arm `gh pr merge --auto`" not in text
        assert "merge_queue" in text
        assert "pass no strategy flag (`--merge`, `--squash`, or `--rebase`)" in text
    for forbidden in ("Before arming:", "and re-arm", "auto-merge may remain armed", "where the playbook already requires it"):
        assert forbidden not in playbook
    assert "Arm it only when the platform queues" not in planning
    for text in (planning, router):
        assert "pr-merger-workflow-arm-watch-fix-confirm" not in text
        assert "pr-merger-workflow-watch-fix-confirm" in text
