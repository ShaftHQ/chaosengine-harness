"""Plan CLI, approval gate, and pre-done evidence."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "runtime"))

import plan_cli  # noqa: E402
import plan_gate  # noqa: E402
import plan_model  # noqa: E402
import plan_render  # noqa: E402
import pre_done_review  # noqa: E402
import tool  # noqa: E402


def _write(path: Path, text: str) -> None:
    path.write_text(text, encoding="utf-8")


def test_tool_registers_plan_and_state():
    assert tool.SCRIPT_TOOLS["plan"] == "plan_cli.py"
    assert tool.SCRIPT_TOOLS["state"] == "state_bundle.py"
    help_text = tool.tool_help_text()
    for line in (
        "tool.py plan new",
        "tool.py plan show",
        "tool.py plan approve",
        "tool.py plan step",
        "tool.py plan walkthrough",
    ):
        assert line in help_text


def test_no_network_and_no_sticky_comment():
    for name in ("plan_model.py", "plan_render.py", "plan_cli.py", "plan_gate.py"):
        text = (ROOT / "runtime" / name).read_text(encoding="utf-8")
        assert "urllib" not in text
        assert "requests" not in text
        assert "gh api" not in text
        assert "<!-- ce-plan:" not in text
        assert "Mohab" not in text


def test_host_probe_is_skipped():
    probe = json.loads((ROOT / "tests" / "fixtures" / "plan" / "host-ui-probe.json").read_text(encoding="utf-8"))
    assert probe["captured"] is False
    assert probe["hosts"]
    assert {row["status"] for row in probe["hosts"]} == {"skipped"}


def test_checklist_import_and_exit_codes(tmp_path, monkeypatch):
    monkeypatch.setenv("CHAOS_ENGINE_TASKS_DIR", str(tmp_path))
    markdown = tmp_path / "in.md"
    _write(markdown, "Fix login\n\n- [ ] Reproduce\n- [x] Patch\n")
    assert plan_cli.main([]) == 2
    assert plan_cli.main(["new", "login", "--from-md", str(markdown)]) == 0
    assert plan_cli.main(["new", "login", "--from-md", str(markdown)]) == 1
    plan = plan_model.load("login")
    assert plan is not None
    assert plan["explanation"] == "Fix login"
    assert [step["status"] for step in plan["steps"]] == ["pending", "done"]
    assert plan_cli.main(["gate", "login"]) == 0
    assert plan_cli.main(["show", "missing"]) == 6
    assert plan_cli.main(["gate", "missing"]) == 6
    before = plan_model.plan_path("login").read_bytes()
    assert plan_cli.main(["step", "login", "missing", "--status", "done"]) == 1
    assert plan_cli.main(["edit", "login", "--remove", "missing"]) == 1
    assert plan_model.plan_path("login").read_bytes() == before


def test_revision_approval_and_comments(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("CHAOS_ENGINE_TASKS_DIR", str(tmp_path))
    markdown = tmp_path / "in.md"
    _write(markdown, "- [ ] One\n- [ ] Two\n- [ ] Three\n")
    assert plan_cli.main(["new", "fix", "--from-md", str(markdown), "--goal", "Ship"]) == 0
    assert plan_cli.main(["gate", "fix"]) == 4
    monkeypatch.delenv("CHAOS_ENGINE_ENFORCE_PLAN_APPROVAL", raising=False)
    assert plan_gate.plan_approval_block("fix") is None
    assert plan_cli.main(["approve", "fix", "--ref", "chat", "--comment", "s2:use the same 404 body"]) == 0
    plan = plan_model.load("fix")
    assert plan["approval"]["state"] == "approved"
    assert plan["approval"]["comments"] == [{"step": "s2", "text": "use the same 404 body"}]
    assert "comment s2: use the same 404 body" in plan_render.resume_block(plan)
    revision = plan["revision"]
    assert plan_cli.main(["step", "fix", "s1", "--status", "in_progress"]) == 0
    assert plan_model.load("fix")["revision"] == revision
    assert plan_cli.main(["gate", "fix"]) == 0
    assert plan_cli.main(["edit", "fix", "--add", "Extra"]) == 0
    updated = plan_model.load("fix")
    assert updated["revision"] == revision + 1
    assert updated["approval"]["state"] == "awaiting"
    assert plan_cli.main(["gate", "fix"]) == 4
    assert plan_cli.main(["stop", "fix"]) == 0
    assert plan_cli.main(["gate", "fix"]) == 5
    capsys.readouterr()


def test_owner_code_and_approval_block(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("CHAOS_ENGINE_TASKS_DIR", str(tmp_path))
    monkeypatch.setenv("CHAOS_ENGINE_ENFORCE_PLAN_APPROVAL", "1")
    markdown = tmp_path / "in.md"
    _write(markdown, "- [ ] One\n- [ ] Two\n- [ ] Three\n")
    assert plan_cli.main(["new", "fix", "--from-md", str(markdown)]) == 0
    denial = plan_gate.plan_approval_block("fix")
    assert denial is not None
    assert "plan approve" in denial
    assert plan_cli.main(["approve", "fix"]) == 1
    assert plan_cli.main(["approve", "fix", "--code", "NOPE"]) == 1
    assert plan_model.load("fix")["approval"]["state"] == "awaiting"
    assert plan_cli.main(["approve", "fix", "--request-code"]) == 0
    code = capsys.readouterr().out.split()[1]
    assert plan_cli.main(["approve", "fix", "--code", code]) == 0
    assert plan_gate.plan_approval_block("fix") is None
    assert plan_cli.main(["approve", "fix", "--code", code]) == 1
    expired = plan_gate.request_approval_code("fix", int(plan_model.load("fix")["revision"]), now=1_000, ttl=10)
    status, message = plan_gate.approve("fix", code=expired, now=5_000, environ=os.environ)
    assert status == 1
    assert "expired" in message


def test_done_without_evidence_fails_pre_done(tmp_path, monkeypatch):
    monkeypatch.setenv("CHAOS_ENGINE_TASKS_DIR", str(tmp_path))
    source = tmp_path / "plan.json"
    source.write_text(
        json.dumps(
            {
                "steps": [
                    {
                        "id": "s1",
                        "title": "Check",
                        "status": "pending",
                        "verify": [{"kind": "test", "spec": "pytest"}],
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    assert plan_cli.main(["new", "bare", "--from", str(source)]) == 0
    assert plan_cli.main(["step", "bare", "s1", "--status", "done"]) == 1
    assert plan_model.load("bare")["steps"][0]["status"] == "pending"
    forced = plan_model.load("bare")
    forced["steps"][0]["status"] = "done"
    forced["steps"][0]["note"] = ""
    forced["steps"][0]["evidence"] = []
    plan_model.save(forced)
    found = pre_done_review.mechanical_problems({"proof_required": False, "task": "bare"})
    assert any("done with verify and no evidence" in item for item in found)
    assert plan_cli.main(["step", "bare", "s1", "--status", "done", "--note", "no-evidence: fixture"]) == 0
    cleared = pre_done_review.mechanical_problems({"proof_required": False, "task": "bare"})
    assert not any("no evidence" in item for item in cleared)
    assert pre_done_review.mechanical_problems({"proof_required": False}) == []


def test_second_run_same_done_total_and_evidence(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("CHAOS_ENGINE_TASKS_DIR", str(tmp_path / "tasks"))
    monkeypatch.chdir(tmp_path)
    log = tmp_path / "log.txt"
    _write(log, "ok\nexit: 0\n")
    markdown = tmp_path / "in.md"
    _write(markdown, "Fix login\n\n- [ ] Reproduce\n- [ ] Patch\n- [ ] Prove\n")
    assert plan_cli.main(["new", "fix", "--from-md", str(markdown), "--goal", "Fix login"]) == 0
    assert plan_cli.main(["approve", "fix", "--ref", "chat"]) == 0
    evidence = f"test:{log}"
    assert plan_cli.main(["step", "fix", "s1", "--status", "done", "--evidence", evidence]) == 0
    first_walk = tmp_path / "walk-1.md"
    second_walk = tmp_path / "walk-2.md"
    assert plan_cli.main(["walkthrough", "fix", "--out", str(first_walk)]) == 0

    def snapshot():
        assert plan_cli.main(["show", "fix", "--format", "json"]) == 0
        plan = json.loads(capsys.readouterr().out)
        done, total = plan_model.progress(plan)
        return done, total, [step.get("evidence") for step in plan["steps"]]

    first = snapshot()
    assert plan_cli.main(["step", "fix", "s1", "--status", "done", "--evidence", evidence]) == 0
    assert plan_cli.main(["walkthrough", "fix", "--out", str(second_walk)]) == 0
    second = snapshot()
    assert first == second
    assert first[0] == 1 and first[1] == 3
    assert first_walk.read_bytes() == second_walk.read_bytes()
    assert "exit 0" in first_walk.read_text(encoding="utf-8")


def test_pr_section_and_public_contract(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("CHAOS_ENGINE_TASKS_DIR", str(tmp_path))
    markdown = tmp_path / "in.md"
    _write(markdown, "- [ ] Only\n")
    assert plan_cli.main(["new", "one", "--from-md", str(markdown), "--triage", "public-contract"]) == 0
    assert plan_cli.main(["gate", "one"]) == 4
    capsys.readouterr()
    assert plan_cli.main(["show", "one", "--format", "md", "--pr-section"]) == 0
    assert capsys.readouterr().out.startswith("## Plan\n")


def test_watch_reports_one_change(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("CHAOS_ENGINE_TASKS_DIR", str(tmp_path))
    markdown = tmp_path / "in.md"
    _write(markdown, "- [ ] One\n")
    assert plan_cli.main(["new", "job", "--from-md", str(markdown)]) == 0
    sleeps: list[float] = []

    def on_wait() -> None:
        if not sleeps:
            plan_model.on_checkpoint("job", "s1", status="done", now=3)

    code = plan_cli.watch_task(
        "job",
        is_tty=False,
        poll_s=1.0,
        sleep=lambda delay: sleeps.append(delay),
        on_wait=on_wait,
        max_loops=4,
    )
    assert code == 0
    assert sleeps and sleeps[0] <= 2
    output = capsys.readouterr().out
    assert "0/1 done" in output
    assert "s1 done 1/1 done" in output


def test_tool_py_plan_new_dispatches(tmp_path, monkeypatch):
    monkeypatch.setenv("CHAOS_ENGINE_TASKS_DIR", str(tmp_path))
    markdown = tmp_path / "in.md"
    _write(markdown, "- [ ] One\n- [x] Two\n")
    env = os.environ.copy()
    env["CHAOS_ENGINE_TASKS_DIR"] = str(tmp_path)
    completed = subprocess.run(
        [sys.executable, str(ROOT / "tool.py"), "plan", "new", "via-tool", "--from-md", str(markdown)],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr
    assert plan_model.load("via-tool")["explanation"] == ""
    assert [step["status"] for step in plan_model.load("via-tool")["steps"]] == ["pending", "done"]
    help_run = subprocess.run(
        [sys.executable, str(ROOT / "tool.py"), "plan", "--help"],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert help_run.returncode == 0
    assert "tool.py plan approve" in help_run.stdout
