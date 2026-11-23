"""Test-run checkpoint next line and Surefire classified skips (issue 195)."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "runtime"))

import task_ledger  # noqa: E402

_SUMMARY = "Tests run: 2, Failures: 0, Errors: 0, Skipped: 1"
_CLASSIFIED_LOG = _SUMMARY + "\nBLOCKED G54\n"
_NEXT = "methods: LoginTest; hypothesis: calendar slot; command: mvn -q test"


def _classify(log: str, exit_code: int, **kwargs: object) -> str:
    classify = getattr(task_ledger, "classify_surefire", None)
    assert callable(classify)
    return classify(log, exit_code, **kwargs)


def _isolate(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("CHAOS_ENGINE_TASKS_DIR", str(tmp_path / "tasks"))
    monkeypatch.setenv("CHAOS_ENGINE_SPEC_DIR", str(tmp_path / "specs"))
    specs = tmp_path / "specs"
    specs.mkdir()
    (specs / "spec-t1.md").write_text("spec\n", encoding="utf-8")
    monkeypatch.setattr(task_ledger, "REFUSED_VOLATILE_ROOTS", ("/nonexistent-volatile-root",))
    monkeypatch.setattr(task_ledger, "VOLATILE_FS_TYPES", frozenset())


def test_classified_skip_is_not_failed():
    result = _classify(_CLASSIFIED_LOG, 0)
    assert "FAILED" not in result
    assert result.startswith("CLASSIFIED")
    assert "Tests run: 2" in result
    assert "Skipped: 1" in result


def test_unclassified_skip_is_failed():
    result = _classify(_SUMMARY + "\nskipped because flaky\n", 0)
    assert "FAILED" in result


def test_glued_token_is_not_classified():
    result = _classify(_SUMMARY + "\nBLOCKED G54extra\n", 0)
    assert "FAILED" in result


def test_id_outside_skip_line_is_failed():
    log = _SUMMARY + "\nBLOCKED G54extra\nRunning Test1\n"
    result = _classify(log, 0)
    assert "FAILED" in result


def test_id_on_skip_phrase_is_classified():
    result = _classify(_SUMMARY + "\ncom.example.Test1 skipped because flaky\n", 0)
    assert result.startswith("CLASSIFIED")
    assert "FAILED" not in result


def test_bare_skip_ignores_id_on_another_line():
    log = _SUMMARY + "\nskipped because flaky\nRunning Test1\n"
    result = _classify(log, 0)
    assert "FAILED" in result


def test_missing_summary_is_failed():
    result = _classify("BLOCKED G54\n", 0)
    assert "FAILED" in result


def test_all_pass_is_classified():
    result = _classify("Tests run: 2, Failures: 0, Errors: 0, Skipped: 0\n", 0)
    assert result.startswith("CLASSIFIED")
    assert "FAILED" not in result


def test_nonzero_exit_is_failed():
    result = _classify(_CLASSIFIED_LOG, 1)
    assert "FAILED" in result


def test_lost_device_is_failed():
    result = _classify(_CLASSIFIED_LOG, 0, lost_device=True)
    assert "FAILED" in result


def test_resume_prints_test_run_next(tmp_path: Path, monkeypatch, capsys):
    _isolate(tmp_path, monkeypatch)
    assert task_ledger.main(
        ["t1", "watch", "--start", "--kind", "test-run", "--next", _NEXT]
    ) == 0
    capsys.readouterr()
    assert task_ledger.main(["t1"], "resume") == 0
    out = capsys.readouterr().out
    assert "LoginTest" in out
    assert "calendar slot" in out
    assert "mvn -q test" in out


def test_test_run_next_without_labels_is_refused(tmp_path: Path, monkeypatch, capsys):
    _isolate(tmp_path, monkeypatch)
    code = task_ledger.main(
        ["t1", "watch", "--start", "--kind", "test-run", "--next", "run the suite"]
    )
    captured = capsys.readouterr()
    assert code != 0
    assert "methods:" in captured.err
    assert "hypothesis:" in captured.err
    assert "command:" in captured.err
    assert not (tmp_path / "tasks" / "t1.jsonl").exists()
    task_ledger.main(["t1"], "resume")
    out = capsys.readouterr().out
    assert "Resume at: run the suite" not in out
