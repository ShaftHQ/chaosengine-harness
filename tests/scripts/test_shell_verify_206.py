"""Shell-script verification: bash -n and new CR-byte detection (#206)."""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "runtime"))

import pre_done_review  # noqa: E402


def _git(repo: Path, *args: str) -> subprocess.CompletedProcess[bytes]:
    return subprocess.run(
        ["git", *args],
        cwd=repo,
        capture_output=True,
        check=True,
    )


def _init_repo(tmp_path: Path) -> Path:
    _git(tmp_path, "init")
    _git(tmp_path, "config", "user.name", "Test User")
    _git(tmp_path, "config", "user.email", "test@example.com")
    _git(tmp_path, "config", "core.autocrlf", "false")
    return tmp_path


def _commit_file(repo: Path, rel: str, data: bytes) -> Path:
    target = repo / rel
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(data)
    _git(repo, "add", rel)
    _git(repo, "commit", "-m", f"add {rel}")
    return target


def test_corrupted_sh_with_stray_cr_that_bash_n_misses_fails(tmp_path: Path):
    repo = _init_repo(tmp_path)
    script = _commit_file(repo, "scripts/deploy.sh", b"#!/usr/bin/env bash\necho ok\n")
    script.write_bytes(b"#!/usr/bin/env bash\r\nVAR=value\r\necho ok\n")

    bash = shutil.which("bash")
    assert bash is not None
    syntax = subprocess.run([bash, "-n", str(script)], capture_output=True, check=False)
    assert syntax.returncode == 0, "fixture must pass bash -n to prove CR check catches what bash -n misses"

    findings = pre_done_review.shell_script_problems(repo)
    assert findings == ["NEW CR BYTES scripts/deploy.sh (0 -> 2)"]


def test_clean_sh_edit_passes(tmp_path: Path):
    repo = _init_repo(tmp_path)
    script = _commit_file(repo, "scripts/run.sh", b"#!/bin/sh\necho v1\n")
    script.write_bytes(b"#!/bin/sh\necho v2\n")

    assert pre_done_review.shell_script_problems(repo) == []


def test_shell_syntax_error_fails_with_syntax(tmp_path: Path):
    if shutil.which("bash") is None:
        pytest.skip("bash not on PATH")
    repo = _init_repo(tmp_path)
    script = _commit_file(repo, "scripts/broken.sh", b"#!/usr/bin/env bash\necho ok\n")
    script.write_bytes(b"#!/usr/bin/env bash\nif true; then\n  echo missing_fi\n")

    findings = pre_done_review.shell_script_problems(repo)
    assert len(findings) == 1
    assert findings[0].startswith("SYNTAX scripts/broken.sh: ")


def test_extensionless_bash_shebang_with_stray_cr_fails(tmp_path: Path):
    repo = _init_repo(tmp_path)
    script = _commit_file(repo, "bin/helper", b"#!/usr/bin/env bash\necho hi\n")
    script.write_bytes(b"#!/usr/bin/env bash\necho hi\r\n")
    # Non-shell script with CRLF must be ignored.
    other = _commit_file(repo, "bin/pytool", b"#!/usr/bin/env python3\nprint('ok')\n")
    other.write_bytes(b"#!/usr/bin/env python3\r\nprint('ok')\r\n")

    findings = pre_done_review.shell_script_problems(repo)
    assert findings == ["NEW CR BYTES bin/helper (0 -> 1)"]


def test_existing_crlf_file_without_growth_has_no_false_positive(tmp_path: Path):
    repo = _init_repo(tmp_path)
    script = _commit_file(repo, "scripts/legacy.sh", b"#!/bin/sh\r\necho one\r\n")
    # Same CR count (2 -> 2): no false positive.
    script.write_bytes(b"#!/bin/sh\r\necho two\r\n")
    assert pre_done_review.shell_script_problems(repo) == []

    # Reduced CR count (2 -> 1): no false positive.
    script.write_bytes(b"#!/bin/sh\necho two\r\n")
    assert pre_done_review.shell_script_problems(repo) == []

    # Growing CR count (2 -> 3): flagged.
    script.write_bytes(b"#!/bin/sh\r\necho two\r\necho three\r\n")
    assert pre_done_review.shell_script_problems(repo) == [
        "NEW CR BYTES scripts/legacy.sh (2 -> 3)"
    ]


def test_untracked_sh_with_cr_uses_zero_baseline(tmp_path: Path):
    repo = _init_repo(tmp_path)
    _commit_file(repo, "README.md", b"# repo\n")
    (repo / "new.sh").write_bytes(b"#!/bin/sh\necho new\r\n")

    assert pre_done_review.shell_script_problems(repo) == ["NEW CR BYTES new.sh (0 -> 1)"]


def test_cli_shell_check_exit_codes(tmp_path: Path, capsys, monkeypatch):
    repo = _init_repo(tmp_path)
    script = _commit_file(repo, "ok.sh", b"#!/bin/sh\necho a\n")
    script.write_bytes(b"#!/bin/sh\necho b\n")

    assert pre_done_review.main(["--shell-check", str(repo)]) == 0
    assert "pass (0 finding(s))" in capsys.readouterr().out

    # Omitting PROJECT_ROOT checks cwd.
    monkeypatch.chdir(repo)
    assert pre_done_review.main(["--shell-check"]) == 0
    assert "pass (0 finding(s))" in capsys.readouterr().out

    script.write_bytes(b"#!/bin/sh\necho b\r\n")
    assert pre_done_review.main(["--shell-check", str(repo)]) == 1
    out = capsys.readouterr().out
    assert "NEW CR BYTES ok.sh (0 -> 1)" in out
    assert "fail (1 finding(s))" in out

    assert pre_done_review.main(["--shell-check", str(tmp_path / "does-not-exist")]) == 2
    assert pre_done_review.main(["--shell-check", str(repo), "extra"]) == 2
    assert pre_done_review.main(["--shell-check", "--unknown"]) == 2


def test_mechanical_problems_wires_shell_check_and_shell_files(tmp_path: Path):
    repo = _init_repo(tmp_path)
    script = _commit_file(repo, "run.sh", b"#!/bin/sh\necho ok\n")
    script.write_bytes(b"#!/bin/sh\necho bad\r\n")
    base_obs = {"proofs": [{"id": "pytest", "ran": True, "exit": 0}]}

    # Without shell_check or shell_files, existing callers are unaffected.
    assert pre_done_review.mechanical_problems({**base_obs, "project_root": str(repo)}) == []

    # With shell_check: True
    reasons = pre_done_review.mechanical_problems(
        {**base_obs, "project_root": str(repo), "shell_check": True}
    )
    assert reasons == ["NEW CR BYTES run.sh (0 -> 1)"]

    # With explicit shell_files
    reasons_files = pre_done_review.mechanical_problems(
        {**base_obs, "root": str(repo), "shell_files": ["run.sh"]}
    )
    assert reasons_files == ["NEW CR BYTES run.sh (0 -> 1)"]


def test_autocrlf_true_content_edit_and_new_crlf_line_are_not_new_cr(tmp_path: Path):
    repo = _init_repo(tmp_path)
    script = _commit_file(repo, "scripts/legacy.sh", b"#!/bin/sh\necho one\n")
    _git(repo, "config", "core.autocrlf", "true")

    script.write_bytes(b"#!/bin/sh\r\necho two\r\n")
    assert pre_done_review.shell_script_problems(repo) == []

    script.write_bytes(b"#!/bin/sh\r\necho one\r\necho three\r\n")
    assert pre_done_review.shell_script_problems(repo) == []


def test_autocrlf_true_stray_cr_fails_with_new_cr_bytes(tmp_path: Path):
    repo = _init_repo(tmp_path)
    script = _commit_file(repo, "scripts/legacy.sh", b"#!/bin/sh\necho one\n")
    _git(repo, "config", "core.autocrlf", "true")

    script.write_bytes(b"#!/bin/sh\r\ntr -d '\r'\r\n")
    assert pre_done_review.shell_script_problems(repo) == [
        "NEW CR BYTES scripts/legacy.sh (2 -> 3)"
    ]

    script.write_bytes(b"#!/bin/sh\r\necho one\r\r\n")
    assert pre_done_review.shell_script_problems(repo) == [
        "NEW CR BYTES scripts/legacy.sh (2 -> 3)"
    ]


def test_autocrlf_true_eol_lf_still_flags_crlf(tmp_path: Path):
    repo = _init_repo(tmp_path)
    (repo / ".gitattributes").write_text("*.sh text eol=lf\n", encoding="utf-8")
    script = _commit_file(repo, "scripts/legacy.sh", b"#!/bin/sh\necho one\n")
    _git(repo, "add", ".gitattributes")
    _git(repo, "commit", "-m", "attrs")
    _git(repo, "config", "core.autocrlf", "true")

    script.write_bytes(b"#!/bin/sh\r\necho two\r\n")
    assert pre_done_review.shell_script_problems(repo) == [
        "NEW CR BYTES scripts/legacy.sh (0 -> 2)"
    ]


def test_missing_bash_still_runs_cr_check(tmp_path: Path, monkeypatch):
    repo = _init_repo(tmp_path)
    script = _commit_file(repo, "nobash.sh", b"#!/bin/sh\necho ok\n")
    script.write_bytes(b"#!/bin/sh\necho ok\r\n")
    monkeypatch.setattr(shutil, "which", lambda _name: None)

    assert pre_done_review.shell_script_problems(repo) == ["NEW CR BYTES nobash.sh (0 -> 1)"]
