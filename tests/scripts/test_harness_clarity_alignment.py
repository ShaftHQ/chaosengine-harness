"""Clarity alignment for dedup, merge policy, hook honesty, and the 8 hook hosts."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def _read(relative: str) -> str:
    return (ROOT / relative).read_text(encoding="utf-8")


def _rows(text: str) -> list[list[str]]:
    rows = []
    for line in text.splitlines():
        if not line.startswith("|"):
            continue
        rows.append([cell.strip() for cell in line.strip().strip("|").split("|")])
    return rows


def test_f10_duplicate_in_tree_copy_bullet_stays_only_in_identity():
    bullet = "An in-tree copy is not a resolved upstream adapter."
    assert bullet in _read("identity.md")
    for relative in ("companions/caveman-ultra.md", "companions/ponytail-ultra.md"):
        assert bullet not in _read(relative)


def test_f3_retrieve_record_names_used_or_skipped_and_keeps_the_reason_token():
    skill = _read("skills/chaos-engine/SKILL.md")
    assert "record `retrieve: used|skipped(<reason>)`" in skill
    assert "skipped(<reason>)" in skill


def test_f4_pdca_cap_is_three_not_a_quota():
    skill = _read("skills/chaos-engine/SKILL.md")
    assert "PDCA cap is 3, not a quota. Review 1 starts with the self-accept push" in skill
    assert "delivery-cycle.md" in skill
    assert "At most 3 local PDCA loops, then review 1 with the self-accept push" not in skill
    assert "review 1 with the self-accept push" in skill


def test_f5_ethics_check_is_on_the_person_only_and_tier2_paths():
    ethics = _read("companions/ethics-card.md")
    person = next(line for line in ethics.splitlines() if line.startswith("- Person-only"))
    assert "tool.py ethics-check" in person
    assert len(ethics.encode("utf-8")) < 1024
    gates = _read("references/bot-entry.md").split("## Mechanical gates", 1)[1].split("##", 1)[0]
    assert "tool.py ethics-check" in gates
    for relative in ("references/host-parity-matrix.md", "references/lifecycle-hooks.md"):
        tier2 = next(line for line in _read(relative).splitlines() if line.startswith("| Tier 2"))
        assert "tool.py ethics-check" in tier2


def test_f1_stop_is_observe_only_or_continue_outside_enforce_hosts():
    for relative in ("references/hook-trigger-map.md", "references/lifecycle-hooks.md"):
        text = _read(relative)
        assert "observe-only" in text
        assert "decision=continue" in text
        assert "exit 0" in text
        assert "tool.py pre-done --gate" in text
        assert "tool.py dod <PR>" in text
    for cells in _rows(_read("references/hook-trigger-map.md")):
        if not cells or cells[0] != "`Stop`":
            continue
        hosts = cells[1].casefold()
        mode = cells[2].casefold()
        if "opencode" in hosts:
            assert "enforce" not in mode
            assert "observe-only" in mode
        if "antigravity" in hosts:
            assert "enforce" not in mode
            assert "decision=continue" in mode
            assert "exit 0" in mode


def test_f7_nine_host_gap_exit2_and_cursor_posttooluse_fail_open():
    matrix = _read("references/host-parity-matrix.md")
    implementation = matrix.split("## One implementation", 1)[1].split("##", 1)[0]
    assert "Antigravity" in implementation
    gap = next(line for line in matrix.splitlines() if line.startswith("| GAP-EXIT2 |"))
    for host in ("Cursor", "OpenCode"):
        assert host in gap
    assert "decision=deny" in gap
    assert "decision=continue" in gap
    assert "exit 0" in gap
    cursor = next(line for line in matrix.splitlines() if line.startswith("| GAP-CURSOR-HOOKS |"))
    assert "PostToolUse" in cursor
    assert "fail-open" in cursor.casefold()
    assert "permission" in cursor
    assert "all five hosts" not in matrix
    for relative in (
        "guides/tools/cursor.md",
        "guides/tools/opencode.md",
        "guides/tools/antigravity.md",
    ):
        text = _read(relative)
        for command in (
            "tool.py delete-check",
            "tool.py pre-done --gate",
            "tool.py dod",
            "tool.py ethics-check",
        ):
            assert command in text, relative
    bot = _read("guides/tools/grok-bot.md")
    for token in (
        "entry --full",
        "retrieve",
        "delete-check",
        "ethics-check",
        "pre-done",
        "dod",
        "checkpoint",
        "resume",
        "maintain",
        "GAP-BOT-ENTRY",
    ):
        assert token in bot


def test_f8_implementation_batch_is_not_interrupted_for_consolidated_check():
    block = _read("references/router-contract.md").split(
        "4. Implement the full approved scope", 1
    )[1].split("\n5. ", 1)[0]
    assert "test," not in block
    assert "consolidated Check" in block
    for word in ("review", "commit", "push"):
        assert word in block


def test_f9_status_table_points_at_kanban_and_the_broken_self_link_is_gone():
    rules = _read("references/permanent-rules.md")
    status = next(line for line in rules.splitlines() if line.startswith("| Status reports are tables"))
    assert "skills/kanban/SKILL.md" in status
    assert "chaos-engine/SKILL.md" not in status
    assert "404s every other coordinate" not in rules


def test_f11_job_applications_discovers_channel_selection_only():
    text = _read("skills/job-applications/SKILL.md")
    assert "applying to jobs for the user" not in text.casefold()
    description = next(line for line in text.splitlines() if line.startswith("description:"))
    folded = description.casefold()
    assert "channel" in folded
    assert "email" in folded and "linkedin" in folded and "ats" in folded
    assert "job-apply" in folded


def test_f12_user_prompt_submit_includes_cursor_and_antigravity():
    row = next(
        line
        for line in _read("references/hook-trigger-map.md").splitlines()
        if line.startswith("| `UserPromptSubmit` |")
    )
    assert "Cursor" in row
    assert "Antigravity" in row
    assert "PreInvocation" in row
    assert "terminat" in row.casefold()


def test_hook_hosts_match_the_production_hook_registry():
    sys.path.insert(0, str(ROOT))
    from runtime import conformance, harness_index

    assert set(harness_index.HOOK_HOSTS) == set(conformance.production_hook_registry())
    assert set(harness_index.HOOK_HOSTS) == {
        "claude",
        "codex",
        "copilot",
        "gemini",
        "grok",
        "opencode",
        "cursor",
        "antigravity",
    }
