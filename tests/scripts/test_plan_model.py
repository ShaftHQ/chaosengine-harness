"""ce-plan/v1 validation, ledger projection, and host fold."""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "runtime"))

import plan_model  # noqa: E402


def _approval(*, required: bool = False, state: str = "approved", revision: int = 1) -> dict:
    return {
        "required": required,
        "state": state,
        "revision": revision,
        "by": "owner" if state == "approved" else "",
        "at": "",
        "ref": "",
        "comments": [],
    }


def _plan(steps: list[dict], **extra) -> dict:
    body = {
        "schema": plan_model.SCHEMA,
        "task": "sample",
        "goal": "",
        "explanation": "",
        "revision": 1,
        "approval": _approval(),
        "steps": steps,
        "walkthrough": None,
    }
    body.update(extra)
    return body


def test_schema_enums_match_the_model():
    schema = json.loads((ROOT / "schemas" / "ce-plan.v1.json").read_text(encoding="utf-8"))
    assert schema["$defs"]["step"]["properties"]["status"]["enum"] == list(plan_model.STATUSES)
    assert schema["$defs"]["evidence"]["properties"]["kind"]["enum"] == list(plan_model.EVIDENCE_KINDS)
    assert schema["properties"]["steps"]["maxItems"] == 100


def test_each_defect_has_one_message():
    steps = [
        {"id": "s1", "title": "   ", "status": "nope"},
        {"id": "s1", "title": "Ok", "status": "pending"},
    ]
    errors = plan_model.validate(_plan(steps))
    assert errors.count("empty title: s1") == 1
    assert errors.count("unknown status: nope") == 1
    assert errors.count("duplicate step id: s1") == 1


def test_too_many_steps():
    steps = [plan_model.blank_step(f"s{index}", f"Step {index}") for index in range(1, 102)]
    errors = plan_model.validate(_plan(steps))
    assert errors == ["too many steps: 101 > 100"]


def test_depends_on_must_exist_and_be_acyclic():
    chain = [
        plan_model.blank_step("s1", "One"),
        plan_model.blank_step("s2", "Two"),
    ]
    chain[1]["dependsOn"] = ["s1"]
    assert plan_model.validate(_plan(chain)) == []
    broken = [
        {"id": "s1", "title": "One", "status": "pending", "dependsOn": ["s2"]},
        {"id": "s2", "title": "Two", "status": "pending", "dependsOn": ["s1", "s9"]},
    ]
    errors = plan_model.validate(_plan(broken))
    assert errors.count("dependsOn missing: s9") == 1
    assert sum(item.startswith("dependsOn cycle:") for item in errors) == 1


def test_text_is_collapsed_and_capped():
    step = plan_model.blank_step("s1", "a   b")
    step["title"] = "a   \n  b"
    plan = plan_model.normalize(_plan([step]))
    assert plan["steps"][0]["title"] == "a b"
    long = plan_model.blank_step("s1", "x" * 600)
    plan = plan_model.normalize(_plan([long]))
    assert len(plan["steps"][0]["title"]) == 500


def test_markdown_checklist_round_trip():
    explanation, steps = plan_model.parse_markdown("Fix login\n\n- [ ] Reproduce\n- [x] Patch\n")
    plan = plan_model.fresh_plan("login", steps, explanation=explanation, now=0)
    assert explanation == "Fix login"
    assert [step["status"] for step in plan["steps"]] == ["pending", "done"]
    again = plan_model.normalize(json.loads(json.dumps(plan)))
    assert again["steps"][1]["status"] == "done"


def test_ledger_restores_cached_status(tmp_path, monkeypatch):
    monkeypatch.setenv("CHAOS_ENGINE_TASKS_DIR", str(tmp_path))
    plan = plan_model.fresh_plan("sample", [plan_model.blank_step("s1", "One")], now=0)
    plan_model.save(plan)
    plan_model.set_status(plan, "s1", "done", now=10)
    plan_model.save(plan)
    path = plan_model.plan_path("sample")
    raw = json.loads(path.read_text(encoding="utf-8"))
    raw["steps"][0]["status"] = "pending"
    path.write_text(json.dumps(raw), encoding="utf-8")
    assert plan_model.load("sample")["steps"][0]["status"] == "done"


def test_host_status_map():
    assert plan_model.host_status("in_progress", "openbot") == "inProgress"
    assert plan_model.host_status("blocked", "codex") == "pending"
    assert plan_model.host_status("skipped", "codex") == "completed"
    assert plan_model.host_status("in_progress", "acp") == "in_progress"
    assert plan_model.host_status("done", "claude") == "completed"


def test_fold_todowrite_and_unknown(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("CHAOS_ENGINE_TASKS_DIR", str(tmp_path))
    plan_model.save(plan_model.fresh_plan("sample", [plan_model.blank_step("s1", "Old")], now=0))
    payload = {
        "todos": [
            {"content": "Reproduce", "status": "completed"},
            {"content": "Patch", "status": "in_progress", "activeForm": "Patching"},
        ]
    }
    folded = plan_model.fold_tool_call("TodoWrite", payload, [])
    assert folded is not None
    assert [step["status"] for step in folded] == ["done", "in_progress"]
    assert folded[1]["activeText"] == "Patching"
    assert plan_model.fold_tool_call("MysteryTool", {"todos": []}, []) is None
    assert plan_model.apply_fold("sample", "MysteryTool", {"x": 1}) is False
    assert "unknown tool payload" in capsys.readouterr().err
    assert plan_model.apply_fold("sample", "TodoWrite", payload) is True
    loaded = plan_model.load("sample")
    assert [step["title"] for step in loaded["steps"]] == ["Reproduce", "Patch"]


def test_on_checkpoint_matches_step_id_only(tmp_path, monkeypatch):
    monkeypatch.setenv("CHAOS_ENGINE_TASKS_DIR", str(tmp_path))
    plan = plan_model.fresh_plan(
        "sample",
        [plan_model.blank_step("s1", "One"), plan_model.blank_step("s3", "Three")],
        now=0,
    )
    plan_model.save(plan)
    assert plan_model.on_checkpoint("sample", "s3", now=5) is True
    assert plan_model.on_checkpoint("sample", "other") is False
    loaded = plan_model.load("sample")
    assert loaded["steps"][1]["status"] == "in_progress"
    assert loaded["steps"][0]["status"] == "pending"
