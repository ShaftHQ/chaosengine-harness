"""Every rules/*.py module is on the pre-done or done path, or retired (#163)."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "runtime"))

import dod  # noqa: E402
import owner_gate  # noqa: E402
import pre_done_review  # noqa: E402

BRIDGE = ROOT / "rules" / "pre_done_bridge.py"

# Known-bad inputs for the shipped function. Needles are hit substrings, not copies of the rule.
CASES = (
    ("avatar_likeness_gate", {}, "glasses-missing"),
    ("cms_block_identity", {}, "missing-current-block-text"),
    ("design_fix_loop", {"full_regen_failures": 2}, "need-localized-masked-edit-after-cap-2"),
    ("ethics_check", None, "blocks-submit"),
    ("gate_proven_red", {}, "gate-not-red"),
    ("large_read_deny", None, "Read denied"),
    ("lessons_2026_11_01", {}, "missing-resumable-batches"),
    ("lessons_2026_11_02", {"owner_status_requested": True}, "missing-fresh-poll"),
    ("lessons_2026_11_06", {"multi_agent_order": True}, "missing-shared-instruction-file"),
    ("lessons_l82_l92", "", "redaction"),
    ("lessons_repeat_failure_pdca", {"chained_fix_after_fail": True}, "chained-fix-after-fail"),
    ("mega_pr", "ship one PR per ticket", "one-pr-per-ticket"),
    ("memory_full_dump", "x" * 90, "truncated-memory"),
    ("no_probe_live", {"action": "write", "path": "/etc/hostname", "live_roots": ["/etc"]}, "probe-write-on-live-path"),
    ("operation_boundary", "password=hunter2", "password-in-output"),
    ("orchestrator_pre_publish", {"surface": "web", "live_publish": True}, "missing-orchestrator-gate-pass"),
    ("preview_at_real_width", {}, "missing-orchestrator-pass"),
    ("public_facts", {"trainee_count": "484", "assert_founded_year": False}, "superseded-trainee-count-484"),
    ("remote_credential_guard", "https://user:secret@example.com/repo", "userinfo-password"),
    ("verify_dropped", "redo the task", "missing-live-state-receipt"),
    ("web_ui_gate", {}, "bidi-not-ok"),
)


def _bridge():
    spec = importlib.util.spec_from_file_location("ce_pre_done_bridge_163", BRIDGE)
    if spec is None or spec.loader is None:
        raise RuntimeError(BRIDGE)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_every_rule_module_is_wired_or_retired(tmp_path: Path):
    names = sorted(
        path.stem
        for path in (ROOT / "rules").glob("*.py")
        if path.stem != "pre_done_bridge"
    )
    bridge = _bridge()
    assert set(names) == set(bridge.WIRED) | set(bridge.RETIRED)
    assert not (set(bridge.WIRED) & set(bridge.RETIRED))
    for name, reason in bridge.RETIRED.items():
        assert str(reason).strip()
    pre = (ROOT / "runtime" / "pre_done_review.py").read_text(encoding="utf-8")
    done = (ROOT / "runtime" / "dod.py").read_text(encoding="utf-8")
    assert "apply_wired_rules" in pre
    assert "apply_wired_rules" in done
    dump = tmp_path / "dump.log"
    dump.write_bytes(b"x" * 8192)
    cases = []
    for name, payload, needle in CASES:
        if name == "large_read_deny":
            payload = {"tool_name": "read", "tool_input": {"file_path": str(dump)}}
        cases.append((name, payload, needle))
    assert {name for name, _payload, _needle in cases} == set(bridge.WIRED)
    for name, payload, needle in cases:
        result = bridge.invoke(name, payload)
        assert result["ok"] is False, name
        assert any(needle in str(hit) for hit in result["hits"]), (name, result)
    direct = bridge.load_module("mega_pr").evaluate("ship one PR per ticket")
    via = bridge.invoke("mega_pr", "ship one PR per ticket")
    assert direct["hits"] == via["hits"]
    ethics = bridge.load_module("ethics_check")
    assert ethics.blocks_submit(None) is True


def test_pre_done_and_dod_call_the_shipped_rule():
    plan = "ship one PR per ticket"
    reasons = pre_done_review.mechanical_problems(
        {"proofs": [{"id": "pytest", "ran": True}], "rules": {"mega_pr": plan}}
    )
    assert any("one-pr-per-ticket" in item for item in reasons)
    rows = dod.evaluate(
        {
            "pr": {"labels": [{"name": "bug"}], "body": "Fixes #1\n", "files": []},
            "checks": [],
            "human": True,
            "rules": {"mega_pr": plan},
        }
    )
    assert any(status == "gap" and "one-pr-per-ticket" in detail for _name, status, detail in rows)


def test_record_unverifiable_gate_once_without_sign_off(tmp_path: Path):
    path = tmp_path / "owner-gate.json"
    reason = "voice recording is not available in this session"
    first = owner_gate.record_unverifiable_gate(path, issue_id="71", reason=reason)
    assert first["blocking"] == "blocking: unverifiable"
    assert first["record"] is True
    assert first["sign_off"] is False
    assert first["ask"] == ""
    assert first["poll"] is False
    second = owner_gate.record_unverifiable_gate(path, issue_id="71", reason=reason)
    assert second["record"] is False
    assert second["blocking"] == "blocking: unverifiable"
    body = path.read_text(encoding="utf-8")
    assert "blocking: unverifiable" in body
    assert '"issue": "71"' in body
    assert "sign_off" in body
    assert "approved" not in body.casefold()
    assert "PNG" not in body


def test_ab_report_host_is_scrubbed():
    text = (ROOT / "experiments" / "harness-ab" / "REPORT.md").read_text(encoding="utf-8")
    assert "TheMohie" not in text
    assert "mohab@" not in text.casefold()
    assert "<user>@<host>" in text
