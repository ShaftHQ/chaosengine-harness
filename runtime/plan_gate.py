#!/usr/bin/env python3
"""Plan approval gate. Default is advisory. Enforcement needs the owner code."""

from __future__ import annotations

import hashlib
import json
import os
import secrets
import sys
import time
from pathlib import Path

_DIR = str(Path(__file__).resolve().parent)
if _DIR not in sys.path:
    sys.path.insert(0, _DIR)

import plan_model  # noqa: E402
import task_ledger  # noqa: E402

ENFORCE_ENV = "CHAOS_ENGINE_ENFORCE_PLAN_APPROVAL"
CODE_TTL = 1800
CODE_ALPHABET = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"
_ON = frozenset({"1", "true", "yes", "on"})


def enforcement_on(environ: dict | None = None) -> bool:
    env = os.environ if environ is None else environ
    return str(env.get(ENFORCE_ENV) or "").strip().casefold() in _ON


def _store_path() -> Path:
    return task_ledger.tasks_root() / "plan-approve-codes.json"


def _load_codes() -> dict:
    path = _store_path()
    if not path.is_file():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _save_codes(codes: dict) -> None:
    path = _store_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(codes, sort_keys=True), encoding="utf-8")
    path.chmod(0o600)


def _digest(code: str) -> str:
    return hashlib.sha256(code.encode("utf-8")).hexdigest()


def request_approval_code(task: str, revision: int, *, now: float | None = None, ttl: float = CODE_TTL) -> str:
    moment = time.time() if now is None else now
    code = "".join(secrets.choice(CODE_ALPHABET) for _ in range(6))
    codes = _load_codes()
    codes[_digest(code)] = {
        "task": task,
        "revision": int(revision),
        "expires": moment + ttl,
        "used": False,
    }
    _save_codes(codes)
    return code


def consume_approval_code(task: str, revision: int, code: str, *, now: float | None = None) -> str:
    if not str(code or "").strip():
        return "no code"
    moment = time.time() if now is None else now
    codes = _load_codes()
    digest = _digest(code.strip())
    entry = codes.get(digest)
    if not isinstance(entry, dict):
        return "code unknown"
    if entry.get("used"):
        return "code already used"
    if float(entry.get("expires") or 0) < moment:
        return "code expired"
    if entry.get("task") != task or int(entry.get("revision") or -1) != int(revision):
        return "code was issued for a different plan"
    entry["used"] = True
    codes[digest] = entry
    _save_codes(codes)
    return ""


def _denial(task: str) -> str:
    return (
        "Plan approval required before this write. "
        f"Run `tool.py plan approve {task}` after the owner pastes the one-use code "
        f"from `tool.py plan approve {task} --request-code`."
    )


def plan_names() -> list[str]:
    root = task_ledger.tasks_root()
    if not root.is_dir():
        return []
    return sorted(path.name[: -len(".plan.json")] for path in root.glob("*.plan.json"))


def plan_approval_block(
    task: str | None = None,
    *,
    environ: dict | None = None,
    mutation: bool = True,
) -> str | None:
    """Denial string before approval, None after, when enforcement is on."""
    if not mutation or not enforcement_on(environ):
        return None
    names = [task] if task else plan_names()
    for name in names:
        if not name:
            continue
        plan = plan_model.load(name)
        if plan is None:
            continue
        if plan_model.blocks(plan):
            return _denial(name)
    return None


def approve(
    task: str,
    *,
    code: str = "",
    ref: str = "",
    comments: list[dict] | None = None,
    environ: dict | None = None,
    now: float | None = None,
) -> tuple[int, str]:
    plan = plan_model.load(task)
    if plan is None:
        return 6, "no plan"
    if enforcement_on(environ):
        reason = consume_approval_code(task, int(plan["revision"]), code, now=now)
        if reason:
            return 1, reason
    moment = time.time() if now is None else now
    approval = plan["approval"]
    approval["state"] = "approved"
    approval["revision"] = int(plan["revision"])
    approval["by"] = "owner"
    approval["at"] = plan_model._iso(moment)
    if ref:
        approval["ref"] = plan_model.collapse(ref)
    if comments is not None:
        approval["comments"] = comments
    plan_model.save(plan)
    return 0, "approved"


def stop(task: str) -> tuple[int, str]:
    plan = plan_model.load(task)
    if plan is None:
        return 6, "no plan"
    plan["approval"]["state"] = "stopped"
    plan_model.save(plan)
    return 0, "stopped"


def gate(task: str) -> int:
    plan = plan_model.load(task)
    if plan is None:
        return 6
    state = (plan.get("approval") or {}).get("state")
    if state == "stopped":
        return 5
    if plan_model.blocks(plan):
        return 4
    return 0


def evidence_findings(obs: dict) -> list[str]:
    """Fail when a done step with verify has no evidence."""
    plan = _plan_from_obs(obs)
    if not isinstance(plan, dict):
        return []
    found: list[str] = []
    for step in plan.get("steps") or []:
        if not isinstance(step, dict) or step.get("status") != "done" or not step.get("verify"):
            continue
        if str(step.get("note") or "").startswith("no-evidence:"):
            continue
        if step.get("evidence"):
            continue
        found.append(f"plan evidence: step {step.get('id')} is done with verify and no evidence")
    approval = plan.get("approval") if isinstance(plan.get("approval"), dict) else {}
    if approval.get("required") and approval.get("state") == "approved" and not plan.get("walkthrough"):
        found.append("plan evidence: approved plan has no walkthrough")
    return found


def _plan_from_obs(obs: dict) -> dict | None:
    if not isinstance(obs, dict):
        return None
    inline = obs.get("plan")
    if isinstance(inline, dict):
        try:
            return plan_model.normalize(inline)
        except plan_model.PlanError:
            return inline
    task = obs.get("task")
    if task:
        return plan_model.load(str(task))
    path = obs.get("plan_path")
    if path:
        file = Path(str(path))
        if file.is_file():
            try:
                return plan_model.normalize(json.loads(file.read_text(encoding="utf-8")))
            except (OSError, UnicodeError, json.JSONDecodeError, plan_model.PlanError):
                return None
    return None
