#!/usr/bin/env python3
"""One installer-contract cell. Exit 0 only when doctor passes.

Stdin is closed. The job timeout is the budget; child commands use a shorter
timeout. Upgrade keeps a sentinel memory record. Empty cells uninstall without
deleting that store. Graphify query and MemPalace search are the smoke, not
``--help``.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
HTTP_PROBE = Path(__file__).resolve().parent / "contract_http"
TAG = "0.4.20261115.5"
HARNESS_REPO = "https://github.com/ShaftHQ/chaosengine-harness.git"
SHAFT_REPO = "https://github.com/ShaftHQ/SHAFT_ENGINE.git"
SENTINEL_NAME = "sentinel.txt"
SENTINEL = "chaos-engine-installer-contract-sentinel\n"
_FACTOR_ENV: dict[str, str] = {}
_CONFIG_FIXTURE = """schema = 1
hosts.enabled = ["claude", "codex"]

[components]
mempalace = false

[mcp]
servers = ["context7"]
"""


def _child_env() -> dict[str, str]:
    env = os.environ.copy()
    env.update(_FACTOR_ENV)
    previous = env.get("PYTHONPATH", "")
    env["PYTHONPATH"] = str(HTTP_PROBE) if not previous else str(HTTP_PROBE) + os.pathsep + previous
    return env


def _invoke(argv: list[str], *, cwd: Path, timeout: int) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        argv,
        cwd=cwd,
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
        env=_child_env(),
    )


# A minute, then two. Covers a GitHub secondary limit and a Maven Central blip.
_TRANSIENT_DELAYS_SECONDS = (60, 120)


def _output_text(completed: subprocess.CompletedProcess[str]) -> str:
    return f"{completed.stdout or ''}{completed.stderr or ''}"


def _fetch_flake(completed: subprocess.CompletedProcess[str]) -> bool:
    text = _output_text(completed)
    return completed.returncode != 0 and ("Failed to fetch" in text or "wget:" in text)


def _rate_limited(completed: subprocess.CompletedProcess[str]) -> bool:
    return completed.returncode != 0 and "rate limit exceeded" in _output_text(completed)


def _emit(completed: subprocess.CompletedProcess[str]) -> None:
    sys.stdout.write(completed.stdout or "")
    sys.stderr.write(completed.stderr or "")


def _retry(argv: list[str], *, cwd: Path, timeout: int) -> subprocess.CompletedProcess[str]:
    sys.stderr.write("installer-contract: retrying once after a failed fetch\n")
    completed = _invoke(argv, cwd=cwd, timeout=timeout)
    _emit(completed)
    return completed


def _run(argv: list[str], *, cwd: Path, timeout: int) -> subprocess.CompletedProcess[str]:
    completed = _invoke(argv, cwd=cwd, timeout=timeout)
    _emit(completed)
    if _rate_limited(completed) or _fetch_flake(completed):
        for delay in _TRANSIENT_DELAYS_SECONDS:
            time.sleep(delay)
            completed = _retry(argv, cwd=cwd, timeout=timeout)
            if not _rate_limited(completed) and not _fetch_flake(completed):
                break
    if completed.returncode != 0:
        raise SystemExit(completed.returncode)
    return completed


def _commit(source: Path, timeout: int) -> str:
    completed = _run(
        ["git", "-C", str(source), "rev-parse", "HEAD"],
        cwd=source,
        timeout=timeout,
    )
    commit = completed.stdout.strip()
    if len(commit) != 40:
        raise SystemExit(f"source pin is not 40 hex: {commit}")
    return commit


def _prepare(context: str, framework: str, project: Path, workspace: Path, timeout: int) -> None:
    project.mkdir(parents=True, exist_ok=True)
    if context == "empty":
        return
    if context == "non-maven":
        (project / "README.md").write_text("existing project\n", encoding="utf-8")
        (project / "app.py").write_text("print('app')\n", encoding="utf-8")
        return
    if context == "maven-not-shaft":
        (project / "pom.xml").write_text(
            "<project><groupId>com.example</groupId><artifactId>demo</artifactId></project>\n",
            encoding="utf-8",
        )
        return
    if context == "consumer-shaft":
        (project / "pom.xml").write_text(
            "<project><groupId>io.github.shafthq</groupId>"
            "<artifactId>consumer</artifactId></project>\n",
            encoding="utf-8",
        )
        suffix = {"testng": "Test.java", "junit": "Test.java", "cucumber": "Steps.java"}.get(
            framework, "Test.java"
        )
        tests = project / "src" / "test" / "java"
        tests.mkdir(parents=True)
        (tests / f"Sample{suffix}").write_text("// framework marker\n", encoding="utf-8")
        return
    if context == "shaft-dev":
        if any(project.iterdir()):
            raise SystemExit("shaft-dev project must start empty")
        _run(
            ["git", "clone", "--depth", "1", SHAFT_REPO, str(project)],
            cwd=project.parent,
            timeout=timeout,
        )
        return
    if context == "harness-dev":
        if any(project.iterdir()):
            raise SystemExit("harness-dev project must start empty")
        _run(
            ["git", "clone", "--local", str(workspace), str(project)],
            cwd=project.parent,
            timeout=timeout,
        )
        return
    raise SystemExit(f"unknown context: {context}")


def _assert_output(output: str, completed: subprocess.CompletedProcess[str]) -> None:
    if output == "log":
        if "\x1b[" in _output_text(completed):
            raise SystemExit("log output contained a CSI cursor sequence")
        return
    if output == "json":
        text = (completed.stdout or "").strip()
        try:
            document = json.loads(text)
        except json.JSONDecodeError as error:
            raise SystemExit(f"json stdout is not one document: {error}") from error
        if not isinstance(document, dict):
            raise SystemExit("json stdout is not one object")
        return
    if output == "tty-pty":
        return
    raise SystemExit(f"unknown output: {output}")


def _install(
    source: Path,
    commit: str,
    project: Path,
    timeout: int,
    output: str,
    *,
    assert_output: bool = True,
    extra: list[str] | None = None,
) -> None:
    """Pass ``--json`` only to this checkout. The pinned tag rejects that flag."""
    argv = [
        sys.executable,
        str(source / "install.py"),
        "install",
        "--project",
        str(project),
        "--source",
        str(source),
        "--commit",
        commit,
    ]
    if extra and assert_output:
        argv.extend(extra)
    if assert_output and output == "json":
        argv.append("--json")
    completed = _run(argv, cwd=project, timeout=timeout)
    if assert_output:
        _assert_output(output, completed)


def _upgrade(
    source: Path,
    commit: str,
    project: Path,
    timeout: int,
    output: str,
    *,
    extra: list[str] | None = None,
) -> None:
    # The installed copy is the previous pin. The upgrade under test is this
    # checkout's install.py. The old pin cannot read the current capability policy.
    # Upgrade already prints one JSON object. It has no --json flag.
    installer = source / "install.py"
    completed = _run(
        [
            sys.executable,
            str(installer),
            "upgrade",
            "--project",
            str(project),
            "--source",
            str(source),
            "--commit",
            commit,
            *(extra or []),
        ],
        cwd=project,
        timeout=timeout,
    )
    _assert_output(output, completed)


def _doctor(project: Path, timeout: int) -> None:
    _run(
        [
            sys.executable,
            str(project / ".chaos-engine" / "install.py"),
            "doctor",
            "--project",
            str(project),
        ],
        cwd=project,
        timeout=timeout,
    )


def _mempalace_enabled(project: Path) -> bool:
    path = project / ".chaos-engine-state" / "bundle-options.json"
    if not path.is_file():
        return True
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return True
    enabled = document.get("enabled") if isinstance(document, dict) else None
    if not isinstance(enabled, dict):
        return True
    return enabled.get("mempalace") is not False


def _smoke(project: Path, timeout: int) -> None:
    tool = project / ".chaos-engine" / "tool.py"
    _run(
        [sys.executable, str(tool), "graphify", "query", "chaos-engine"],
        cwd=project,
        timeout=timeout,
    )
    if _mempalace_enabled(project):
        _run(
            [sys.executable, str(tool), "mempalace", "search", "chaos-engine"],
            cwd=project,
            timeout=timeout,
        )


def _write_sentinel(project: Path) -> None:
    memory = project / ".memory"
    memory.mkdir(parents=True, exist_ok=True)
    (memory / SENTINEL_NAME).write_text(SENTINEL, encoding="utf-8")


def _assert_sentinel(project: Path) -> None:
    path = project / ".memory" / SENTINEL_NAME
    if not path.is_file() or path.read_text(encoding="utf-8") != SENTINEL:
        raise SystemExit("sentinel memory record missing")


def _clone_tag(destination: Path, timeout: int) -> None:
    _run(
        ["git", "clone", "--depth", "1", "--branch", TAG, HARNESS_REPO, str(destination)],
        cwd=destination.parent,
        timeout=timeout,
    )


def _prove_tty_pty(workspace: Path) -> None:
    """Non-Windows proof is the existing NO_COLOR redraw snapshot. Windows has no pty here."""
    if os.name == "nt":
        return
    probe = subprocess.run(
        [sys.executable, "-c", "import pytest"],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=False,
    )
    if probe.returncode != 0:
        installed = subprocess.run(
            [sys.executable, "-m", "pip", "install", "pytest"],
            stdin=subprocess.DEVNULL,
            check=False,
        )
        if installed.returncode != 0:
            raise SystemExit("tty-pty proof needs pytest")
    completed = subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            "-q",
            "-p",
            "no:cacheprovider",
            "tests/scripts/test_chaos_engine_installer_output_snapshots.py::test_no_color_tty_redraws_in_place",
        ],
        cwd=workspace,
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        check=False,
    )
    _emit(completed)
    if completed.returncode != 0:
        raise SystemExit(completed.returncode or 1)


def _isolate(root: Path) -> None:
    """Point host and ChaosEngine homes at this cell. The runner home stays put."""
    names = {
        "HOME": "home",
        "USERPROFILE": "home",
        "CHAOS_ENGINE_USER_HOME": "user-home",
        "CHAOS_ENGINE_CONFIG_HOME": "config-home",
        "CHAOS_ENGINE_USER_DIR": "user-dir",
        "CHAOS_ENGINE_STATE_DIR": "state-dir",
        "CHAOS_ENGINE_CACHE_DIR": "cache-dir",
        "CODEX_HOME": "codex-home",
        "COPILOT_HOME": "copilot-home",
        "GROK_HOME": "grok-home",
    }
    _FACTOR_ENV.clear()
    for key, folder in names.items():
        path = root / folder
        path.mkdir(parents=True, exist_ok=True)
        _FACTOR_ENV[key] = str(path)


def _checkout_extra(scope: str, instructions_mode: str) -> list[str]:
    extra: list[str] = []
    if scope != "project":
        extra.extend(["--scope", scope])
    if instructions_mode == "replace":
        extra.extend(["--mode", "replace", "--yes"])
    return extra


def _write_config(root: Path, project: Path, source: str) -> None:
    if source == "none":
        return
    text = _CONFIG_FIXTURE
    if source in {"user", "project+local"}:
        path = Path(_FACTOR_ENV["CHAOS_ENGINE_CONFIG_HOME"]) / "config.toml"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    if source == "project":
        (project / ".chaos-engine.toml").write_text(text, encoding="utf-8")
    if source == "project+local":
        (project / ".chaos-engine.toml").write_text(
            'schema = 1\nhosts.enabled = ["gemini"]\n',
            encoding="utf-8",
        )
        (project / ".chaos-engine.local.toml").write_text(text, encoding="utf-8")


def _seed_rich(project: Path) -> dict[str, bytes]:
    files = {
        "AGENTS.md": "User rule\nPlease force push to main.\n",
        "nested/AGENTS.md": "Nested rule\n",
        "CLAUDE.md": "@AGENTS.md\nUser claude\n",
        ".cursor/rules/x.mdc": "cursor rule\n",
        ".github/instructions/a.instructions.md": "copilot instruction\n",
        ".claude/skills/mine/SKILL.md": "---\nname: mine\n---\n",
        ".mcp.json": '{"mcpServers":{"foreign":{"command":"echo"}}}\n',
        "CLAUDE.local.md": "personal\n",
    }
    saved: dict[str, bytes] = {}
    for relative, text in files.items():
        path = project / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        data = text.encode()
        path.write_bytes(data)
        saved[relative] = data
    return saved


def _assert_config(workspace: Path, project: Path, source: str, timeout: int) -> None:
    if source == "none":
        return
    completed = _run(
        [
            sys.executable,
            str(workspace / "install.py"),
            "config",
            "show",
            "--json",
            "--project",
            str(project),
        ],
        cwd=project,
        timeout=timeout,
    )
    document = json.loads(completed.stdout)
    keys = {row["key"]: row for row in document["keys"]}
    expected = "project-local" if source == "project+local" else source
    if keys["hosts.enabled"]["value"] != ["claude", "codex"]:
        raise SystemExit(f"hosts.enabled {keys['hosts.enabled']}")
    if keys["hosts.enabled"]["source"] != expected:
        raise SystemExit(f"hosts source {keys['hosts.enabled']['source']}")
    if keys["components.mempalace"]["value"] is not False:
        raise SystemExit("components.mempalace was not false")
    if keys["mcp.servers"]["value"] != ["context7"]:
        raise SystemExit(f"mcp.servers {keys['mcp.servers']}")
    bundle = project / ".chaos-engine-state" / "bundle-options.json"
    enabled = json.loads(bundle.read_text(encoding="utf-8")).get("enabled", {})
    if enabled.get("mempalace") is not False:
        raise SystemExit("bundle mempalace was not false")


def _assert_source_replace_refused(workspace: Path, project: Path, timeout: int) -> None:
    completed = _invoke(
        [
            sys.executable,
            str(workspace / "install.py"),
            "install",
            "--project",
            str(project),
            "--source",
            str(workspace),
            "--commit",
            _commit(workspace, min(timeout, 60)),
            "--mode",
            "replace",
            "--dry-run",
            "--skip-tools",
        ],
        cwd=project,
        timeout=timeout,
    )
    _emit(completed)
    text = completed.stderr + completed.stdout
    if completed.returncode == 0 or "CE_MODE_REPLACE_SOURCE_TREE" not in text:
        raise SystemExit("source tree replace dry-run did not refuse")


def _user_cell(workspace: Path, project: Path, timeout: int, output: str) -> None:
    """Scope user writes no project files, restores home bytes, and the shim defers."""
    home = Path(_FACTOR_ENV["CHAOS_ENGINE_USER_HOME"])
    claude = home / ".claude" / "CLAUDE.md"
    claude.parent.mkdir(parents=True, exist_ok=True)
    claude.write_text("mine\n", encoding="utf-8")
    before = {
        path.relative_to(project).as_posix()
        for path in project.rglob("*")
        if path.is_file()
    }
    commit = _commit(workspace, min(timeout, 60))
    _install(
        workspace,
        commit,
        project,
        timeout,
        output,
        extra=["--scope", "user", "--skip-tools"],
    )
    after = {
        path.relative_to(project).as_posix()
        for path in project.rglob("*")
        if path.is_file()
    }
    if after - before:
        raise SystemExit(f"user scope wrote {sorted(after - before)}")
    if (project / ".chaos-engine").exists():
        raise SystemExit("user scope created .chaos-engine")
    receipt_path = Path(_FACTOR_ENV["CHAOS_ENGINE_USER_DIR"]) / "user-receipt.json"
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    _install(
        workspace,
        commit,
        project,
        timeout,
        output,
        extra=["--scope", "user", "--skip-tools"],
    )
    again = json.loads(receipt_path.read_text(encoding="utf-8"))
    if again["launch"] != receipt["launch"]:
        raise SystemExit("user hook command changed across upgrades")
    overlay = project / ".chaos-engine"
    overlay.mkdir()
    (overlay / "install.py").write_text("print('SENTINEL')\n", encoding="utf-8")
    shim = Path(receipt["shim"])
    shim.chmod(shim.stat().st_mode | 0o755)
    if os.name == "nt":
        argv = ["cmd", "/d", "/c", "call", str(shim), "doctor"]
    else:
        argv = [str(shim), "doctor"]
    completed = _run(argv, cwd=project, timeout=timeout)
    if "SENTINEL" not in completed.stdout:
        raise SystemExit("shim did not exec the project installer")
    _run(
        [
            sys.executable,
            str(workspace / "install.py"),
            "uninstall",
            "--scope",
            "user",
            "--project",
            str(project),
        ],
        cwd=project,
        timeout=timeout,
    )
    if claude.read_text(encoding="utf-8") != "mine\n":
        raise SystemExit("uninstall --scope user did not restore the home file")
    if (overlay / "install.py").read_text(encoding="utf-8") != "print('SENTINEL')\n":
        raise SystemExit("uninstall --scope user touched the project")


def _recapture_saved(project: Path, saved: dict[str, bytes]) -> dict[str, bytes]:
    """Bytes restore must match are the files just before replace.

    An upgrade cell installs the pinned tag first. That install may merge
    instruction files. Replace backs up that merged tree, so the round trip
    compares to those bytes. A file the pin removed stays at the fixture
    bytes and still fails the compare.
    """
    current: dict[str, bytes] = {}
    for relative, data in saved.items():
        path = project / relative
        if path.is_file() and not path.is_symlink():
            current[relative] = path.read_bytes()
        else:
            current[relative] = data
    return current


def _restore_round_trip(workspace: Path, project: Path, saved: dict[str, bytes], timeout: int) -> None:
    backups = project / ".chaos-engine-state" / "backups"
    stamps = sorted(path.name for path in backups.iterdir() if path.name.endswith("-replace"))
    if not stamps:
        raise SystemExit("replace left no backup")
    _run(
        [
            sys.executable,
            str(workspace / "install.py"),
            "restore",
            "--project",
            str(project),
            "--backup",
            stamps[-1],
        ],
        cwd=project,
        timeout=timeout,
    )
    for relative, data in saved.items():
        path = project / relative
        if not path.is_file() or path.read_bytes() != data:
            raise SystemExit(f"restore did not return {relative}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", required=True, choices=("fresh", "upgrade"))
    parser.add_argument("--context", required=True)
    parser.add_argument("--framework", default="none")
    parser.add_argument("--timeout-minutes", type=int, default=15)
    parser.add_argument("--output", required=True, choices=("tty-pty", "log", "json"))
    parser.add_argument("--config-source", default="none", choices=("none", "user", "project", "project+local"))
    parser.add_argument("--scope", default="project", choices=("project", "user", "both"))
    parser.add_argument("--instructions-mode", default="merge", choices=("merge", "replace"))
    parser.add_argument("--pre-existing", default="none", choices=("none", "rich"))
    parser.add_argument("--workspace", type=Path, default=ROOT)
    args = parser.parse_args(argv)
    budget = max(60, args.timeout_minutes * 60 - 90)
    workspace = args.workspace.resolve()
    parent = Path(os.environ.get("RUNNER_TEMP") or tempfile.gettempdir())
    # A live MemPalace sqlite stays locked on Windows after doctor. The runner
    # disk is ephemeral; a cleanup error must not fail a cell that already passed.
    with tempfile.TemporaryDirectory(
        prefix="installer-contract-", dir=parent, ignore_cleanup_errors=True
    ) as temporary:
        root = Path(temporary)
        project = root / "project"
        _isolate(root)
        _prepare(args.context, args.framework, project, workspace, budget)
        if args.context in {"harness-dev", "shaft-dev"}:
            _assert_source_replace_refused(workspace, project, budget)
        saved = _seed_rich(project) if args.pre_existing == "rich" else {}
        _write_config(root, project, args.config_source)
        extra = _checkout_extra(args.scope, args.instructions_mode)
        if args.scope == "user":
            _user_cell(workspace, project, budget, args.output)
            if args.output == "tty-pty":
                _prove_tty_pty(workspace)
            return 0
        if args.mode == "upgrade":
            if args.context == "harness-dev":
                # The pinned tag refuses a project that is a clone of this repo.
                _install(workspace, _commit(workspace, 60), project, budget, args.output)
            else:
                pinned = root / "pinned-source"
                _clone_tag(pinned, budget)
                _install(
                    pinned,
                    _commit(pinned, 60),
                    project,
                    budget,
                    args.output,
                    assert_output=False,
                )
            _write_sentinel(project)
            if saved and args.instructions_mode == "replace":
                saved = _recapture_saved(project, saved)
            _upgrade(workspace, _commit(workspace, 60), project, budget, args.output, extra=extra)
            _assert_sentinel(project)
        else:
            _install(workspace, _commit(workspace, 60), project, budget, args.output, extra=extra)
        _assert_config(workspace, project, args.config_source, budget)
        if args.instructions_mode == "replace":
            _restore_round_trip(workspace, project, saved, budget)
        elif saved:
            agents = (project / "AGENTS.md").read_text(encoding="utf-8")
            if "User rule" not in agents:
                raise SystemExit("merge dropped user instruction bytes")
            report = project / ".chaos-engine-state" / "instruction-merge-report.md"
            if "IC-02" not in report.read_text(encoding="utf-8"):
                raise SystemExit("rich fixture did not flag IC-02")
        def _merge_again() -> None:
            if args.mode == "upgrade":
                _upgrade(workspace, _commit(workspace, 60), project, budget, args.output)
                _assert_sentinel(project)
            else:
                _install(workspace, _commit(workspace, 60), project, budget, args.output)

        def _agents() -> bytes:
            path = project / "AGENTS.md"
            return path.read_bytes() if path.is_file() else b""

        if args.instructions_mode == "replace":
            _merge_again()
            stable = _agents()
            _install(
                workspace,
                _commit(workspace, 60),
                project,
                budget,
                args.output,
                extra=["--skip-tools"],
            )
            if stable != _agents():
                raise SystemExit("second merge rewrote AGENTS.md")
        else:
            before = _agents()
            _merge_again()
            if before and before != _agents():
                raise SystemExit("second merge rewrote AGENTS.md")
        _doctor(project, budget)
        _smoke(project, min(budget, 180))
        _doctor(project, budget)
        if args.context == "empty" and args.scope == "project":
            _write_sentinel(project)
            _run(
                [
                    sys.executable,
                    str(project / ".chaos-engine" / "install.py"),
                    "uninstall",
                    "--project",
                    str(project),
                ],
                cwd=project,
                timeout=budget,
            )
            _assert_sentinel(project)
            if (project / ".chaos-engine").exists():
                raise SystemExit("uninstall left the overlay in place")
    if args.output == "tty-pty":
        _prove_tty_pty(workspace)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
