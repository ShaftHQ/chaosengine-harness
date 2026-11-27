#!/usr/bin/env python3
"""Delegation ladder receipt and the PreToolUse writer gate.

The ladder text lives in the router. This module refuses a writer dispatch
that does not match a receipt for that rule.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shlex
import subprocess
import sys
import time
from pathlib import Path

RECEIPT_NAME = ".chaos-engine-state/delegation-receipt.json"
REVIEW_ROUNDS_NAME = ".chaos-engine-state/review-rounds.json"
REVIEW_CHAIN_CAP = 2
REVIEW_CAP_LIFT_ENV = "CHAOS_ENGINE_REVIEW_CAP_LIFT"
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
_FREE_COMMAND = re.compile(
    r"\bopencode\b[^\n]{0,160}\brun\b|\bdispatch\.py\b[^\n]{0,160}\bargv\b",
    re.IGNORECASE,
)
_REVIEW_TEXT = re.compile(r"adversarial review", re.IGNORECASE)
_NEGATED_EDIT = re.compile(
    r"\b(?:do not|don't|does not|never)\s+"
    r"(?:implement|edit|fix|change|write|update|add|modify|refactor|create)\b",
    re.IGNORECASE,
)
_EDIT_VERB = re.compile(
    r"\b(?:implement|edit|fix|change|write|update|add|modify|refactor|create)\b",
    re.IGNORECASE,
)
_DIRECT_TOOL = re.compile(
    r"^(?:write|edit|strreplace|multiedit|apply_?patch|notebookedit|search_replace|"
    r"write_file|writefile|write_to_file|writetofile|create_file|createfile|"
    r"edit_file|editfile|replace|replace_string_in_file|replacestringinfile|"
    r"multi_replace_string_in_file|multireplacestringinfile|"
    r"replace_file_content|replacefilecontent|"
    r"multi_replace_file_content|multireplacefilecontent)$",
    re.IGNORECASE,
)
_VARIANT = re.compile(r"--variant(?:=|\s+)(low|medium|high|max)\b", re.IGNORECASE)
_VARIANT_RANK = {"low": 0, "medium": 1, "high": 2, "max": 3}
_REVIEW_SUBJECT = re.compile(r"review-subject:\s*([A-Za-z0-9._/@-]+)", re.IGNORECASE)
_WIN_DRIVE = re.compile(r"^[A-Za-z]:[\\/]")
_ABS_PATH = re.compile(
    r"(?<![A-Za-z0-9])("
    r"/(?:[\w.+@=-]+/)+[\w.+@=-]+"
    r"|[A-Za-z]:(?:\\\\|\\|/)+(?:[\w.+@=-]+(?:\\\\|\\|/))+[\w.+@=-]+"
    r")"
)
_ENV_ASSIGN = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*=")


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
            if effort not in EFFORTS:
                return "a mechanical free writer uses low, medium, high, or max"
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
    review_cap = payload.get("review_cap")
    if review_cap is not None:
        if isinstance(review_cap, bool) or not isinstance(review_cap, int) or review_cap < REVIEW_CHAIN_CAP:
            return f"review_cap must be an integer >= {REVIEW_CHAIN_CAP}"
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


def _unquoted(text: str) -> str:
    """Drop quoted spans so a mention inside a string is not a dispatch."""
    out: list[str] = []
    quote = ""
    for char in text:
        if quote:
            if char == quote:
                quote = ""
            continue
        if char in {"'", '"'}:
            quote = char
            continue
        out.append(char)
    return "".join(out)


def _editing(text: str) -> bool:
    """True when a change verb remains after a negated instruction is removed."""
    return _EDIT_VERB.search(_NEGATED_EDIT.sub(" ", text)) is not None


def _split_statements(text: str) -> list[str]:
    """Split shell command text on unquoted ``&&``, ``||``, ``;``, ``|``, and newlines."""
    parts: list[str] = []
    buf: list[str] = []
    quote = ""
    index = 0
    while index < len(text):
        char = text[index]
        if quote:
            buf.append(char)
            if char == quote and text[index - 1] != "\\":
                quote = ""
            index += 1
            continue
        if char in {"'", '"'}:
            quote = char
            buf.append(char)
            index += 1
            continue
        if text.startswith("&&", index) or text.startswith("||", index):
            parts.append("".join(buf))
            buf = []
            index += 2
            continue
        if char in {";", "|", "\n", "\r"}:
            parts.append("".join(buf))
            buf = []
            index += 1
            continue
        buf.append(char)
        index += 1
    parts.append("".join(buf))
    return [part.strip() for part in parts if part.strip()]


def _is_opencode_help(statement: str) -> bool:
    """True only when the command head is ``opencode`` and that run is help."""
    if "$(" in statement or "`" in statement:
        return False
    if any(mark in statement for mark in (";", "&&", "||")):
        return False
    try:
        parts = shlex.split(statement, posix=True)
    except ValueError:
        parts = statement.split()
    cleaned: list[str] = []
    skip_next = False
    for token in parts:
        if skip_next:
            skip_next = False
            continue
        if token in {">", ">>", "<", "2>", "&>", "1>", "2>>"}:
            skip_next = True
            continue
        if re.match(r"^(?:\d*>&\d+|\d*>>?\S+|<\S+)$", token):
            continue
        cleaned.append(token)
    index = 0
    while index < len(cleaned) and _ENV_ASSIGN.match(cleaned[index]):
        index += 1
    if index >= len(cleaned):
        return False
    head = cleaned[index].rsplit("/", 1)[-1].casefold()
    if head != "opencode":
        return False
    rest = cleaned[index + 1 :]
    for run_idx, tok in enumerate(rest):
        if not tok.startswith("-") and tok.casefold() != "run":
            return False
        if tok.casefold() != "run":
            continue
        tail = rest[run_idx + 1 :]
        return bool(tail) and tail[0] in {"--help", "-h"} and all(
            item in {"--help", "-h"} for item in tail
        )
    return False


def _has_real_free_command(raw_text: str) -> bool:
    """True when at least one unquoted statement is a non-help free-writer dispatch."""
    matched = False
    for statement in _split_statements(raw_text):
        if not _FREE_COMMAND.search(_unquoted(statement)):
            continue
        if _is_opencode_help(statement):
            continue
        matched = True
        break
    return matched


def classify(tool_name: str, tool_input: object, commands: tuple[str, ...]) -> str | None:
    raw_commands = "\n".join(commands)
    command_text = _unquoted(raw_commands)
    if _FREE_COMMAND.search(command_text) and _has_real_free_command(raw_commands):
        return "free-writer"
    if _SHELL_TOOL.search(tool_name or "") and _FREE_COMMAND.search(_unquoted(_blob(tool_input))):
        raw_input = (
            str(tool_input.get("command") or "")
            if isinstance(tool_input, dict) and isinstance(tool_input.get("command"), str)
            else _blob(tool_input)
        )
        if _has_real_free_command(raw_input):
            return "free-writer"
    if _WRITER_TOOL.match(tool_name or ""):
        kind = _subagent_type(tool_input)
        text = _blob(tool_input)
        if _REVIEW_TYPE.search(kind) and not _editing(text):
            return "review"
        if _REVIEW_TEXT.search(text) and not _editing(text):
            return "review"
        if not _editing(text):
            return None
        return "host-writer"
    if _DIRECT_TOOL.match(tool_name or ""):
        return "direct-edit"
    return None


def _brief_text(receipt: dict) -> str:
    path = str(receipt.get("brief") or "")
    if not path:
        return ""
    try:
        return Path(path).read_text(encoding="utf-8")
    except OSError:
        return ""


def _free_problem(receipt: dict, command_text: str) -> str | None:
    brief_path = str(receipt.get("brief") or "")
    brief = _brief_text(receipt)
    if not brief_path or brief_path not in command_text or not brief_ok(brief):
        return "delegation ladder: the free writer command must name the brief file."
    mechanical = bool(receipt.get("mechanical"))
    if mechanical and "mechanical" not in brief.casefold():
        return "delegation ladder: a mechanical receipt needs the word mechanical in the brief."
    found = _VARIANT.findall(command_text)
    variant = found[-1].lower() if found else None
    if variant is None and re.search(r"\bopencode\b", command_text, re.IGNORECASE) and re.search(
        r"\brun\b", command_text, re.IGNORECASE
    ):
        return "delegation ladder: free opencode dispatch must pass --variant high or max."
    if variant is None:
        variant = "high"
    effort = str(receipt.get("effort") or "high")
    floor = effort if (mechanical and effort in {"low", "medium"}) else "high"
    if _VARIANT_RANK[variant] < _VARIANT_RANK[floor]:
        return "delegation ladder: free opencode dispatch must pass --variant high or max."
    return None


def _git_branch(path: Path) -> str:
    env = os.environ.copy()
    env.pop("GIT_DIR", None)
    env.pop("GIT_WORK_TREE", None)
    try:
        completed = subprocess.run(  # nosec B603 B607
            ["git", "-C", os.fspath(path), "symbolic-ref", "--short", "HEAD"],
            check=False,
            capture_output=True,
            text=True,
            timeout=2,
            env=env,
        )
    except (OSError, subprocess.TimeoutExpired):
        return ""
    if completed.returncode != 0:
        return ""
    return completed.stdout.strip()


def _explicit_cwd(tool_input: object) -> Path | None:
    if not isinstance(tool_input, dict):
        return None
    for key in ("cwd", "directory", "dir", "workdir"):
        value = tool_input.get(key)
        if isinstance(value, str) and (value.startswith("/") or _WIN_DRIVE.match(value)):
            path = Path(value)
            if path.is_dir():
                return path
    return None


def review_subject(tool_input: object, cwd: Path) -> str:
    """Branch key for one review chain. The session checkout is not a subject."""
    blob = _blob(tool_input)
    marker = _REVIEW_SUBJECT.search(blob)
    if marker:
        # `.` is a legal subject character; a trailing sentence period is not the key.
        subject = marker.group(1).rstrip(".")
        if subject:
            return subject
    explicit = _explicit_cwd(tool_input)
    if explicit is not None:
        branch = _git_branch(explicit)
        if branch:
            return branch
    root = project_root(cwd).resolve()
    for raw in _ABS_PATH.findall(blob)[:8]:
        path = Path(raw)
        if not path.is_dir() or not (path / ".git").exists():
            continue
        if path.resolve() == root:
            continue
        branch = _git_branch(path)
        if branch:
            return branch
    return "unscoped"


def _review_cap(root: Path, now: float | None = None) -> int:
    """Default 2; explicit owner lift via receipt ``review_cap`` or ``CHAOS_ENGINE_REVIEW_CAP_LIFT``."""
    cap = REVIEW_CHAIN_CAP
    receipt = load_receipt(root, now)
    if receipt is not None:
        lifted = receipt.get("review_cap")
        if isinstance(lifted, int) and not isinstance(lifted, bool) and lifted > cap:
            cap = lifted
    raw_env = os.environ.get(REVIEW_CAP_LIFT_ENV, "").strip()
    if raw_env.isdigit():
        env_cap = int(raw_env)
        if env_cap > cap:
            cap = env_cap
    return cap


def _load_review_subjects(path: Path) -> dict[str, int]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        payload = {}
    subjects = payload.get("subjects") if isinstance(payload, dict) else None
    if not isinstance(subjects, dict):
        return {}
    return {
        str(k): v
        for k, v in subjects.items()
        if isinstance(v, int) and not isinstance(v, bool)
    }


def check_review_chain(tool_input: object, cwd: Path, now: float | None = None) -> str | None:
    """Check the review chain cap without incrementing ``review-rounds.json``."""
    root = project_root(cwd)
    subject = review_subject(tool_input, cwd)
    cap = _review_cap(root, now)
    subjects = _load_review_subjects(root / REVIEW_ROUNDS_NAME)
    used = subjects.get(subject, 0)
    if used >= cap:
        count_label = "two" if cap == 2 else str(cap)
        return (
            "delegation ladder: subject "
            f"{subject} used its {count_label} adversarial reviews. "
            "Name review-subject for a different change. "
            "Close the class in the edit and prove that class with the test. "
            "Do not open another reviewer for a further example."
        )
    return None


def record_review_round(tool_input: object, cwd: Path) -> str | None:
    """Increment ``review-rounds.json`` for the review subject after all PreToolUse gates pass."""
    root = project_root(cwd)
    subject = review_subject(tool_input, cwd)
    path = root / REVIEW_ROUNDS_NAME
    subjects = _load_review_subjects(path)
    subjects[subject] = subjects.get(subject, 0) + 1
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"subjects": subjects}, indent=2) + "\n", encoding="utf-8")
    except OSError:
        return "delegation ladder: cannot record the review round."
    return None


def _review_chain_block(
    tool_input: object,
    cwd: Path,
    *,
    commit: bool = True,
    now: float | None = None,
) -> str | None:
    """Refuse a review past the cap. Count only when ``commit`` is true."""
    denied = check_review_chain(tool_input, cwd, now=now)
    if denied is not None:
        return denied
    if not commit:
        return None
    return record_review_round(tool_input, cwd)


def writer_block(
    tool_name: str,
    tool_input: object,
    commands: tuple[str, ...],
    cwd: Path,
    now: float | None = None,
    *,
    commit_review: bool = True,
    is_subagent: bool = False,
) -> str | None:
    kind = classify(tool_name, tool_input, commands)
    if kind is None:
        return None
    if kind == "review":
        return _review_chain_block(tool_input, cwd, commit=commit_review, now=now)
    root = project_root(cwd)
    receipt = load_receipt(root, now)
    if receipt is None:
        if kind == "direct-edit":
            return "delegation ladder: a direct host edit needs rung=direct."
        return (
            "delegation ladder: record a receipt before this writer "
            "(python3 .chaos-engine/hooks/delegation_gate.py record)."
        )
    problem = validate(receipt)
    if problem:
        return f"delegation ladder: receipt is not valid ({problem})."
    paid_subagent_edit = (
        is_subagent
        and receipt.get("rung") == "paid"
        and bool(receipt.get("brief_ok"))
    )
    if kind == "direct-edit" and receipt.get("rung") != "direct" and not paid_subagent_edit:
        return "delegation ladder: a direct host edit needs rung=direct."
    if kind == "host-writer" and receipt.get("rung") != "paid":
        return "delegation ladder: a host writer is the paid fallback. The receipt rung is not paid."
    if kind == "free-writer" and receipt.get("rung") != "free":
        return "delegation ladder: a free writer needs rung=free."
    if kind == "free-writer":
        command_text = "\n".join(commands) or _blob(tool_input)
        return _free_problem(receipt, command_text)
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
    payload: dict[str, object] = {
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
    if args.review_cap is not None:
        payload["review_cap"] = args.review_cap
    return payload


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
    parser.add_argument("--review-cap", type=int, default=None)
    parser.add_argument("--root", default=".")
    return parser


def main(argv: list[str] | None = None) -> int:
    return record(_parser().parse_args(argv))


if __name__ == "__main__":
    raise SystemExit(main())
