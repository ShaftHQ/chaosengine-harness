"""Crash-safe, resumable long tasks (ShaftHQ/SHAFT_ENGINE#8065). Offline fixtures."""

from __future__ import annotations

import importlib.util
import subprocess
import sys
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]


def _load():
    spec = importlib.util.spec_from_file_location("task_ledger_8065", ROOT / "task_ledger.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def ledger(tmp_path, monkeypatch):
    state = tmp_path / "state"
    monkeypatch.setenv("CHAOS_ENGINE_TASKS_DIR", str(state / "tasks"))
    monkeypatch.setenv("CHAOS_ENGINE_SPEC_DIR", str(state / "specs"))
    monkeypatch.delenv("CHAOS_ENGINE_OWNER_FINISH_GOAL", raising=False)
    monkeypatch.delenv("CHAOS_ENGINE_BOOT_TIME", raising=False)
    monkeypatch.delenv("TMPDIR", raising=False)
    (state / "specs").mkdir(parents=True)
    for name in ("t1", "t2", "t3", "old"):
        (state / "specs" / f"spec-{name}.md").write_text("spec\n", encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    return _load()


def _durable(tmp_path: Path, name: str = "work") -> Path:
    path = tmp_path / name
    path.mkdir(parents=True, exist_ok=True)
    return path


@pytest.fixture
def durable(ledger, monkeypatch):
    """pytest's tmp_path sits under /tmp; treat it as durable for fixtures that need a durable root."""
    monkeypatch.setattr(ledger, "REFUSED_VOLATILE_ROOTS", ("/nonexistent-volatile-root",))
    monkeypatch.setattr(ledger, "VOLATILE_FS_TYPES", frozenset())
    return ledger


# R1 ---------------------------------------------------------------------------

def test_tmp_workdir_is_refused(ledger, capsys):
    code = ledger.main(["t1", "plan", "--start", "--workdir", "/tmp/some-task", "--next", "x"])
    assert code == ledger.EXIT_VOLATILE
    assert "refused" in capsys.readouterr().err
    assert ledger.entries("t1") == []


def test_dev_shm_refused_and_override_records(ledger):
    assert ledger.volatile_reason("/dev/shm/x")[1] is True
    assert ledger.main(["t1", "plan", "--start", "--workdir", "/tmp/x", "--allow-volatile", "--next", "y"]) == 0
    assert ledger.entries("t1")[-1]["workdir"] == "/tmp/x"


def test_tmpdir_and_tmpfs_warn_only(durable, tmp_path, monkeypatch):
    ledger = durable
    monkeypatch.setenv("TMPDIR", str(tmp_path / "scratch"))
    reason, refused = ledger.volatile_reason(tmp_path / "scratch" / "w")
    assert reason and not refused
    monkeypatch.delenv("TMPDIR")
    mounts = tmp_path / "mounts"
    mounts.write_text("tmpfs /mnt/ram tmpfs rw 0 0\n/dev/sda1 / ext4 rw 0 0\n", encoding="utf-8")
    monkeypatch.setattr(ledger, "VOLATILE_FS_TYPES", frozenset({"tmpfs", "ramfs"}))
    reason, refused = ledger.volatile_reason("/mnt/ram/w", mounts_file=str(mounts))
    assert "tmpfs" in reason and not refused
    assert ledger.volatile_reason("/srv/w", mounts_file=str(mounts)) == ("", False)


def test_durable_workdir_records_head_and_prereqs(durable, tmp_path):
    ledger = durable
    work = _durable(tmp_path)
    subprocess.run(["git", "init", "-q", str(work)], check=True)
    subprocess.run(["git", "-C", str(work), "-c", "user.name=t", "-c", "user.email=t@e", "commit",
                    "-q", "--allow-empty", "-m", "c"], check=True)
    head = subprocess.run(["git", "-C", str(work), "rev-parse", "HEAD"], capture_output=True,
                          text=True, check=True).stdout.strip()
    assert ledger.main(["t1", "plan", "--start", "--workdir", str(work), "--prereq", "disk:0",
                        "--next", "write code"]) == 0
    row = ledger.entries("t1")[-1]
    assert row["workdir"] == str(work) and row["head"] == head and row["prereq"] == ["disk:0"]
    text = ledger.brief("t1")
    assert text.startswith("Resume at: write code")
    assert "prereq ok: disk:" in text


def test_failing_prereq_is_reported(durable, tmp_path):
    ledger = durable
    work = _durable(tmp_path)
    ledger.main(["t1", "plan", "--start", "--workdir", str(work), "--prereq", "disk:999999", "--next", "n"])
    assert "prereq FAIL: disk:" in ledger.brief("t1")


# R2 ---------------------------------------------------------------------------

def _pushed_repo(tmp_path: Path) -> tuple[Path, str]:
    bare = _durable(tmp_path, "remote.git")
    subprocess.run(["git", "init", "-q", "--bare", str(bare)], check=True)
    work = _durable(tmp_path, "clone")
    subprocess.run(["git", "clone", "-q", str(bare), str(work)], check=True, capture_output=True)
    git = ["git", "-C", str(work), "-c", "user.name=t", "-c", "user.email=t@e"]
    subprocess.run(git + ["commit", "-q", "--allow-empty", "-m", "c"], check=True)
    subprocess.run(git + ["push", "-q", "-u", "origin", "HEAD"], check=True, capture_output=True)
    head = subprocess.run(git + ["rev-parse", "HEAD"], capture_output=True, text=True, check=True).stdout.strip()
    return work, head


def test_push_without_checkpoint_is_flagged(ledger, tmp_path, capsys):
    work, head = _pushed_repo(tmp_path)
    ledger.record("t2", "plan", workdir=str(work), head="0" * 40, next_action="push")
    assert ledger.main(["t2", "--verify"]) == ledger.EXIT_UNCHECKPOINTED
    assert head[:12] in capsys.readouterr().err


def test_push_with_checkpoint_passes(ledger, tmp_path):
    work, head = _pushed_repo(tmp_path)
    ledger.record("t2", "push", workdir=str(work), head=head[:12], next_action="open PR")
    assert ledger.main(["t2", "--verify"]) == 0


# R3 ---------------------------------------------------------------------------

def test_restart_then_entry_lists_task_and_next_step(ledger, tmp_path):
    work = _durable(tmp_path)
    scratch = tmp_path / "volatile-tmp"
    scratch.mkdir()
    now = time.time()
    ledger.record("t1", "pr", workdir=str(work), next_action="run the review", start=True, now=now - 600)
    ledger.record("t3", "done", workdir=str(work), now=now - 500)
    ledger.record("old", "plan", workdir=str(work), next_action="old step", now=now - 30 * 86400)
    import shutil
    shutil.rmtree(scratch)  # simulated restart: /tmp gone, the state dir kept
    listing = ledger.unfinished_listing(work, now=now)
    lines = listing.splitlines()
    assert "t1" in lines[1] and "Resume at: run the review" in lines[1]
    assert "old [stale]" in lines[2]
    assert "t3" not in listing
    assert ledger.unfinished_listing(_durable(tmp_path, "elsewhere"), now=now) == ""


def test_tool_entry_prints_unfinished_tasks(ledger, tmp_path, monkeypatch):
    work = _durable(tmp_path)
    ledger.record("t1", "pr", workdir=str(work), next_action="merge PR 5")
    monkeypatch.chdir(work)
    out = subprocess.run([sys.executable, str(ROOT / "tool.py"), "entry"], capture_output=True, text=True,
                         cwd=work, env={**__import__("os").environ})
    assert "Unfinished tasks" in out.stdout and "Resume at: merge PR 5" in out.stdout


# R4 ---------------------------------------------------------------------------

def test_budget_exhausted_records_planned_stop_with_next_step(ledger, tmp_path, capsys):
    work = _durable(tmp_path)
    ledger.record("t1", "plan", workdir=str(work), next_action="commit", start=True, now=time.time() - 40 * 60)
    code = ledger.main(["t1", "commit", "--next", "push branch"])
    assert code == 3
    rows = ledger.entries("t1")
    assert rows[-1].get(ledger.PLANNED_STOP) == "budget"
    err = capsys.readouterr().err
    assert "planned stop (budget) at step 'commit'; next push branch" in err
    text = ledger.brief("t1")
    assert text.startswith("Resume at: push branch")
    assert "cause: planned stop (budget)" in text


def test_budget_check_alone_also_marks_planned_stop(ledger):
    ledger.record("t1", "plan", next_action="x", start=True, now=time.time() - 40 * 60)
    assert ledger.main(["t1", "--budget"]) == 3
    assert ledger.entries("t1")[-1].get(ledger.PLANNED_STOP) == "budget"


# R5 ---------------------------------------------------------------------------

def test_restart_cause_named(ledger, monkeypatch):
    then = time.time() - 3600
    ledger.record("t1", "review", next_action="merge", now=then)
    monkeypatch.setenv("CHAOS_ENGINE_BOOT_TIME", str(then + 60))
    assert "cause: box restarted" in ledger.brief("t1")


def test_host_cap_cause_named(ledger, monkeypatch):
    monkeypatch.setenv("CHAOS_ENGINE_BOOT_TIME", "1")
    ledger.record("t1", "review", next_action="merge", now=time.time() - 3 * 3600)
    assert "likely the host cap" in ledger.brief("t1")


def test_recent_checkpoint_has_no_cause(ledger, monkeypatch):
    monkeypatch.setenv("CHAOS_ENGINE_BOOT_TIME", "1")
    ledger.record("t1", "review", next_action="merge")
    assert "cause:" not in ledger.brief("t1")
