#!/usr/bin/env python3
"""Offline live-task validator and hidden verifier.

The agent workspace is a copy of environment/ only. tests/ is copied in after
the handed-back tree is cloned, so edits under tests/ cannot change the reward.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess  # nosec B404 - bash and git argv, no shell.
import tempfile
import tomllib
from pathlib import Path
from typing import Any

CANARY_RE = re.compile(r"canary:\s*([0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12})")
ALLOWED_SECTIONS = {
    "task": frozenset(),
    "metadata": frozenset({"difficulty", "category"}),
    "agent": frozenset({"timeout_sec", "max_steps"}),
    "verifier": frozenset({"timeout_sec"}),
}
DIFFICULTIES = frozenset({"easy", "medium", "hard"})
CEILINGS = {
    "easy": {"max_steps": 8, "timeout_sec": 60, "verifier_timeout_sec": 20},
    "medium": {"max_steps": 20, "timeout_sec": 180, "verifier_timeout_sec": 30},
    "hard": {"max_steps": 40, "timeout_sec": 600, "verifier_timeout_sec": 60},
}
REQUIRED_FILES = (
    "task.toml",
    "instruction.md",
    "tests/test.sh",
    "solution/solve.sh",
)
ENV_ALLOW = ("PATH", "LANG", "LC_ALL", "LC_CTYPE", "TZ", "TMPDIR", "SYSTEMROOT", "COMSPEC", "PATHEXT")
TOKEN = re.compile(rb"eyJ[A-Za-z0-9_-]{10,}\.eyJ[A-Za-z0-9_-]{10,}")
ASSIGNMENT = re.compile(
    rb"(?i)(client_?secret|access_?key|password|api_?key|session_?id)[\"']?\s*[:=]\s*[\"']?"
    rb"([A-Za-z0-9._~+/=-]{16,})(?!\s*\()"
)
MATRIX_STATUSES = frozenset({"pass", "fail", "skipped", "unknown"})


def _authored_files(task: Path) -> list[Path]:
    found = [task / relative for relative in REQUIRED_FILES]
    environment = task / "environment"
    if environment.is_dir():
        found.extend(path for path in environment.rglob("*") if path.is_file())
    return found


def _canary_in(path: Path) -> str | None:
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeError):
        return None
    match = CANARY_RE.search(text)
    return match.group(1).lower() if match else None


def validate_task(task: Path) -> list[str]:
    """Reject unknown keys, missing files, a missing canary, and tier-ceiling breaches."""
    defects: list[str] = []
    task = Path(task)
    for relative in REQUIRED_FILES:
        if not (task / relative).is_file():
            defects.append(f"missing {relative}")
    environment = task / "environment"
    if not environment.is_dir() or not any(environment.rglob("*")):
        defects.append("missing environment/")
    toml_path = task / "task.toml"
    document: dict[str, Any] = {}
    if toml_path.is_file():
        try:
            document = tomllib.loads(toml_path.read_text(encoding="utf-8"))
        except tomllib.TOMLDecodeError as exc:
            defects.append(f"task.toml: {exc}")
            document = {}
        if not isinstance(document, dict):
            defects.append("task.toml must be a table")
            document = {}
        for section, allowed in ALLOWED_SECTIONS.items():
            if section not in document:
                defects.append(f"missing [{section}]")
                continue
            table = document[section]
            if not isinstance(table, dict):
                defects.append(f"[{section}] must be a table")
                continue
            unknown = sorted(set(table) - allowed)
            if unknown:
                defects.append(f"unknown keys in [{section}]: {', '.join(unknown)}")
        extra = sorted(set(document) - set(ALLOWED_SECTIONS))
        if extra:
            defects.append(f"unknown sections: {', '.join(extra)}")
        meta = document.get("metadata") if isinstance(document.get("metadata"), dict) else {}
        agent = document.get("agent") if isinstance(document.get("agent"), dict) else {}
        verifier = document.get("verifier") if isinstance(document.get("verifier"), dict) else {}
        difficulty = str(meta.get("difficulty") or "")
        if difficulty not in DIFFICULTIES:
            defects.append("metadata.difficulty must be easy|medium|hard")
        else:
            ceiling = CEILINGS[difficulty]
            max_steps = agent.get("max_steps")
            timeout_sec = agent.get("timeout_sec")
            verifier_timeout = verifier.get("timeout_sec")
            if not isinstance(max_steps, int) or isinstance(max_steps, bool) or max_steps < 1:
                defects.append("agent.max_steps must be an integer >= 1")
            elif max_steps > ceiling["max_steps"]:
                defects.append(f"agent.max_steps {max_steps} exceeds {difficulty} ceiling {ceiling['max_steps']}")
            if not isinstance(timeout_sec, int) or isinstance(timeout_sec, bool) or timeout_sec < 1:
                defects.append("agent.timeout_sec must be an integer >= 1")
            elif timeout_sec > ceiling["timeout_sec"]:
                defects.append(f"agent.timeout_sec {timeout_sec} exceeds {difficulty} ceiling {ceiling['timeout_sec']}")
            if not isinstance(verifier_timeout, int) or isinstance(verifier_timeout, bool) or verifier_timeout < 1:
                defects.append("verifier.timeout_sec must be an integer >= 1")
            elif verifier_timeout > ceiling["verifier_timeout_sec"]:
                defects.append(
                    f"verifier.timeout_sec {verifier_timeout} exceeds {difficulty} ceiling {ceiling['verifier_timeout_sec']}"
                )
        if not str(meta.get("category") or "").strip():
            defects.append("metadata.category is required")
    canaries = []
    for path in _authored_files(task):
        if not path.is_file():
            continue
        canary = _canary_in(path)
        if not canary:
            defects.append(f"missing canary in {path.relative_to(task)}")
        else:
            canaries.append(canary)
    if canaries and len(set(canaries)) != 1:
        defects.append("canary GUID differs across authored files")
    return defects


def _verifier_timeout(task: Path) -> int:
    document = tomllib.loads((task / "task.toml").read_text(encoding="utf-8"))
    timeout = document.get("verifier", {}).get("timeout_sec", 20)
    return int(timeout) if isinstance(timeout, int) else 20


def agent_workspace(task: Path, dest: Path) -> None:
    """Copy environment/ only. Verifier and oracle files stay out."""
    dest.mkdir(parents=True, exist_ok=True)
    environment = Path(task) / "environment"
    for path in environment.rglob("*"):
        target = dest / path.relative_to(environment)
        if path.is_dir():
            target.mkdir(parents=True, exist_ok=True)
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, target)
    if (dest / "tests").exists() or (dest / "solution").exists():
        raise RuntimeError("verifier or oracle leaked into the agent workspace")


def _read_reward(path: Path) -> tuple[str, float | None]:
    if not path.is_file():
        return "verifier-error", None
    text = path.read_text(encoding="utf-8").strip()
    if not text:
        return "verifier-error", None
    try:
        return "scored", float(text)
    except ValueError:
        return "verifier-error", None


def grade(task: Path, handed_back: Path, *, env: dict[str, str] | None = None) -> dict[str, Any]:
    """Clone the handed-back tree, then copy tests/ in, then read reward.txt."""
    with tempfile.TemporaryDirectory(prefix="ce-live-grade-") as tmp:
        clone = Path(tmp) / "clone"
        shutil.copytree(handed_back, clone)
        leaked = clone / "tests"
        if leaked.exists():
            shutil.rmtree(leaked)
        shutil.copytree(task / "tests", clone / "tests")
        completed = subprocess.run(  # nosec B603 - fixed bash argv.
            ["bash", str(clone / "tests" / "test.sh")],
            cwd=clone,
            capture_output=True,
            text=True,
            timeout=_verifier_timeout(task),
            env=env,
            check=False,
        )
        status, reward = _read_reward(clone / "reward.txt")
        return {
            "status": status,
            "reward": reward,
            "copied_after_clone": True,
            "returncode": completed.returncode,
        }


def _prepare(task: Path, *, solve: bool, env: dict[str, str] | None = None) -> dict[str, Any]:
    with tempfile.TemporaryDirectory(prefix="ce-live-work-") as tmp:
        work = Path(tmp) / "work"
        agent_workspace(task, work)
        if solve:
            subprocess.run(  # nosec B603 - fixed bash argv.
                ["bash", str(task / "solution" / "solve.sh")],
                cwd=work,
                capture_output=True,
                text=True,
                timeout=_verifier_timeout(task),
                env=env,
                check=False,
            )
        return grade(task, work, env=env)


def prove(task: Path) -> dict[str, Any]:
    """Oracle must score 1 and the untouched environment must score 0."""
    oracle = _prepare(task, solve=True)
    nop = _prepare(task, solve=False)
    ok = (
        oracle.get("status") == "scored"
        and oracle.get("reward") == 1.0
        and nop.get("status") == "scored"
        and nop.get("reward") == 0.0
    )
    return {"ok": ok, "oracle": oracle, "nop": nop}


def scrubbed_environ(home: Path, base: dict[str, str] | None = None) -> dict[str, str]:
    source = os.environ if base is None else base
    env = {key: source[key] for key in ENV_ALLOW if source.get(key)}
    env["PATH"] = source.get("PATH", "")
    env["HOME"] = str(home)
    return env


def scan_secrets(root: Path) -> list[str]:
    """Return secret-pattern hits. The matched value is not included."""
    findings: list[str] = []
    for path in Path(root).rglob("*"):
        if not path.is_file():
            continue
        try:
            data = path.read_bytes()
        except OSError:
            continue
        if TOKEN.search(data):
            findings.append(f"JWT-like token in {path.name}")
        if any(
            re.search(rb"\d", match.group(2)) and re.search(rb"[A-Za-z]", match.group(2))
            for match in ASSIGNMENT.finditer(data)
        ):
            findings.append(f"secret assignment in {path.name}")
    return findings


def measure_numstat(repo: Path, base: str = "HEAD") -> dict[str, int]:
    """files and added+deleted lines from git diff --numstat."""
    completed = subprocess.run(  # nosec B603 - fixed git argv.
        ["git", "-C", str(repo), "diff", "--numstat", base],
        capture_output=True,
        text=True,
        check=False,
    )
    files = 0
    lines = 0
    for line in completed.stdout.splitlines():
        parts = line.split("\t")
        if len(parts) < 3:
            continue
        files += 1
        if parts[0].isdigit() and parts[1].isdigit():
            lines += int(parts[0]) + int(parts[1])
    return {"files": files, "lines": lines}


def bound_exceeded(stats: dict[str, int], *, max_files: int, max_lines: int) -> bool:
    return stats["files"] > max_files or stats["lines"] > max_lines


def run_trial(task: Path, mode: str = "nop") -> dict[str, Any]:
    """Throwaway git repo, allowlisted environment, secret scan afterwards."""
    defects = validate_task(task)
    if defects:
        return {"ok": False, "defects": defects, "secret_findings": []}
    if mode not in {"nop", "oracle"}:
        raise ValueError("mode must be nop or oracle")
    with tempfile.TemporaryDirectory(prefix="ce-live-trial-") as tmp:
        root = Path(tmp) / "trial"
        root.mkdir()
        subprocess.run(["git", "init"], cwd=root, capture_output=True, check=False)
        env = scrubbed_environ(root)
        work = root / "work"
        agent_workspace(task, work)
        if mode == "oracle":
            subprocess.run(  # nosec B603
                ["bash", str(task / "solution" / "solve.sh")],
                cwd=work,
                capture_output=True,
                text=True,
                timeout=_verifier_timeout(task),
                env=env,
                check=False,
            )
        graded = grade(task, work, env=env)
        return {
            "ok": graded["status"] == "scored",
            "grade": graded,
            "secret_findings": scan_secrets(root),
            "verifier_in_workspace": (work / "tests").exists(),
        }


def validate_conformance_matrix(document: dict[str, Any], hosts: list[str]) -> list[str]:
    """skipped and unknown are not pass. A pass without a driven client is a defect."""
    defects: list[str] = []
    if not isinstance(document, dict):
        return ["matrix must be an object"]
    date = str(document.get("date") or "")
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", date):
        defects.append("date must be YYYY-MM-DD")
    rows = document.get("hosts")
    if not isinstance(rows, list):
        return defects + ["hosts must be a list"]
    seen = []
    for row in rows:
        if not isinstance(row, dict):
            defects.append("host row must be an object")
            continue
        host = str(row.get("host") or "")
        seen.append(host)
        if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", str(row.get("date") or "")):
            defects.append(f"{host or 'host'}: date must be YYYY-MM-DD")
        results = row.get("results")
        if not isinstance(results, list) or not results:
            defects.append(f"{host or 'host'}: results required")
            continue
        for item in results:
            if not isinstance(item, dict):
                defects.append(f"{host}: result must be an object")
                continue
            status = str(item.get("status") or "")
            if status not in MATRIX_STATUSES:
                defects.append(f"{host}: status {status or '(blank)'} is not pass|fail|skipped|unknown")
            if status == "pass" and not (row.get("client_version") and row.get("model") and row.get("date")):
                defects.append(f"{host}: pass requires client_version, model, and date")
    missing = [host for host in hosts if host not in seen]
    if missing:
        defects.append("missing hosts: " + ", ".join(missing))
    return defects


def matrix_counts(document: dict[str, Any]) -> dict[str, int]:
    counts = {name: 0 for name in sorted(MATRIX_STATUSES)}
    for row in document.get("hosts") or []:
        if not isinstance(row, dict):
            continue
        for item in row.get("results") or []:
            if isinstance(item, dict) and item.get("status") in counts:
                counts[str(item["status"])] += 1
    return counts
