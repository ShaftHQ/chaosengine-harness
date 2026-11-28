#!/usr/bin/env python3
"""ce-plan/v1 model. Status lives in task-ledger plan-step rows. No network."""

from __future__ import annotations

import copy
import hashlib
import json
import re
import sys
import time
from pathlib import Path

_DIR = str(Path(__file__).resolve().parent)
if _DIR not in sys.path:
    sys.path.insert(0, _DIR)

import task_ledger  # noqa: E402

SCHEMA = "ce-plan/v1"
MAX_STEPS = 100
TEXT_CAP = 500
STATUSES = ("pending", "in_progress", "done", "failed", "skipped", "blocked")
TERMINAL_STATUSES = frozenset({"done", "failed", "skipped", "blocked"})
EVIDENCE_KINDS = (
    "test",
    "command",
    "diff",
    "commit",
    "pr",
    "ci",
    "screenshot",
    "recording",
    "url",
    "review",
)
FILE_EVIDENCE = frozenset({"test", "command", "diff", "screenshot", "recording"})
CHANGE_EVIDENCE = frozenset({"commit", "pr", "diff"})
ID_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_.-]{0,63}$")
CHECKBOX = re.compile(r"^[-*]\s+\[([ xX])\]\s+(.*)$")
EXIT_LINE = re.compile(r"^exit(?:\s*[:=]\s*|\s+)(\d+)\s*$", re.IGNORECASE)
_THREE = {
    "pending": "pending",
    "in_progress": "inProgress",
    "done": "completed",
    "failed": "pending",
    "skipped": "completed",
    "blocked": "pending",
}
_ACP = {
    "pending": "pending",
    "in_progress": "in_progress",
    "done": "completed",
    "failed": "pending",
    "skipped": "completed",
    "blocked": "pending",
}
HOST_STATUS = {"openbot": _THREE, "codex": _THREE, "acp": _ACP, "claude": _ACP}
_IN_STATUS = {
    "pending": "pending",
    "inprogress": "in_progress",
    "in_progress": "in_progress",
    "in-progress": "in_progress",
    "completed": "done",
    "complete": "done",
    "done": "done",
    "failed": "failed",
    "skipped": "skipped",
    "blocked": "blocked",
}


class PlanError(ValueError):
    def __init__(self, errors: list[str]):
        self.errors = list(errors)
        super().__init__("; ".join(self.errors))


def collapse(text: object, *, cap: int = TEXT_CAP) -> str:
    flat = " ".join(str(text or "").split())
    if len(flat) <= cap:
        return flat
    return flat[:cap]


def plan_path(task: str) -> Path:
    if not task_ledger.NAME_RE.match(task):
        raise PlanError([f"invalid task name: {task!r}"])
    return task_ledger.tasks_root() / f"{task}.plan.json"


def progress(plan: dict) -> tuple[int, int]:
    steps = plan.get("steps") or []
    return sum(1 for step in steps if step.get("status") == "done"), len(steps)


def host_status(status: str, family: str) -> str:
    table = HOST_STATUS.get(family)
    if table is None:
        raise PlanError([f"unknown host family: {family}"])
    mapped = table.get(status)
    if mapped is None:
        raise PlanError([f"unknown status: {status}"])
    return mapped


def _strings(value: object, label: str, errors: list[str]) -> list[str]:
    if value is None:
        return []
    if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
        errors.append(f"{label} must be a list of strings")
        return []
    return [collapse(item) for item in value]


def _canonical_evidence(item: object, step_id: str, errors: list[str]) -> dict | None:
    if not isinstance(item, dict):
        errors.append(f"evidence entry must be an object: {step_id}")
        return None
    kind = str(item.get("kind") or "")
    ref = str(item.get("ref") or "").strip()
    if kind not in EVIDENCE_KINDS:
        errors.append(f"unknown evidence kind: {kind or 'empty'}")
        return None
    if not ref:
        errors.append(f"evidence ref empty: {step_id}")
        return None
    built: dict = {"kind": kind, "ref": ref}
    digest = item.get("sha256")
    if digest:
        if not isinstance(digest, str) or not re.fullmatch(r"[0-9a-f]{64}", digest):
            errors.append(f"evidence sha256 invalid: {step_id}")
        else:
            built["sha256"] = digest
    if "exit" in item and item.get("exit") is not None:
        code = item.get("exit")
        if isinstance(code, bool) or not isinstance(code, int):
            errors.append(f"evidence exit invalid: {step_id}")
        else:
            built["exit"] = code
    summary = collapse(item.get("summary"))
    if summary:
        built["summary"] = summary
    return built


def _canonical_step(raw: dict, index: int, errors: list[str]) -> dict:
    step_id = str(raw.get("id") or f"s{index}")
    if not ID_RE.match(step_id):
        errors.append(f"invalid step id: {step_id!r}")
    title = collapse(raw.get("title"))
    if not title:
        errors.append(f"empty title: {step_id}")
    status = str(raw.get("status") or "pending")
    if status not in STATUSES:
        errors.append(f"unknown status: {status}")
    verify_raw = raw.get("verify") or []
    verify: list[dict] = []
    if not isinstance(verify_raw, list):
        errors.append(f"verify must be a list: {step_id}")
    else:
        for item in verify_raw:
            if not isinstance(item, dict) or not str(item.get("kind") or "").strip() or not str(item.get("spec") or "").strip():
                errors.append(f"verify entry needs kind and spec: {step_id}")
                continue
            verify.append({"kind": collapse(item.get("kind")), "spec": collapse(item.get("spec"))})
    evidence_raw = raw.get("evidence") or []
    evidence: list[dict] = []
    if not isinstance(evidence_raw, list):
        errors.append(f"evidence must be a list: {step_id}")
    else:
        for item in evidence_raw:
            built = _canonical_evidence(item, step_id, errors)
            if built is not None:
                evidence.append(built)
    return {
        "id": step_id,
        "title": title,
        "activeText": collapse(raw.get("activeText")),
        "intent": collapse(raw.get("intent")),
        "tools": _strings(raw.get("tools"), f"tools {step_id}", errors),
        "files": _strings(raw.get("files"), f"files {step_id}", errors),
        "dependsOn": _strings(raw.get("dependsOn"), f"dependsOn {step_id}", errors),
        "verify": verify,
        "status": status if status in STATUSES else "pending",
        "evidence": evidence,
        "note": collapse(raw.get("note")),
    }


def _graph_errors(steps: list[dict]) -> list[str]:
    errors: list[str] = []
    ids = [step["id"] for step in steps]
    seen: set[str] = set()
    for step_id in ids:
        if step_id in seen:
            errors.append(f"duplicate step id: {step_id}")
        seen.add(step_id)
    known = set(ids)
    for step in steps:
        for dep in step["dependsOn"]:
            if dep not in known:
                errors.append(f"dependsOn missing: {dep}")
    graph = {step["id"]: [dep for dep in step["dependsOn"] if dep in known] for step in steps}
    color: dict[str, int] = {}
    cyclic: list[str] = []

    def visit(node: str) -> None:
        color[node] = 1
        for dep in graph.get(node, []):
            state = color.get(dep, 0)
            if state == 0:
                visit(dep)
            elif state == 1:
                cyclic.append(node)
        color[node] = 2

    for step_id in ids:
        if step_id not in color and step_id in graph:
            visit(step_id)
    if cyclic:
        errors.append("dependsOn cycle: " + ", ".join(dict.fromkeys(cyclic)))
    return errors


def normalize(data: dict) -> dict:
    """Canonical plan, or PlanError with one message per defect."""
    if not isinstance(data, dict):
        raise PlanError(["plan must be an object"])
    errors: list[str] = []
    if data.get("schema") != SCHEMA:
        errors.append(f"schema must be {SCHEMA}")
    task = str(data.get("task") or "")
    if not task_ledger.NAME_RE.match(task):
        errors.append(f"invalid task name: {task!r}")
    revision = data.get("revision", 1)
    if isinstance(revision, bool) or not isinstance(revision, int) or revision < 1:
        errors.append("revision must be an integer >= 1")
        revision = 1
    approval_raw = data.get("approval")
    if not isinstance(approval_raw, dict):
        errors.append("approval must be an object")
        approval_raw = {}
    state = str(approval_raw.get("state") or "awaiting")
    if state not in {"awaiting", "approved", "stopped"}:
        errors.append(f"unknown approval state: {state}")
        state = "awaiting"
    approval_revision = approval_raw.get("revision", 0)
    if isinstance(approval_revision, bool) or not isinstance(approval_revision, int) or approval_revision < 0:
        errors.append("approval revision must be an integer >= 0")
        approval_revision = 0
    comments: list[dict] = []
    comments_raw = approval_raw.get("comments") or []
    if not isinstance(comments_raw, list):
        errors.append("approval comments must be a list")
    else:
        for item in comments_raw:
            if not isinstance(item, dict) or not str(item.get("step") or "").strip() or not str(item.get("text") or "").strip():
                errors.append("approval comment needs step and text")
                continue
            comments.append({"step": str(item["step"]), "text": collapse(item.get("text"))})
    steps: list[dict] = []
    steps_raw = data.get("steps")
    if not isinstance(steps_raw, list):
        errors.append("steps must be a list")
    else:
        if len(steps_raw) > MAX_STEPS:
            errors.append(f"too many steps: {len(steps_raw)} > {MAX_STEPS}")
        if not steps_raw:
            errors.append("plan has no steps")
        for index, raw in enumerate(steps_raw, start=1):
            if not isinstance(raw, dict):
                errors.append(f"step must be an object: {index}")
                continue
            steps.append(_canonical_step(raw, index, errors))
    errors.extend(_graph_errors(steps))
    if errors:
        raise PlanError(errors)
    walkthrough = data.get("walkthrough")
    return {
        "schema": SCHEMA,
        "task": task,
        "goal": collapse(data.get("goal")),
        "explanation": collapse(data.get("explanation")),
        "revision": int(revision),
        "approval": {
            "required": bool(approval_raw.get("required")),
            "state": state,
            "revision": int(approval_revision),
            "by": collapse(approval_raw.get("by")),
            "at": str(approval_raw.get("at") or ""),
            "ref": collapse(approval_raw.get("ref")),
            "comments": comments,
        },
        "steps": steps,
        "walkthrough": None if walkthrough is None else str(walkthrough),
    }


def validate(data: dict) -> list[str]:
    try:
        normalize(data)
    except PlanError as exc:
        return list(exc.errors)
    return []


def blank_step(step_id: str, title: str, status: str = "pending") -> dict:
    return {
        "id": step_id,
        "title": collapse(title),
        "activeText": "",
        "intent": "",
        "tools": [],
        "files": [],
        "dependsOn": [],
        "verify": [],
        "status": status,
        "evidence": [],
        "note": "",
    }


def parse_markdown(text: str) -> tuple[str, list[dict]]:
    explanation: list[str] = []
    steps: list[dict] = []
    started = False
    for raw in text.splitlines():
        match = CHECKBOX.match(raw.strip())
        if match:
            started = True
            status = "done" if match.group(1).lower() == "x" else "pending"
            steps.append(blank_step(f"s{len(steps) + 1}", match.group(2), status))
            continue
        if not started and raw.strip():
            explanation.append(raw.strip())
    return collapse(" ".join(explanation)), steps


def _approval_for(required: bool, now: float | None = None) -> dict:
    moment = time.time() if now is None else now
    return {
        "required": required,
        "state": "awaiting" if required else "approved",
        "revision": 0 if required else 1,
        "by": "" if required else "owner",
        "at": "" if required else _iso(moment),
        "ref": "",
        "comments": [],
    }


def fresh_plan(
    task: str,
    steps: list[dict],
    *,
    goal: str = "",
    explanation: str = "",
    triage: str = "",
    now: float | None = None,
) -> dict:
    required = triage.strip().casefold() == "public-contract" or len(steps) >= 3
    return normalize(
        {
            "schema": SCHEMA,
            "task": task,
            "goal": goal,
            "explanation": explanation,
            "revision": 1,
            "approval": _approval_for(required, now),
            "steps": steps,
            "walkthrough": None,
        }
    )


def read_raw(task: str) -> dict | None:
    path = plan_path(task)
    if not path.is_file():
        return None
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise PlanError(["plan must be an object"])
    return payload


def save(plan: dict) -> Path:
    canonical = normalize(plan)
    path = plan_path(canonical["task"])
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".json.tmp")
    temporary.write_text(json.dumps(canonical, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temporary.replace(path)
    return path


def project_status(task: str, plan: dict | None = None) -> dict:
    """Overlay the latest plan-step ledger row onto a copy of the plan."""
    if plan is None:
        plan = read_raw(task)
        if plan is None:
            raise PlanError(["no plan"])
    projected = copy.deepcopy(plan)
    latest: dict[str, dict] = {}
    for row in task_ledger.entries(task):
        if row.get("kind") == "plan-step" and row.get("step"):
            latest[str(row["step"])] = row
    for step in projected.get("steps") or []:
        if not isinstance(step, dict):
            continue
        row = latest.get(str(step.get("id")))
        if not row:
            continue
        if row.get("status") in STATUSES:
            step["status"] = row["status"]
        if isinstance(row.get("evidence"), list):
            step["evidence"] = row["evidence"]
        if "note" in row:
            step["note"] = row["note"]
        if row.get("activeText"):
            step["activeText"] = row["activeText"]
    return projected


def load(task: str) -> dict | None:
    raw = read_raw(task)
    if raw is None:
        return None
    return normalize(project_status(task, raw))


def _append_row(task: str, row: dict) -> None:
    path = task_ledger.ledger(task)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(row, separators=(",", ":")) + "\n")


def _status_row(task: str, step: dict, *, now: float | None = None) -> None:
    row = {
        "t": round(time.time() if now is None else now),
        "step": step["id"],
        "kind": "plan-step",
        "status": step["status"],
        "evidence": step.get("evidence") or [],
        "note": step.get("note") or "",
    }
    if step.get("activeText"):
        row["activeText"] = step["activeText"]
    _append_row(task, row)


def _find(plan: dict, step_id: str) -> dict:
    for step in plan["steps"]:
        if step["id"] == step_id:
            return step
    raise PlanError([f"unknown step: {step_id}"])


def _iso(when: float) -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(when))


def evidence_path(ref: str, root: Path | None = None) -> Path | None:
    if ref.startswith(("http://", "https://")):
        return None
    path = Path(ref)
    if not path.is_absolute():
        path = (root or Path.cwd()) / path
    return path


def _exit_code(payload: bytes) -> int | None:
    lines = [line.strip() for line in payload.decode("utf-8", errors="replace").splitlines() if line.strip()]
    if not lines:
        return None
    match = EXIT_LINE.match(lines[-1])
    return int(match.group(1)) if match else None


def build_evidence(spec: str, root: Path | None = None) -> dict:
    if ":" not in spec:
        raise PlanError([f"evidence must be KIND:REF: {spec}"])
    kind, ref = spec.split(":", 1)
    kind, ref = kind.strip(), ref.strip()
    if kind not in EVIDENCE_KINDS:
        raise PlanError([f"unknown evidence kind: {kind}"])
    if not ref:
        raise PlanError(["evidence ref empty"])
    item: dict = {"kind": kind, "ref": ref}
    if kind not in FILE_EVIDENCE:
        return item
    path = evidence_path(ref, root)
    if path is not None and path.is_file():
        payload = path.read_bytes()
        item["sha256"] = hashlib.sha256(payload).hexdigest()
        code = _exit_code(payload)
        if code is not None:
            item["exit"] = code
    return item


def evidence_mark(item: dict, root: Path | None = None) -> str:
    """missing, changed (sha mismatch), or empty when the recorded file still matches."""
    ref = str(item.get("ref") or "")
    path = evidence_path(ref, root)
    recorded = item.get("sha256")
    kind = item.get("kind")
    if path is None or (not recorded and kind not in FILE_EVIDENCE):
        return ""
    if not path.is_file():
        return "missing" if recorded or kind in FILE_EVIDENCE else ""
    if not recorded:
        return ""
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    if digest != recorded:
        return "changed (sha mismatch)"
    return ""


def _waived(note: str) -> bool:
    return str(note or "").startswith("no-evidence:")


def set_status(
    plan: dict,
    step_id: str,
    status: str,
    *,
    evidence: list[str] | None = None,
    note: str | None = None,
    root: Path | None = None,
    now: float | None = None,
) -> dict:
    if status not in STATUSES:
        raise PlanError([f"unknown status: {status}"])
    step = _find(plan, step_id)
    note_text = collapse(note) if note is not None else str(step.get("note") or "")
    built = [build_evidence(spec, root) for spec in evidence] if evidence else None
    if status == "done" and step.get("verify"):
        has_evidence = bool(built) or bool(step.get("evidence"))
        if not has_evidence and not _waived(note_text):
            raise PlanError([f'step {step_id} needs --evidence or --note "no-evidence: <reason>"'])
    step["status"] = status
    if built is not None:
        step["evidence"] = built
    if note is not None:
        step["note"] = note_text
    _status_row(plan["task"], step, now=now)
    return plan


def on_checkpoint(task: str, step: str, *, status: str = "in_progress", now: float | None = None) -> bool:
    """Record a plan step when its id matches. Other checkpoint steps stay untouched."""
    plan = load(task)
    if plan is None or not any(item["id"] == step for item in plan["steps"]):
        return False
    current = _find(plan, step)
    # shortcut: checkpoint has no evidence slot, so a verify step stays in_progress until plan step --evidence
    if status == "done" and current.get("verify") and not current.get("evidence") and not _waived(current.get("note") or ""):
        status = "in_progress"
    set_status(plan, step, status, now=now)
    save(plan)
    return True


def _bump(plan: dict) -> None:
    plan["revision"] = int(plan["revision"]) + 1
    if plan["approval"].get("required"):
        plan["approval"]["state"] = "awaiting"


def _open(step: dict) -> None:
    if step.get("status") == "done":
        raise PlanError([f"cannot edit a done step: {step['id']}"])


def add_step(plan: dict, title: str, *, after: str = "") -> dict:
    title = collapse(title)
    if not title:
        raise PlanError(["empty title"])
    if len(plan["steps"]) >= MAX_STEPS:
        raise PlanError([f"too many steps: {MAX_STEPS + 1} > {MAX_STEPS}"])
    ids = {step["id"] for step in plan["steps"]}
    number = 1
    while f"s{number}" in ids:
        number += 1
    step = blank_step(f"s{number}", title)
    if after:
        index = next((pos for pos, item in enumerate(plan["steps"]) if item["id"] == after), None)
        if index is None:
            raise PlanError([f"unknown step: {after}"])
        plan["steps"].insert(index + 1, step)
    else:
        plan["steps"].append(step)
    _bump(plan)
    return plan


def remove_step(plan: dict, step_id: str) -> dict:
    step = _find(plan, step_id)
    _open(step)
    if len(plan["steps"]) == 1:
        raise PlanError(["plan has no steps"])
    plan["steps"] = [item for item in plan["steps"] if item["id"] != step_id]
    for item in plan["steps"]:
        item["dependsOn"] = [dep for dep in item["dependsOn"] if dep != step_id]
    _bump(plan)
    return plan


def move_step(plan: dict, step_id: str, after: str) -> dict:
    step = _find(plan, step_id)
    _open(step)
    if after == step_id:
        raise PlanError([f"unknown step: {after}"])
    _find(plan, after)
    order = [item["id"] for item in plan["steps"]]
    rest = [item for item in plan["steps"] if item["id"] != step_id]
    index = next(pos for pos, item in enumerate(rest) if item["id"] == after)
    rest.insert(index + 1, step)
    plan["steps"] = rest
    if [item["id"] for item in rest] == order:
        return plan
    _bump(plan)
    return plan


def retitle_step(plan: dict, step_id: str, title: str) -> dict:
    step = _find(plan, step_id)
    _open(step)
    title = collapse(title)
    if not title:
        raise PlanError(["empty title"])
    if step["title"] == title:
        return plan
    step["title"] = title
    _bump(plan)
    return plan


def blocks(plan: dict) -> bool:
    approval = plan.get("approval") or {}
    if approval.get("state") == "stopped":
        return True
    if not approval.get("required"):
        return False
    return not (
        approval.get("state") == "approved" and int(approval.get("revision") or -1) == int(plan.get("revision") or -2)
    )


def verified_items(plan: dict) -> list[dict]:
    """Handoff verified rows taken from step evidence. No second list."""
    rows = []
    for step in plan.get("steps") or []:
        for item in step.get("evidence") or []:
            row = {
                "command": f"{item.get('kind')}:{item.get('ref')}",
                "howObtained": "measured",
                "step": step.get("id"),
            }
            if "exit" in item:
                row["exit"] = item["exit"]
            rows.append(row)
    return rows


def changes_lines(plan: dict) -> list[str]:
    lines = []
    for step in plan.get("steps") or []:
        for item in step.get("evidence") or []:
            if item.get("kind") in CHANGE_EVIDENCE:
                lines.append(f"{item['kind']}: {item['ref']}")
    return lines


def open_items(plan: dict) -> list[str]:
    lines = []
    for step in plan.get("steps") or []:
        if step.get("status") in {"failed", "blocked", "skipped"}:
            lines.append(f"{step['id']} {step['status']}: {step.get('note') or step['status']}")
    return lines


def _incoming_status(value: object) -> str:
    raw = str(value or "").strip()
    compact = raw.replace(" ", "").replace("_", "").replace("-", "").casefold()
    if compact == "inprogress":
        return "in_progress"
    return _IN_STATUS.get(raw) or _IN_STATUS.get(compact) or ""


def _fold_step(item: dict, index: int, used: set[str]) -> dict | None:
    title = item.get("content") or item.get("subject") or item.get("step") or item.get("title") or item.get("text")
    status = _incoming_status(item.get("status") or "pending")
    if not str(title or "").strip() or not status:
        return None
    raw_id = str(item.get("id") or item.get("taskId") or f"s{index}")
    while not ID_RE.match(raw_id) or raw_id in used:
        index += 1
        raw_id = f"s{index}"
    used.add(raw_id)
    step = blank_step(raw_id, str(title), status)
    step["activeText"] = collapse(item.get("activeForm") or item.get("activeText") or "")
    return step


def fold_tool_call(tool: str, payload: object, steps: list[dict]) -> list[dict] | None:
    """Map one host plan payload onto steps. Unknown shapes return None."""
    if not isinstance(payload, dict):
        return None
    name = tool.strip()
    if name == "TodoWrite" and isinstance(payload.get("todos"), list):
        used: set[str] = set()
        folded = []
        for index, item in enumerate(payload["todos"], start=1):
            if not isinstance(item, dict):
                return None
            step = _fold_step(item, index, used)
            if step is None:
                return None
            folded.append(step)
        return folded or None
    if name == "TaskCreate":
        used = {step["id"] for step in steps}
        step = _fold_step(payload, len(steps) + 1, used)
        if step is None:
            return None
        return [*steps, step]
    if name == "TaskUpdate":
        step_id = str(payload.get("taskId") or payload.get("id") or "")
        if not step_id:
            return None
        if payload.get("deleted") is True:
            return [step for step in steps if step["id"] != step_id] or None
        status = _incoming_status(payload.get("status"))
        if not status:
            return None
        found = False
        updated = []
        for step in steps:
            if step["id"] != step_id:
                updated.append(step)
                continue
            found = True
            copied = copy.deepcopy(step)
            copied["status"] = status
            active = payload.get("activeForm") or payload.get("activeText")
            if active:
                copied["activeText"] = collapse(active)
            updated.append(copied)
        return updated if found else None
    entries = None
    if name == "update_plan" and isinstance(payload.get("plan"), list):
        entries = payload["plan"]
    elif name in {"plan", "session/update"} and payload.get("sessionUpdate", "plan") == "plan":
        entries = payload.get("entries") if isinstance(payload.get("entries"), list) else payload.get("plan")
    if isinstance(entries, list):
        used = set()
        folded = []
        for index, item in enumerate(entries, start=1):
            if not isinstance(item, dict):
                return None
            step = _fold_step(item, index, used)
            if step is None:
                return None
            folded.append(step)
        return folded or None
    return None


def apply_fold(task: str, tool: str, payload: dict) -> bool:
    """Observe-only fold. An unknown payload prints one line and changes nothing."""
    plan = load(task)
    if plan is None:
        print(f"plan fold ignored unknown tool payload: {tool}", file=sys.stderr)
        return False
    folded = fold_tool_call(tool, payload, plan["steps"])
    if folded is None:
        print(f"plan fold ignored unknown tool payload: {tool}", file=sys.stderr)
        return False
    old_structure = [(step["id"], step["title"]) for step in plan["steps"]]
    new_structure = [(step["id"], step["title"]) for step in folded]
    old_status = [(step["id"], step["status"], step.get("activeText") or "") for step in plan["steps"]]
    new_status = [(step["id"], step["status"], step.get("activeText") or "") for step in folded]
    if old_structure != new_structure:
        _bump(plan)
    plan["steps"] = folded
    if old_status != new_status or old_structure != new_structure:
        for step in folded:
            _status_row(task, step)
    save(plan)
    return True


def seed_ledger(plan: dict, *, now: float | None = None) -> None:
    for step in plan["steps"]:
        if step["status"] != "pending" or step.get("evidence"):
            _status_row(plan["task"], step, now=now)
