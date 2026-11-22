"""Waste digests, WIP caps, and the repeated-defect ratchet (#79)."""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "runtime"))

import handoff_receipt  # noqa: E402
import session_token_usage  # noqa: E402
import task_ledger  # noqa: E402

WAIVER = "owner-2026-11-22-all-open-issues-one-pr"


def test_usage_rows_carry_waste_digests_not_transcripts(tmp_path: Path):
    ledger = {
        "schemaVersion": 1,
        "totals": {"localPromptTokens": 10, "localCompletionTokens": 2, "cloudPromptTokens": 0, "cloudCompletionTokens": 0},
        "waste": {"tokenWaste": 3, "contextWaste": 4, "reworkWaste": 1, "source": "digest"},
        "wip": {"items": 1, "branches": 1, "openPrs": 0},
        "prSize": 12,
        "cycleTimeSeconds": 30,
        "prompt": "do not store this transcript",
    }
    (tmp_path / "alpha.json").write_text(json.dumps(ledger), encoding="utf-8")
    rows = session_token_usage.usage_rows(tmp_path)
    assert rows[0]["tokenWaste"] == 3
    assert rows[0]["contextWaste"] == 4
    assert rows[0]["reworkWaste"] == 1
    assert rows[0]["wip"]["openPrs"] == 0
    assert rows[0]["prSize"] == 12
    blob = json.dumps(rows)
    assert "do not store this transcript" not in blob
    card = session_token_usage.fixture_scorecard()
    assert card["source"] == "fixture"
    assert card["label"].startswith("fixture")
    assert card["tokenWaste"] == 120


def test_handoff_receipt_stores_digests_only():
    receipt = handoff_receipt.build(
        task="gate",
        head_sha="abc",
        waste={"tokenWaste": 5, "contextWaste": 0, "reworkWaste": 1, "source": "digest", "prompt": "secret transcript"},
        wip={"items": 1, "branches": 1, "openPrs": 2},
        pr_size=40,
        cycle_time_seconds=15,
    )
    assert receipt["waste"]["tokenWaste"] == 5
    assert receipt["waste"]["source"] == "digest"
    assert "prompt" not in receipt["waste"]
    assert receipt["prSize"] == 40
    assert "secret transcript" not in json.dumps(receipt)
    empty = handoff_receipt.build(task="gate", head_sha="abc")
    assert empty["waste"]["tokenWaste"] == "unmeasured"
    assert empty["cycleTimeSeconds"] == "unmeasured"


def test_wip_caps_fail_closed_and_no_string_lifts_them():
    over = task_ledger.wip_gate(doing=2, branches=2, open_prs=2)
    assert over["ok"] is False
    assert "wip-doing-cap" in over["reasons"]
    assert "wip-branch-cap" in over["reasons"]
    assert "wip-open-pr-cap" in over["reasons"]
    waived = task_ledger.wip_gate(doing=2, branches=2, open_prs=4, waiver=WAIVER)
    assert waived["ok"] is False
    assert waived["waiverAccepted"] is False
    other = task_ledger.wip_gate(doing=2, branches=1, open_prs=1, waiver="not-the-waiver")
    assert other["ok"] is False


def test_ledger_view_reports_wip_and_blocks_a_repeated_defect():
    ledger = {
        "items": [
            {"id": "a", "status": "in-progress", "branch": "ChaosEngine/one", "pr": "9", "defect_type": "visual-inventory"},
            {"id": "b", "status": "done", "defect_type": "visual-inventory"},
            {"id": "c", "status": "pr", "branch": "ChaosEngine/two", "pr": "10"},
        ]
    }
    view = task_ledger.wip_from_ledger(ledger)
    assert view["items"] == 1
    assert view["branches"] == 2
    assert view["openPrs"] == 2
    assert view["ok"] is False
    ratchet = task_ledger.defect_ratchet(ledger)
    assert ratchet["ok"] is False
    assert "visual-inventory" in ratchet["blocked"]
    ledger["preventive_checks"] = {"visual-inventory": "spec-template-headings"}
    assert task_ledger.defect_ratchet(ledger)["ok"] is True
    text = (ROOT / "references" / "lean-agile.md").read_text(encoding="utf-8")
    card = (ROOT / "references" / "bot-entry.md").read_text(encoding="utf-8")
    assert WAIVER not in text
    assert WAIVER not in card
    assert "fixture" in text
    assert "n≥5" in text or "n>=5" in text
    assert "Agile Manifesto" in text or "agilemanifesto.org" in text
