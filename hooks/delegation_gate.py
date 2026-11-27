#!/usr/bin/env python3
"""Delegation ladder receipt and the PreToolUse writer gate.

The ladder text lives in the router. This module refuses a writer dispatch
that does not match a receipt for that rule.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
from pathlib import Path

RECEIPT_NAME = ".chaos-engine-state/delegation-receipt.json"
TTL_SECONDS = 2 * 60 * 60
BRIEF_MARKERS = ("goal", "file scope", "preserve", "acceptance", "test command", "stop")
RUNGS = ("free", "ask", "paid", "direct")
EFFORTS = ("low", "medium", "high", "max")
FREE_STATES = ("selected", "unreachable-declined", "too-complex", "not-applicable")
TIERS = ("cheapest", "standard", "premium")

_WRITER_TOOL = re.compile(
    r"^(?:task|agent|spawn_agent|spawn_subagent|invoke_subagent|collaboration\.spawn_agent)$",
    re.IGNORECASE,
)
_SHELL_TOOL = re.compile(
    r"bash|shell|powershell|exec_command|execcommand|run_command|runcommand|run_terminal_command|runterminalcommand",
    re.IGNORECASE,
)
_REVIEW_TYPE = re.compile(r"reviewer", re.IGNORECASE)
_WRITER_TYPE = re.compile(r"implementer|mechanical-helper", re.IGNORECASE)
_FREE_COMMAND = re.compile(
    r"\bopencode\b[^\n]{0,160}\brun\b|\bdispatch\.py\b[^\n]{0,160}\bargv\b",
    re.IGNORECASE,
)
_REVIEW_TEXT = re.compile(r"adversarial review", re.IGNORECASE)
_READ_ONLY = re.compile(r"read-only|do not edit|does not edit", re.IGNORECASE)
_IMPLEMENT = re.compile(r"\bimplement\b", re.IGNORECASE)


def project_root(start: Path) -> Path:
    current = start.resolve()
    for candidate in (current, *current.parents):
        if (candidate / ".chaos-engine").is_dir() or (candidate / "skills" / "chaos-engine" / "SKILL.md").is_file():
            return candidate
    return current


def receipt_path(root: Path) -> Path:
    return root / RECEIPT_NAME


def brief_ok(text: str) -> bool:
    folded = text.casefold()
    return all(marker in folded for marker in BRIEF_MARKERS)


def load_receipt(root: Path, now: float | None = None) -> dict | None:
    path = receipt_path(root)
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(payload, dict):
        return None
    recorded = payload.get("recorded_at")
    if not isinstance(recorded, (int, float)):
        return None
    moment = time.time() if now is None else now
    if moment - float(recorded) > TTL_SECONDS:
        return None
    if payload.get("root") != root.resolve().as_posix():
        return None
    return payload


def validate(payload: dict) -> str | None:
    rung = payload.get("rung")
    effort = payload.get("effort")
    free = payload.get("free")
    why = str(payload.get("why") or "").strip()
    if rung not in RUNGS:
        return "rung must be free, ask, paid, or direct"
    if effort not in EFFORTS:
        return "effort must be low, medium, high, or max"
    if free not in FREE_STATES:
        return "free must be selected, unreachable-declined, too-complex, or not-applicable"
    if not why:
        return "why is required"
    if rung == "free":
        if free != "selected":
            return "a free writer records free=selected"
        if payload.get("mechanical"):
            if effort not in {"medium", "high", "max"}:
                return "a mechanical free writer uses medium, high, or max"
        elif effort not in {"high", "max"}:
            return "a free writer uses high or max"
        if not payload.get("brief_ok"):
            return "the brief is missing goal, file scope, preserve, acceptance, test command, or stop"
    if rung == "paid":
        if free not in {"unreachable-declined", "too-complex"}:
            return "paid fallback records free=unreachable-declined or free=too-complex"
        if effort == "max":
            return "paid effort stops at high"
        if effort != "low" and not payload.get("escalated"):
            return "paid effort starts at low; set escalated only after that effort failed"
        if payload.get("escalated") and not str(payload.get("prior") or "").strip():
            return "escalated paid fallback records the prior failure"
        tier = payload.get("tier") or "cheapest"
        if tier not in TIERS:
            return "tier must be cheapest, standard, or premium"
        if tier != "cheapest" and not payload.get("escalated"):
            return "a higher paid tier requires escalated"
        if not payload.get("brief_ok"):
            return "the brief is missing goal, file scope, preserve, acceptance, test command, or stop"
    if rung in {"ask", "direct"} and free != "not-applicable":
        return "ask and direct record free=not-applicable"
    return None


def _blob(tool_input: object) -> str:
    if isinstance(tool_input, dict):
        return json.dumps(tool_input, ensure_ascii=False)
    return str(tool_input or "")


def _subagent_type(tool_input: object) -> str:
    if not isinstance(tool_input, dict):
        return ""
    for key in ("subagent_type", "subagentType", "agent_type", "agentType"):
        value = tool_input.get(key)
        if isinstance(value, str):
            return value
    return ""


def classify(tool_name: str, tool_input: object, commands: tuple[str, ...]) -> str | None:
    command_text = "\n".join(commands)
    if _FREE_COMMAND.search(command_text) or (
        _SHELL_TOOL.search(tool_name or "") and _FREE_COMMAND.search(_blob(tool_input))
    ):
        return "free-writer"
    if not _WRITER_TOOL.match(tool_name or ""):
        return None
    kind = _subagent_type(tool_input)
    text = _blob(tool_input)
    if _REVIEW_TYPE.search(kind):
        return "review"
    if _WRITER_TYPE.search(kind):
        return "host-writer"
    if _READ_ONLY.search(text):
        return None
    if _REVIEW_TEXT.search(text) and not _IMPLEMENT.search(text):
        return "review"
    if _IMPLEMENT.search(text):
        return "host-writer"
    return None


def writer_block(
    tool_name: str,
    tool_input: object,
    commands: tuple[str, ...],
    cwd: Path,
    now: float | None = None,
) -> str | None:
    kind = classify(tool_name, tool_input, commands)
    if kind is None or kind == "review":
        return None
    root = project_root(cwd)
    receipt = load_receipt(root, now)
    if receipt is None:
        return (
            "delegation ladder: record a receipt before this writer "
            "(python3 .chaos-engine/hooks/delegation_gate.py record)."
        )
    problem = validate(receipt)
    if problem:
        return f"delegation ladder: receipt is not valid ({problem})."
    if kind == "host-writer" and receipt.get("rung") != "paid":
        return "delegation ladder: a host writer is the paid fallback. The receipt rung is not paid."
    if kind == "free-writer" and receipt.get("rung") != "free":
        return "delegation ladder: a free writer needs rung=free."
    if kind == "free-writer":
        command_text = "\n".join(commands) or _blob(tool_input)
        command_text = command_text.casefold()
        if "opencode" in command_text and "run" in command_text:
            allowed = ("--variant high", "--variant max")
            if receipt.get("mechanical"):
                allowed = ("--variant medium", "--variant high", "--variant max")
            if not any(token in command_text for token in allowed):
                return "delegation ladder: free opencode dispatch must pass --variant high or max."
    return None


def _payload_from_args(args: argparse.Namespace, root: Path) -> dict:
    brief_text = ""
    brief = ""
    if args.brief:
        brief_path = Path(args.brief)
        try:
            brief_text = brief_path.read_text(encoding="utf-8")
        except OSError as exc:
            raise SystemExit(f"delegation ladder: cannot read brief ({exc})") from exc
        brief = brief_path.resolve().as_posix()
    if args.rung in {"free", "paid"} and not args.brief:
        raise SystemExit("delegation ladder: --brief is required for free and paid")
    return {
        "rung": args.rung,
        "effort": args.effort,
        "free": args.free,
        "why": args.why,
        "mechanical": bool(args.mechanical),
        "escalated": bool(args.escalated),
        "prior": args.prior or "",
        "tier": args.tier,
        "brief_ok": brief_ok(brief_text) if args.rung in {"free", "paid"} else True,
        "brief": brief,
        "root": root.resolve().as_posix(),
        "recorded_at": time.time(),
    }


def record(args: argparse.Namespace) -> int:
    root = project_root(Path(args.root).resolve())
    try:
        payload = _payload_from_args(args, root)
    except SystemExit as exc:
        print(str(exc), file=sys.stderr)
        return 2
    problem = validate(payload)
    if problem:
        print(f"delegation ladder: {problem}", file=sys.stderr)
        return 2
    path = receipt_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    print(path.as_posix())
    return 0


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Record a delegation-ladder receipt")
    parser.add_argument("command", choices=("record",))
    parser.add_argument("--rung", required=True, choices=RUNGS)
    parser.add_argument("--effort", required=True, choices=EFFORTS)
    parser.add_argument("--free", required=True, choices=FREE_STATES)
    parser.add_argument("--why", required=True)
    parser.add_argument("--brief", default="")
    parser.add_argument("--prior", default="")
    parser.add_argument("--tier", default="cheapest", choices=TIERS)
    parser.add_argument("--mechanical", action="store_true")
    parser.add_argument("--escalated", action="store_true")
    parser.add_argument("--root", default=".")
    return parser


def main(argv: list[str] | None = None) -> int:
    return record(_parser().parse_args(argv))


if __name__ == "__main__":
    raise SystemExit(main())
