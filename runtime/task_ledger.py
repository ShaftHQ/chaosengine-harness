#!/usr/bin/env python3
"""Task ledger: resume agent work after a host session cap (#6854).

Some hosts (Grok Bot: about 50 minutes) hard-stop a background session on
wall-clock time. Keepalive pings do not reset such a cap, so the work must be
resumable instead: bounded work units, a short durable ledger line per step,
and a resume brief the next session (or the parent) reads instead of the
transcript. The harness enforces the stop: every in-flight step checkpoint
also checks the session budget (default 35 min), warns in the last 5 minutes,
and exits 3 once it is spent, after recording the step (#7194). A gap longer
than the host cap starts a new session, so a stale ledger never blocks.

    tool.py checkpoint TASK STEP [--branch B] [--pr N] [--next TEXT] [--start]  exit 3 = stop now
    tool.py checkpoint TASK --budget [N | --minutes N] exit 3 = wrap up now
    tool.py resume [TASK]                             brief; exit 6 = absent
    tool.py checkpoint TASK --item ID --group G --status S [--note TEXT]

Delivery ledger (#6980): when a user asks for several tasks, issues, or PRs,
record every item with its target PR group and status before implementing,
show the table, and update the item at each milestone (todo, in-progress,
PR #N, merged, blocked: reason). ``resume`` prints the table, so a resumed
session or the parent sees what is left without the transcript.

Resume at (#7293): the brief's first line is exactly one ``Resume at: <next>``;
a step without ``--next`` warns and keeps the last one.

Crash-safe (ShaftHQ/SHAFT_ENGINE#8065): ``--start --workdir PATH`` declares
the work root. ``/tmp`` and ``/dev/shm`` are refused (exit 5) and other volatile
roots ($TMPDIR, tmpfs) warn. Steps also record ``--head`` (or the work root's
git HEAD) and ``--prereq`` checks (``swap``, ``disk:GiB``, ``mem:GiB``) that
``resume`` re-runs. ``tool.py entry`` lists unfinished tasks, newest first,
stale ones marked. A budget stop records a planned-stop row, and ``resume``
names the cause (box restart, host cap, planned stop). ``checkpoint TASK
--verify`` exits 7 when the work root's pushed HEAD has no checkpoint.
A checkpoint also writes ``TASK.handoff.json``. ``resume`` prints SHA, open
step, and verification from that receipt, not from chat.

State: ``$CHAOS_ENGINE_TASKS_DIR`` or ``~/.local/state/chaos-engine/tasks``,
one ``TASK.jsonl`` per task, outside any worktree so it survives cleanup.
Stdlib only.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess  # nosec B404 - fixed git argv only.
import sys
import time
from pathlib import Path

NAME_RE = re.compile(r"^[A-Za-z0-9_.-]{1,96}$")
DEFAULT_BUDGET_MINUTES = 35
BUDGET_WARN_MINUTES = 5
HOST_CAP_MINUTES = 50
# L80: per-task kind overrides (explicit --minutes/--budget still wins).
KIND_BUDGET_MINUTES = {
    "test-run": 90.0,
    "testrun": 90.0,
    "test_run": 90.0,
}

# Evidence that the task is a real test run (not a budget-bypass label).
# Strip leading env assignments / cd && chains, then require a runner at argv[0].
TEST_RUN_LEAD_RE = re.compile(
    r"(?i)^(?:(?:[A-Za-z_][A-Za-z0-9_]*=\S*\s+)|(?:cd\s+\S+\s*(?:&&|;)\s*))*"
)
TEST_RUN_REJECT_RE = re.compile(
    r"(?i)^(?:echo|printf|true|false|cat|:|#)"
)
TEST_RUN_CMD_RE = re.compile(
    r"(?i)^(?:"
    r"(?:\./)?gradlew?\s+(?:\S+\s+)*test\b|"
    r"mvnw?(?:\s+\S+)*\s+test\b|"
    r"pytest\b|"
    r"python(?:3)?\s+-m\s+(?:pytest|unittest)\b|"
    r"npm(?:\s+run)?\s+test\b|"
    r"cargo\s+test\b|"
    r"go\s+test\b"
    r")"
)
TEST_RUN_ABUSE_CLASSES = frozenset({
    "cleanup", "pr", "design", "docs", "review", "chore", "release",
})
MISSING_NEXT = "(missing: rerun checkpoint with --next \"<exact next step>\")"
STOP_NOW = "stop: push WIP, checkpoint --next, end turn"
OWNER_FINISH_CONTINUE = (
    "owner finish-delivery goal active; checkpoint budget warning only (#7424)"
)
OWNER_FINISH_ENV = "CHAOS_ENGINE_OWNER_FINISH_GOAL"
OWNER_FINISH_STATE = "owner-finish-goal.json"
DONE = "done"
# #8065: work roots a reboot wipes. Refused outright; other volatile roots only warn.
REFUSED_VOLATILE_ROOTS = ("/tmp", "/dev/shm")
VOLATILE_FS_TYPES = frozenset({"tmpfs", "ramfs"})
STALE_DAYS_ENV = "CHAOS_ENGINE_RESUME_STALE_DAYS"
DEFAULT_STALE_DAYS = 7
BOOT_TIME_ENV = "CHAOS_ENGINE_BOOT_TIME"
PLANNED_STOP = "planned-stop"
EXIT_VOLATILE = 5
EXIT_UNCHECKPOINTED = 7


def tasks_root() -> Path:
    override = os.environ.get("CHAOS_ENGINE_TASKS_DIR")
    if override:
        return Path(override)
    base = os.environ.get("XDG_STATE_HOME") or str(Path.home() / ".local" / "state")
    return Path(base) / "chaos-engine" / "tasks"


def ledger(name: str) -> Path:
    if not NAME_RE.match(name):
        raise ValueError(f"invalid task name: {name!r}")
    return tasks_root() / f"{name}.jsonl"


def entries(name: str) -> list[dict]:
    path = ledger(name)
    if not path.is_file():
        return []
    rows = []
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return rows


def record(name: str, step: str, *, branch: str = "", pr: str = "", next_action: str = "",
           start: bool = False, now: float | None = None, spec: str = "", kind: str = "",
           workdir: str = "", head: str = "", prereqs: list[str] | None = None) -> dict:
    row = {"t": round(now if now is not None else time.time()), "step": step}
    for key, value in (("branch", branch), ("pr", pr), ("next", next_action), ("spec", spec), ("kind", kind),
                       ("workdir", workdir), ("head", head)):
        if value:
            row[key] = value
    if prereqs:
        row["prereq"] = list(prereqs)
    if start:
        row["start"] = True
    path = ledger(name)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(row, separators=(",", ":")) + "\n")
    return row


ITEM_STATUSES = ("todo", "in-progress", "pr", "merged", "blocked", "skipped")


def record_item(name: str, item: str, *, group: str = "", status: str = "todo", note: str = "",
                now: float | None = None) -> dict:
    head = status.split(" ", 1)[0].split(":", 1)[0].casefold()
    if head not in ITEM_STATUSES:
        raise ValueError(f"status must start with one of: {', '.join(ITEM_STATUSES)}")
    if head == "blocked" and not note and ":" not in status:
        raise ValueError("blocked needs a reason: --status 'blocked: why' or --note")
    row = {"t": round(now if now is not None else time.time()), "item": item, "status": status}
    if group:
        row["group"] = group
    if note:
        row["note"] = note
    path = ledger(name)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(row, separators=(",", ":")) + "\n")
    return row


def items(name: str) -> dict[str, dict]:
    """Latest row per delivery item, in first-recorded order."""
    latest: dict[str, dict] = {}
    for row in entries(name):
        if "item" in row:
            merged = {**latest.get(row["item"], {}), **row}
            latest[row["item"]] = merged
    return latest


DOING_CAP = 1
BRANCH_CAP = 1
OPEN_PR_CAP = 1
_DONE_STATUSES = frozenset({"merged", "done", "skipped"})
_DOING_STATUSES = frozenset({"in-progress", "doing"})
_OPEN_PR_STATUSES = frozenset({"pr", "review", "in-progress", "doing"})


def _status_head(row: dict) -> str:
    raw = str(row.get("status") or row.get("column") or "")
    return raw.split(":", 1)[0].strip().casefold()


def _ledger_rows(document: object) -> list:
    if isinstance(document, dict):
        rows = document.get("items")
        if rows is None:
            rows = document.get("cards")
        return list(rows or [])
    if isinstance(document, list):
        return document
    return []


def ledger_wip(document: object) -> dict:
    """Read a delivery-ledger JSON object or item list and report WIP counts.

    ``items`` is the count of doing rows, not the size of the whole ledger.
    """
    doing = 0
    branches: set[str] = set()
    prs: set[str] = set()
    for row in _ledger_rows(document):
        if not isinstance(row, dict):
            continue
        status = _status_head(row)
        if status in _DOING_STATUSES:
            doing += 1
        branch = str(row.get("branch") or "").strip()
        if branch and status not in _DONE_STATUSES:
            branches.add(branch)
        pr = str(row.get("pr") or "").strip()
        if pr and status in _OPEN_PR_STATUSES:
            prs.add(pr)
    return {"items": doing, "branches": len(branches), "openPrs": len(prs)}


def wip_gate(*, doing: int, branches: int, open_prs: int, waiver: str = "") -> dict:
    """Fail closed over the per-stream caps.

    ``waiver`` stays in the signature so older callers still run. No string
    lifts the cap, including a token that used to be printed on the
    always-loaded card.
    """
    ignored = waiver
    reasons: list[str] = []
    if doing > DOING_CAP:
        reasons.append("wip-doing-cap")
    if branches > BRANCH_CAP:
        reasons.append("wip-branch-cap")
    if open_prs > OPEN_PR_CAP:
        reasons.append("wip-open-pr-cap")
    return {"ok": not reasons, "reasons": reasons, "waiverAccepted": bool(ignored) and False}


def wip_from_ledger(document: object, *, waiver: str = "") -> dict:
    """Machine-checked WIP view plus the fail-closed gate."""
    counts = ledger_wip(document)
    gate = wip_gate(
        doing=counts["items"],
        branches=counts["branches"],
        open_prs=counts["openPrs"],
        waiver=waiver,
    )
    return {**counts, **gate}


def _seconds(value: object) -> int | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or value < 0:
        return None
    return int(value)


def _span(end: int | None, start: int | None) -> int | str:
    if end is None or start is None or end < start:
        return "unmeasured"
    return end - start


def flow_times(item: object) -> dict:
    """Lead is finish minus create. Queue is start minus create. Blocked is recorded."""
    row = item if isinstance(item, dict) else {}
    created = _seconds(row.get("createdAt", row.get("created_at")))
    started = _seconds(row.get("startedAt", row.get("started_at")))
    finished = _seconds(row.get("finishedAt", row.get("finished_at")))
    blocked = _seconds(row.get("blockedTimeSeconds", row.get("blocked_seconds")))
    return {
        "leadTimeSeconds": _span(finished, created),
        "blockedTimeSeconds": blocked if blocked is not None else "unmeasured",
        "queueTimeSeconds": _span(started, created),
    }


def defect_ratchet(document: object) -> dict:
    """A repeated defect type blocks the next item until a preventive check id exists."""
    rows = _ledger_rows(document)
    counts: dict[str, int] = {}
    checks: dict[str, str] = {}
    for row in rows:
        if not isinstance(row, dict):
            continue
        kind = str(row.get("defect_type") or row.get("defectType") or "").strip()
        if not kind:
            continue
        counts[kind] = counts.get(kind, 0) + 1
        check = row.get("preventive_check") or row.get("preventiveCheck")
        if str(check or "").strip():
            checks[kind] = str(check).strip()
    if isinstance(document, dict):
        extra = document.get("preventive_checks") or document.get("preventiveChecks") or {}
        if isinstance(extra, dict):
            for kind, check in extra.items():
                if str(check or "").strip():
                    checks[str(kind)] = str(check).strip()
    blocked = [kind for kind, count in sorted(counts.items()) if count >= 2 and kind not in checks]
    return {
        "ok": not blocked,
        "blocked": blocked,
        "reasons": [f"repeated-defect:{kind}" for kind in blocked],
    }


def items_table(name: str) -> str:
    rows = items(name)
    if not rows:
        return ""
    lines = ["| Item | Group | Status |", "|---|---|---|"]
    for item, row in rows.items():
        status = row["status"] + (f" ({row['note']})" if row.get("note") else "")
        lines.append(f"| {item} | {row.get('group', '')} | {status} |")
    return "\n".join(lines)


def session_start(rows: list[dict]) -> float | None:
    """Latest `--start` row, or the first row after a gap longer than the host cap (a dead session)."""
    rows = [row for row in rows if "t" in row]
    for index in range(len(rows) - 1, -1, -1):
        row = rows[index]
        gap = index > 0 and row["t"] - rows[index - 1]["t"] > HOST_CAP_MINUTES * 60
        if row.get("start") or gap:
            return float(row["t"])
    return float(rows[0]["t"]) if rows else None



def kind_budget_minutes(kind: str | None) -> float | None:
    """L80: return override minutes for a task kind, or None for default."""
    if not kind:
        return None
    return KIND_BUDGET_MINUTES.get(str(kind).strip().casefold())


def test_run_cmd_matches(cmd: str | None) -> bool:
    """True when *cmd* is an argv-shaped test-runner at the command position.

    Allows leading ``ENV=val`` and ``cd dir &&`` prefixes. Rejects ``echo`` /
    ``printf`` / ``true`` / comments that merely mention a runner name.
    """
    if not cmd:
        return False
    rest = TEST_RUN_LEAD_RE.sub("", str(cmd).strip()).lstrip()
    if not rest or TEST_RUN_REJECT_RE.match(rest):
        return False
    return TEST_RUN_CMD_RE.match(rest) is not None


def test_run_proof_ok(
    *,
    task_cmd: str | None = None,
    command: str | None = None,
    cmd: str | None = None,
    ledger_has_test_cmd: bool = False,
    test_run_proof: bool = False,
    suite_id: str | None = None,
) -> bool:
    """L80: 90-minute test-run budget requires a recorded test-runner command.

    Boolean flags (``ledger_has_test_cmd``, ``test_run_proof``, ``suite_id``)
    never grant 90 alone — a matching cmd string is mandatory.
    """
    del ledger_has_test_cmd, test_run_proof, suite_id  # flags alone are not proof
    return bool(
        test_run_cmd_matches(task_cmd)
        or test_run_cmd_matches(command)
        or test_run_cmd_matches(cmd)
    )


def evaluate_test_run_kind(obs: dict | None) -> dict:
    """Fail-closed policy for kind=test-run budget claims."""
    if obs is None or not isinstance(obs, dict):
        return {"ok": False, "hits": ["missing-input"], "error": "obs required"}
    hits: list[str] = []
    kind = str(obs.get("kind") or "").strip().casefold()
    if kind not in KIND_BUDGET_MINUTES:
        return {"ok": True, "hits": [], "error": None}
    task_class = str(obs.get("task_class") or obs.get("class") or "").strip().casefold()
    if task_class in TEST_RUN_ABUSE_CLASSES:
        hits.append("test-run-kind-abuse")
    if not test_run_proof_ok(
        task_cmd=obs.get("task_cmd") or obs.get("command") or obs.get("cmd"),
        ledger_has_test_cmd=bool(obs.get("ledger_has_test_cmd")),
        test_run_proof=bool(obs.get("test_run_proof")),
        suite_id=obs.get("suite_id"),
    ):
        hits.append("test-run-missing-proof")
    return {
        "ok": not hits,
        "hits": hits,
        "error": None if not hits else "L80 test-run budget gate failed",
    }


def resolve_budget_minutes(
    *,
    kind: str | None = None,
    minutes: float | None = None,
    explicit: bool = False,
    task_cmd: str | None = None,
    command: str | None = None,
    cmd: str | None = None,
    ledger_has_test_cmd: bool = False,
    test_run_proof: bool = False,
    suite_id: str | None = None,
    task_class: str | None = None,
) -> float:
    """Pick session budget: explicit minutes win; else kind override; else 35.

    *explicit* is True when the caller passed ``--minutes`` / ``--budget`` with
    a non-default value, or any ``--budget N``.

    L80: ``kind=test-run`` only yields 90 minutes when test-runner proof is
    present (task cmd matches mvn/gradle/pytest/… or ledger-recorded proof).
    Abuse classes (cleanup/pr/design/…) always keep the default 35.
    """
    if explicit and minutes is not None:
        return float(minutes)
    override = kind_budget_minutes(kind)
    if override is not None:
        abuse = str(task_class or "").strip().casefold() in TEST_RUN_ABUSE_CLASSES
        proof = test_run_proof_ok(
            task_cmd=task_cmd,
            command=command,
            cmd=cmd,
            ledger_has_test_cmd=ledger_has_test_cmd,
            test_run_proof=test_run_proof,
            suite_id=suite_id,
        )
        if abuse or not proof:
            return float(DEFAULT_BUDGET_MINUTES)
        return float(override)
    if minutes is not None:
        return float(minutes)
    return float(DEFAULT_BUDGET_MINUTES)


def ledger_kind(name: str) -> str | None:
    """Most recent ``kind`` recorded on the task ledger, if any."""
    for row in reversed(entries(name)):
        kind = row.get("kind")
        if kind:
            return str(kind)
    return None


def over_budget(name: str, minutes: float, now: float | None = None) -> tuple[bool, float]:
    started = session_start(entries(name))
    if started is None:
        return False, 0.0
    elapsed = max(0.0, ((now if now is not None else time.time()) - started) / 60)
    return elapsed >= minutes, elapsed


def _handoff():
    """Load the handoff writer by path so a spec-loaded ledger still finds it."""
    import importlib.util

    name = "chaos_engine_handoff_receipt"
    module = sys.modules.get(name)
    if module is not None:
        return module
    path = Path(__file__).resolve().parent / "handoff_receipt.py"
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise ImportError(f"handoff receipt missing: {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def _save_handoff(name: str) -> None:
    """Write the one handoff object from ledger fields. A newer file is left untouched."""
    module = _handoff()
    merged: dict = {}
    for row in entries(name):
        if "step" in row:
            merged.update(row)
    payload = module.from_step(
        task=name,
        head=str(merged.get("head") or "unknown"),
        branch=str(merged.get("branch") or ""),
        pr=str(merged.get("pr") or ""),
        next_step=str(merged.get("next") or "unknown"),
    )
    try:
        module.write(tasks_root(), name, payload)
    except module.NewerReceiptError:
        print(f"{name}: newer handoff left untouched", file=sys.stderr)


def _handoff_brief(name: str) -> str:
    module = _handoff()
    receipt = module.read(tasks_root(), name)
    if not receipt:
        return ""
    return module.resume_from_receipt(receipt).rstrip("\n")


def collapse_planned_stops(rows: list[dict]) -> list[dict]:
    """One row per planned stop. The same reason with no later step is one stop."""
    out: list[dict] = []
    for row in rows:
        if (
            PLANNED_STOP in row
            and "step" not in row
            and out
            and PLANNED_STOP in out[-1]
            and "step" not in out[-1]
            and out[-1].get(PLANNED_STOP) == row.get(PLANNED_STOP)
        ):
            continue
        out.append(row)
    return out


def _rewrite_ledger(name: str, rows: list[dict]) -> None:
    path = ledger(name)
    path.parent.mkdir(parents=True, exist_ok=True)
    text = "".join(json.dumps(row, separators=(",", ":")) + "\n" for row in rows)
    path.write_text(text, encoding="utf-8")


def resume_rows(name: str) -> list[dict]:
    """Rows resume shows. Duplicate planned-stop rows collapse to one."""
    rows = entries(name)
    collapsed = collapse_planned_stops(rows)
    if collapsed != rows:
        _rewrite_ledger(name, collapsed)
    return collapsed


def _skipped_prereqs(rows: list[dict]) -> set[str]:
    """Prereq names already recorded as skipped. Resume must not re-add them."""
    found: set[str] = set()
    for row in rows:
        skipped = row.get("skipped")
        if skipped is True and row.get("step"):
            found.add(str(row["step"]).strip().casefold())
        elif isinstance(skipped, list):
            found.update(str(item).split(":", 1)[0].strip().casefold() for item in skipped)
        status = str(row.get("status") or "")
        if status.split(":", 1)[0].strip().casefold() != "skipped":
            continue
        if row.get("item"):
            found.add(str(row["item"]).strip().casefold())
        if row.get("step"):
            found.add(str(row["step"]).strip().casefold())
    return found


def brief(name: str) -> str | None:
    rows = resume_rows(name)
    receipt = _handoff_brief(name)
    if not rows:
        return receipt or None
    table = items_table(name)
    skipped_prereqs = _skipped_prereqs(rows)
    rows = [row for row in rows if "step" in row]
    if not rows:
        return (table + "\n" + receipt) if table and receipt else (table or receipt or None)
    merged: dict = {}
    for row in rows:
        merged.update({k: v for k, v in row.items() if k not in {"start"}})
    sessions = sum(1 for row in rows if row.get("start")) or 1
    when = time.strftime("%Y-%m-%d %H:%M", time.localtime(merged["t"]))
    parts = [f"{name}: last step {merged['step']!r} at {when}", f"session {sessions}"]
    parts += [f"{key} {merged[key]}" for key in ("branch", "pr", "head", "workdir") if key in merged]
    text = "; ".join(parts)
    if merged["step"] == DONE:
        text += "\nstatus: done; nothing to resume"
        text += "\n" + table if table else ""
        return text + ("\n" + receipt if receipt else "")
    # #8065: why the last session ended, and the environment to re-check first.
    cause = stop_cause(entries(name))
    if cause:
        text += "\n" + cause
    for prereq in merged.get("prereq") or []:
        key = prereq.split(":", 1)[0].strip().casefold()
        if key in skipped_prereqs:
            text += f"\nprereq skipped: {key} (recorded skip kept)"
            continue
        ok, message = check_prereq(prereq)
        text += f"\nprereq {'ok' if ok else 'FAIL'}: {message}"
    # #7293: exactly one exact next step, first, so a resumed session never rereads history.
    resume_at = merged.get("next") or MISSING_NEXT
    body = f"Resume at: {resume_at}\n{text}" + ("\n" + table if table else "")
    return body + ("\n" + receipt if receipt else "")


# --- #8065 crash-safe helpers -------------------------------------------------

def _under(path: str, root: str) -> bool:
    path, root = os.path.normpath(path), os.path.normpath(root)
    return path == root or path.startswith(root.rstrip(os.sep) + os.sep)


def _mount_fs_type(path: str, mounts_file: str = "/proc/mounts") -> str:
    """Filesystem type of the longest mount point containing *path* ('' when unknown)."""
    try:
        lines = Path(mounts_file).read_text(encoding="utf-8").splitlines()
    except OSError:
        return ""
    best, fs_type = "", ""
    for line in lines:
        parts = line.split()
        if len(parts) < 3:
            continue
        point = parts[1].replace("\\040", " ")
        if _under(path, point) and len(point) > len(best):
            best, fs_type = point, parts[2]
    return fs_type


def volatile_reason(path: str | os.PathLike, *, mounts_file: str = "/proc/mounts") -> tuple[str, bool]:
    """('', False) for a durable path; else (reason, refused). Refused = /tmp or /dev/shm."""
    resolved = os.path.realpath(os.path.expanduser(str(path)))
    for root in REFUSED_VOLATILE_ROOTS:
        if _under(resolved, root) or _under(os.path.normpath(os.path.abspath(str(path))), root):
            return f"{path} is under {root}, which a restart wipes", True
    tmpdir = os.environ.get("TMPDIR")
    if tmpdir and _under(resolved, os.path.realpath(tmpdir)):
        return f"{path} is under $TMPDIR ({tmpdir}), which may be wiped", False
    fs_type = _mount_fs_type(resolved, mounts_file)
    if fs_type in VOLATILE_FS_TYPES:
        return f"{path} is on {fs_type}, which a restart wipes", False
    return "", False


def git_head(workdir: str) -> str:
    """HEAD of *workdir* when it is a git checkout, else ''."""
    if not workdir or not Path(workdir).is_dir():
        return ""
    try:
        out = subprocess.run(  # nosec B603 B607 - fixed argv.
            ["git", "-C", workdir, "rev-parse", "HEAD"], capture_output=True, text=True, timeout=10,
        )
    except (OSError, subprocess.SubprocessError):
        return ""
    return out.stdout.strip() if out.returncode == 0 else ""


def git_pushed_head(workdir: str) -> str:
    """The upstream commit of *workdir*'s branch (what was pushed), else ''."""
    try:
        out = subprocess.run(  # nosec B603 B607 - fixed argv.
            ["git", "-C", workdir, "rev-parse", "@{u}"], capture_output=True, text=True, timeout=10,
        )
    except (OSError, subprocess.SubprocessError):
        return ""
    return out.stdout.strip() if out.returncode == 0 else ""


def check_prereq(spec: str) -> tuple[bool, str]:
    """Re-check one environment prerequisite: swap, disk:GiB (free in work root), mem:GiB."""
    name, _, value = spec.partition(":")
    name = name.strip().casefold()
    if name == "swap":
        try:
            lines = Path("/proc/swaps").read_text(encoding="utf-8").splitlines()[1:]
        except OSError:
            return True, "swap: cannot read /proc/swaps; check by hand"
        return (bool(lines), "swap: on" if lines else "swap: missing; re-add it before resuming")
    if name in {"disk", "mem"}:
        try:
            need = float(value)
        except ValueError:
            return False, f"{spec}: needs a GiB number, for example {name}:2"
        if name == "disk":
            free = shutil.disk_usage(os.environ.get("CHAOS_ENGINE_PREREQ_DISK_PATH") or ".").free / 2**30
        else:
            free = 0.0
            try:
                for line in Path("/proc/meminfo").read_text(encoding="utf-8").splitlines():
                    if line.startswith("MemAvailable:"):
                        free = int(line.split()[1]) / 2**20
            except OSError:
                return True, f"{spec}: cannot read /proc/meminfo; check by hand"
        ok = free >= need
        return ok, f"{name}: {free:.1f} GiB free (need {need:g})" + ("" if ok else "; free some before resuming")
    return False, f"{spec}: unknown prerequisite (use swap, disk:GiB or mem:GiB)"


def boot_time() -> float | None:
    """Host boot time (epoch seconds); `CHAOS_ENGINE_BOOT_TIME` overrides for fixtures."""
    override = os.environ.get(BOOT_TIME_ENV)
    if override:
        try:
            return float(override)
        except ValueError:
            return None
    try:
        for line in Path("/proc/stat").read_text(encoding="utf-8").splitlines():
            if line.startswith("btime "):
                return float(line.split()[1])
    except OSError:
        return None
    return None


def stop_cause(rows: list[dict], now: float | None = None) -> str:
    """One line on why the last session ended, for the resume brief and the owner report."""
    timed = [row for row in rows if "t" in row]
    if not timed:
        return ""
    last = timed[-1]
    if last.get("step") == DONE:
        return ""
    stamp = time.strftime("%H:%M", time.localtime(last["t"]))
    step = next((row["step"] for row in reversed(timed) if "step" in row), "?")
    booted = boot_time()
    if booted is not None and booted > last["t"]:
        when = time.strftime("%Y-%m-%d %H:%M", time.localtime(booted))
        return f"cause: box restarted {when}; last checkpoint {stamp}; resume after step {step!r}"
    if last.get(PLANNED_STOP):
        return f"cause: planned stop ({last[PLANNED_STOP]}) after step {step!r} at {stamp}"
    current = now if now is not None else time.time()
    if current - last["t"] > HOST_CAP_MINUTES * 60:
        return f"cause: session ended without a planned stop (likely the host cap) after step {step!r} at {stamp}"
    return ""


def last_field(rows: list[dict], key: str):
    for row in reversed(rows):
        if row.get(key):
            return row[key]
    return None


def stale_days() -> float:
    try:
        return float(os.environ.get(STALE_DAYS_ENV) or DEFAULT_STALE_DAYS)
    except ValueError:
        return float(DEFAULT_STALE_DAYS)


def unfinished(project: str | os.PathLike | None = None, now: float | None = None) -> list[dict]:
    """Unfinished tasks, newest first. With *project*, only tasks whose work root is inside or contains it."""
    current = now if now is not None else time.time()
    out = []
    for name in open_tasks():
        rows = entries(name)
        timed = [row for row in rows if "t" in row]
        if not timed:
            continue
        workdir = last_field(rows, "workdir") or ""
        if project is not None:
            proj = os.path.realpath(str(project))
            wd = os.path.realpath(workdir) if workdir else ""
            if not wd or not (_under(wd, proj) or _under(proj, wd)):
                continue
        last_t = timed[-1]["t"]
        out.append({
            "task": name,
            "t": last_t,
            "stale": current - last_t > stale_days() * 86400,
            "next": last_field(rows, "next") or MISSING_NEXT,
            "workdir": workdir,
        })
    out.sort(key=lambda row: row["t"], reverse=True)
    return out


def checkpoint_from_delivery(project: str | os.PathLike, step: str) -> dict | None:
    """Record a push or pr step on the newest unfinished task for this work root.

    Hook hosts call this from PostToolUse so a crash after ``git push`` or ``gh pr``
    resumes from that step. No open task means nothing is invented.
    """
    if step not in {"push", "pr"}:
        return None
    rows = unfinished(project)
    if not rows:
        return None
    current = rows[0]
    nxt = current.get("next") or ""
    if not nxt or nxt == MISSING_NEXT:
        nxt = "open or update the pull request" if step == "push" else "wait for review or merge"
    return record(
        current["task"],
        step,
        workdir=current.get("workdir") or str(project),
        head=git_head(current.get("workdir") or str(project)),
        next_action=nxt,
    )


def unfinished_listing(project: str | os.PathLike | None = None, now: float | None = None) -> str:
    """The SessionStart / `tool.py entry` block: one line per unfinished task, newest first."""
    rows = unfinished(project, now)
    if not rows:
        return ""
    lines = ["Unfinished tasks (run `tool.py resume TASK` first; follow its `Resume at:`):"]
    for row in rows:
        when = time.strftime("%Y-%m-%d %H:%M", time.localtime(row["t"]))
        tag = " [stale]" if row["stale"] else ""
        lines.append(f"- {row['task']}{tag} ({when}): Resume at: {row['next']}")
    return "\n".join(lines) + "\n"


def unchecked_push(name: str, workdir: str = "") -> str:
    """'' when the work root's pushed HEAD matches a checkpoint; else a one-line finding."""
    rows = entries(name)
    workdir = workdir or last_field(rows, "workdir") or ""
    if not workdir:
        return f"{name}: no work root recorded; pass --workdir"
    pushed = git_pushed_head(workdir)
    if not pushed:
        return ""
    heads = [row.get("head") for row in rows if row.get("head")]
    if any(pushed.startswith(head) for head in heads if len(head) >= 7):
        return ""
    return (f"{name}: pushed {pushed[:12]} has no checkpoint; run "
            f"`tool.py checkpoint {name} STEP --head {pushed[:12]} --next \"...\"`")


SPEC_REFUSAL = (
    "{task}: no spec; write one before coding (problem, evidence/root cause, retrieved prior art, "
    "plan steps, riskiest assumption + the test that proves it, files touched, out of scope) and pass "
    "`--spec PATH` once, or save it as {default}"
)


def spec_dir() -> Path:
    override = os.environ.get("CHAOS_ENGINE_SPEC_DIR")
    return Path(override) if override else tasks_root() / "specs"


def find_spec(name: str, given: str = "") -> Path | None:
    """The task's spec: --spec, else the last recorded one, else spec-<task>.md in spec_dir()."""
    recorded = [row["spec"] for row in entries(name) if row.get("spec")] if ledger(name).is_file() else []
    for candidate in (given, *reversed(recorded), str(spec_dir() / f"spec-{name}.md")):
        if candidate and Path(candidate).is_file() and Path(candidate).stat().st_size > 0:
            return Path(candidate).resolve()
    return None


def open_tasks() -> list[str]:
    root = tasks_root()
    if not root.is_dir():
        return []
    names = []
    for path in sorted(root.glob("*.jsonl")):
        rows = [row for row in entries(path.stem) if "step" in row]
        if rows and rows[-1].get("step") != DONE:
            names.append(path.stem)
    return names


def checkpoint_step(ns: argparse.Namespace) -> int:
    """Record a step; an in-flight (non-done) step needs a spec on disk first (exit 4)."""
    spec = find_spec(ns.task, ns.spec) if ns.step != DONE else None
    if ns.step != DONE and spec is None:
        print(SPEC_REFUSAL.format(task=ns.task, default=spec_dir() / f"spec-{ns.task}.md"), file=sys.stderr)
        return 4
    kind = getattr(ns, "kind", "") or ""
    workdir = getattr(ns, "workdir", "") or ""
    if workdir:
        reason, refused = volatile_reason(workdir)
        if refused and not getattr(ns, "allow_volatile", False):
            print(f"{ns.task}: refused: {reason}. Keep work under a durable root "
                  "(for example /workspace/<task>/) or pass --allow-volatile.", file=sys.stderr)
            return EXIT_VOLATILE
        if reason:
            print(f"{ns.task}: WARNING: {reason}. Move work to a durable root.", file=sys.stderr)
        workdir = os.path.abspath(os.path.expanduser(workdir))
    if ns.start:
        reason, _ = volatile_reason(tasks_root())
        if reason:
            print(f"{ns.task}: WARNING: the task ledger {reason}; set CHAOS_ENGINE_TASKS_DIR "
                  "or XDG_STATE_HOME to a durable path.", file=sys.stderr)
    head = getattr(ns, "head", "") or git_head(workdir or last_field(entries(ns.task), "workdir") or "")
    record(
        ns.task,
        ns.step,
        branch=ns.branch,
        pr=ns.pr,
        next_action=ns.next_action,
        start=ns.start,
        spec=str(spec) if ns.spec and spec else "",
        kind=kind,
        workdir=workdir,
        head=head if ns.step != DONE else "",
        prereqs=getattr(ns, "prereq", None) or None,
    )
    _save_handoff(ns.task)
    if ns.step != DONE and not ns.next_action:
        print(
            f"{ns.task}: no --next; 'Resume at' keeps the last one. "
            'Pass --next "<exact next step>"',
            file=sys.stderr,
        )
    if ns.step == DONE:
        return 0
    # L80: kind=test-run → 90 min unless --minutes/--budget set explicitly.
    explicit = False
    minutes_arg = float(ns.minutes)
    if ns.budget is not None and ns.budget > 0:
        explicit = True
        minutes_arg = float(ns.budget)
    elif abs(minutes_arg - float(DEFAULT_BUDGET_MINUTES)) > 1e-9:
        explicit = True
    minutes = resolve_budget_minutes(
        kind=kind or ledger_kind(ns.task),
        minutes=minutes_arg,
        explicit=explicit,
    )
    code = session_gate(ns.task, minutes)
    if code == 3:
        planned_stop(ns.task, "budget")
    return code


def planned_stop(name: str, reason: str, now: float | None = None) -> dict:
    """#8065 R4: mark a planned stop at a step boundary; start no new step after this.

    The same reason with no newer step is one row. A second budget check does not append.
    """
    rows = entries(name)
    step_rows = [row for row in rows if "step" in row]
    step = step_rows[-1]["step"] if step_rows else "?"
    nxt = last_field(rows, "next") or MISSING_NEXT
    for row in reversed(rows):
        if "step" in row:
            break
        if row.get(PLANNED_STOP) == reason:
            return row
    row = {"t": round(now if now is not None else time.time()), PLANNED_STOP: reason}
    path = ledger(name)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(row, separators=(",", ":")) + "\n")
    print(f"{name}: planned stop ({reason}) at step {step!r}; next {nxt}. Start no new step.", file=sys.stderr)
    return row


def write_owner_finish_goal(
    project: Path | None = None,
    *,
    active: bool = True,
    source: str = "/goal",
) -> Path:
    """Persist ``.chaos-engine-state/owner-finish-goal.json`` for #7424.

    Called when the owner starts a ``/goal`` finish-delivery session so the
    35-minute checkpoint stop becomes a warning instead of exit 3.
    """
    root = Path(project) if project is not None else Path.cwd()
    path = root / ".chaos-engine-state" / OWNER_FINISH_STATE
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {"active": bool(active), "source": str(source or "/goal")}
    path.write_text(json.dumps(payload, sort_keys=True) + "\n", encoding="utf-8")
    return path


def owner_finish_goal_active(project: Path | None = None) -> bool:
    """True when the owner explicitly asked to finish a named delivery (#7424).

    Marker: env ``CHAOS_ENGINE_OWNER_FINISH_GOAL`` in {1,true,yes}, or
    ``.chaos-engine-state/owner-finish-goal.json`` with ``{"active": true}``.
    Ordinary unattended sessions without that marker still stop at the budget.
    """
    raw = str(__import__("os").environ.get(OWNER_FINISH_ENV, "")).strip().casefold()
    if raw in {"1", "true", "yes", "on"}:
        return True
    root = Path(project) if project is not None else Path.cwd()
    path = root / ".chaos-engine-state" / OWNER_FINISH_STATE
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return False
    return isinstance(payload, dict) and payload.get("active") is True


def session_gate(name: str, minutes: float, now: float | None = None) -> int:
    """Hard stop after the step is recorded: exit 3 past the budget, warn in its last minutes.

    #7424: an explicit owner finish-delivery goal keeps exit 0 past the budget
    (warning only). Sessions without that goal still get exit 3.
    """
    spent, elapsed = over_budget(name, minutes, now)
    if spent:
        if owner_finish_goal_active():
            print(
                f"{name}: {elapsed:.0f}/{minutes:.0f} min; {OWNER_FINISH_CONTINUE}",
                file=sys.stderr,
            )
            return 0
        print(f"{name}: {elapsed:.0f}/{minutes:.0f} min; {STOP_NOW}", file=sys.stderr)
        return 3
    if elapsed >= minutes - BUDGET_WARN_MINUTES:
        print(f"{name}: {elapsed:.0f}/{minutes:.0f} min; finish this step, then stop", file=sys.stderr)
    return 0


def main(argv: list[str] | None = None, command: str = "checkpoint") -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    try:
        if command == "resume":
            if not args:
                names = open_tasks()
                print("\n".join(brief(n) or n for n in names) if names else "no open tasks")
                return 0
            text = brief(args[0])
            if text is None:
                print(f"{args[0]}: no ledger", file=sys.stderr)
                return 6
            print(text)
            return 0
        parser = argparse.ArgumentParser(prog="tool.py checkpoint")
        parser.add_argument("task")
        parser.add_argument("step", nargs="?")
        parser.add_argument("--branch", default="")
        parser.add_argument("--pr", default="")
        parser.add_argument("--next", dest="next_action", default="")
        parser.add_argument("--start", action="store_true", help="mark a new session start")
        parser.add_argument("--spec", default="", help="the task's spec file; required before a non-done step")
        # `--budget 40` and `--budget --minutes 40` both work (#6990).
        parser.add_argument(
            "--budget", nargs="?", const=0.0, default=None, type=float, metavar="MINUTES",
            help="exit 3 once the session budget (MINUTES, default --minutes) is spent",
        )
        parser.add_argument("--minutes", type=float, default=DEFAULT_BUDGET_MINUTES)
        parser.add_argument("--kind", default="", help="task kind (L80: test-run → 90 min budget)")
        parser.add_argument("--item", help="delivery-ledger item (issue/PR/task id)")
        parser.add_argument("--group", default="", help="target PR group for --item")
        parser.add_argument("--status", default="todo", help="todo|in-progress|pr #N|merged|blocked: why")
        parser.add_argument("--note", default="")
        parser.add_argument("--workdir", default="", help="durable work root (#8065; /tmp and /dev/shm refused)")
        parser.add_argument("--allow-volatile", action="store_true", help="accept a volatile --workdir")
        parser.add_argument("--head", default="", help="head SHA (default: the work root's git HEAD)")
        parser.add_argument("--prereq", action="append", default=[],
                            help="re-checked on resume: swap, disk:GiB, mem:GiB (repeatable)")
        parser.add_argument("--verify", action="store_true",
                            help="exit 7 when the work root's pushed HEAD has no checkpoint (#8065 R2)")
        ns = parser.parse_args(args)
        if ns.verify:
            finding = unchecked_push(ns.task, ns.workdir)
            if finding:
                print(finding, file=sys.stderr)
                return EXIT_UNCHECKPOINTED
            print(f"{ns.task}: pushed HEAD has a checkpoint")
            return 0
        if ns.item:
            record_item(ns.task, ns.item, group=ns.group, status=ns.status, note=ns.note)
            print(items_table(ns.task))
            return 0
        if ns.budget is not None:
            if ns.budget > 0:
                ns.minutes = ns.budget
                explicit = True
            else:
                explicit = False
            kind = getattr(ns, "kind", "") or ledger_kind(ns.task)
            ns.minutes = resolve_budget_minutes(
                kind=kind, minutes=float(ns.minutes), explicit=explicit and ns.budget > 0,
            )
            spent, elapsed = over_budget(ns.task, ns.minutes)
            if spent and owner_finish_goal_active():
                print(
                    f"{ns.task}: {elapsed:.0f}/{ns.minutes:.0f} min; {OWNER_FINISH_CONTINUE}"
                )
                return 0
            verdict = STOP_NOW if spent else "ok"
            print(f"{ns.task}: {elapsed:.0f}/{ns.minutes:.0f} min; {verdict}")
            if spent:
                planned_stop(ns.task, "budget")
                _save_handoff(ns.task)
            return 3 if spent else 0
        if not ns.step:
            parser.error("STEP is required unless --budget is given")
        return checkpoint_step(ns)
    except ValueError as error:
        print(str(error), file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
