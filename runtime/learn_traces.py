#!/usr/bin/env python3
"""Portable learn-traces collect + map-reduce-verify (#5784 / #5847).

Collect remains host-agnostic. Map-reduce-verify uses an isolated file
contract (prompts + batch notes) so every host can run /learn without a
Grok TUI workflow. Offline mode fills that contract deterministically for
scripts/tests; hosts may instead write the same files via Task/subagents.
Actions target git-tracked overlay paths only — never ~/.grok/skills.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

SECRET = re.compile(
    r"(?i)(api[_-]?key|token|password|secret|authorization|bearer)\s*[:=]\s*\S+"
)
BEARER = re.compile(r"(?i)\bBearer\s+[A-Za-z0-9._\-]+")
SK_TOKEN = re.compile(r"\b(?:sk|ghp|gho|ghu|ghs|ghr)_[A-Za-z0-9]{8,}\b")


def redact(text: str) -> str:
    out = SECRET.sub(r"\1=<redacted>", text)
    out = BEARER.sub("Bearer <redacted>", out)
    out = SK_TOKEN.sub("<redacted-token>", out)
    return out


def _read_jsonl(path: Path) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    try:
        for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
            if not line.strip():
                continue
            try:
                parsed = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(parsed, dict):
                rows.append(parsed)
    except OSError:
        return []
    return rows


def _read_json_or_jsonl(path: Path) -> list[dict[str, object]]:
    if path.suffix.casefold() == ".jsonl":
        return _read_jsonl(path)
    try:
        payload = json.loads(path.read_text(encoding="utf-8", errors="replace"))
    except (OSError, json.JSONDecodeError):
        return _read_jsonl(path)
    if isinstance(payload, dict):
        for key in ("messages", "items", "events", "turns"):
            value = payload.get(key)
            if isinstance(value, list):
                return [item for item in value if isinstance(item, dict)]
        return [payload]
    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, dict)]
    return []


def _text_blobs(row: dict[str, object]) -> list[str]:
    blobs: list[str] = []
    for key in ("content", "text", "message", "prompt", "input"):
        value = row.get(key)
        if isinstance(value, str):
            blobs.append(value)
        elif isinstance(value, dict):
            for nested in ("content", "text", "role"):
                item = value.get(nested)
                if isinstance(item, str):
                    blobs.append(item)
            content = value.get("content")
            if isinstance(content, list):
                for block in content:
                    if isinstance(block, dict):
                        text = block.get("text")
                        if isinstance(text, str):
                            blobs.append(text)
                    elif isinstance(block, str):
                        blobs.append(block)
        elif isinstance(value, list):
            for block in value:
                if isinstance(block, str):
                    blobs.append(block)
                elif isinstance(block, dict):
                    text = block.get("text")
                    if isinstance(text, str):
                        blobs.append(text)
    return blobs


_TOOL_RESULT_KINDS = frozenset(
    {
        "tool_result",
        "function_call_output",
        "custom_tool_call_output",
        "tool_output",
    }
)


def _payload_text(value: object) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        return "".join(_payload_text(item) for item in value)
    if isinstance(value, dict):
        for key in ("content", "output", "result", "text"):
            if key in value:
                return _payload_text(value[key])
        return ""
    if value is None:
        return ""
    return str(value)


def _block_kind(node: dict[str, object]) -> str:
    return str(node.get("type") or node.get("kind") or "").casefold().replace("-", "_")


def iter_tool_result_blocks(row: dict[str, object]) -> list[dict[str, object]]:
    found: list[dict[str, object]] = []

    def walk(node: object) -> None:
        if isinstance(node, dict):
            kind = _block_kind(node)
            role = str(node.get("role") or "").casefold()
            if kind in _TOOL_RESULT_KINDS or role in {"tool", "tool_result"}:
                found.append(node)
                return
            for value in node.values():
                walk(value)
        elif isinstance(node, list):
            for item in node:
                walk(item)

    walk(row)
    return found


def stamp_tool_result_bytes(rows: list[dict[str, object]]) -> list[int]:
    """Record utf-8 byte size on each tool result. The body is not copied."""
    sizes: list[int] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        for block in iter_tool_result_blocks(row):
            payload = block.get(
                "content", block.get("output", block.get("result", block.get("text")))
            )
            size = len(_payload_text(payload).encode("utf-8"))
            block["resultBytes"] = size
            sizes.append(size)
    return sizes


def _row_role(row: dict[str, object]) -> str:
    for key in ("role", "type", "kind"):
        value = row.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip().casefold()
    message = row.get("message")
    if isinstance(message, dict):
        role = message.get("role")
        if isinstance(role, str):
            return role.strip().casefold()
    return ""


def classify_session(rows: list[dict[str, object]], *, source: str) -> tuple[str, str]:
    """Return (keep|drop, reason)."""
    if not rows:
        return "drop", "empty"
    roles = {_row_role(row) for row in rows}
    text = " ".join(blob for row in rows for blob in _text_blobs(row)).casefold()
    if any(
        marker in text
        for marker in ("isSidechain\": true", "issubagent", "\"subagent\"")
    ) or any("sidechain" in role or "subagent" in role for role in roles):
        # Explicit sidechain flags on rows.
        for row in rows:
            if row.get("isSidechain") is True or row.get("isSubagent") is True:
                return "drop", "subagent"
            if str(row.get("type", "")).casefold() in {"subagent", "sidechain"}:
                return "drop", "subagent"
    for row in rows:
        if row.get("isSidechain") is True or row.get("isSubagent") is True:
            return "drop", "subagent"
        agent = str(row.get("agentId") or row.get("parentSessionId") or "").strip()
        if agent and str(row.get("type", "")).casefold() in {"subagent", "sidechain"}:
            return "drop", "subagent"
    if "synthetic" in roles or any(
        str(row.get("source", "")).casefold() == "synthetic" for row in rows
    ):
        return "drop", "synthetic"
    if any(str(row.get("headless")).casefold() in {"1", "true", "yes"} for row in rows):
        return "drop", "headless"
    humanish = {"user", "human", "prompt", "user_message", "userpromptsubmit"}
    if roles & humanish or any(_row_role(row) == "user" for row in rows):
        return "keep", "human_session"
    # Claude often uses type=user rather than role.
    if any(str(row.get("type", "")).casefold() == "user" for row in rows):
        return "keep", "human_session"
    # Codex rollouts often nest under type=event_msg / payload
    for row in rows:
        payload = row.get("payload")
        if isinstance(payload, dict) and str(payload.get("type", "")).casefold() in {
            "user_message",
            "message",
        }:
            return "keep", "human_session"
        if str(row.get("type", "")).casefold() in {"response_item", "event_msg"}:
            role = ""
            if isinstance(payload, dict):
                role = str(payload.get("role") or payload.get("type") or "").casefold()
            if role in humanish or role == "user_message":
                return "keep", "human_session"
    del source
    return "drop", "no_human_turn"


def session_id_for(path: Path, host: str) -> str:
    stem = path.stem
    safe = re.sub(r"[^A-Za-z0-9._-]+", "_", f"{host}_{stem}")
    return safe[:120] or f"{host}_session"


def _redact_value(value: object) -> object:
    if isinstance(value, str):
        return redact(value)
    if isinstance(value, list):
        return [_redact_value(item) for item in value]
    if isinstance(value, dict):
        return {str(key): _redact_value(item) for key, item in value.items()}
    return value


def redact_rows(rows: list[dict[str, object]]) -> list[dict[str, object]]:
    return [_redact_value(row) for row in rows if isinstance(row, dict)]  # type: ignore[misc]


def iter_session_files(root: Path) -> list[Path]:
    if not root.is_dir():
        return []
    files: list[Path] = []
    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        if path.name.casefold() in {"manifest.json", "config.json"}:
            continue
        if path.suffix.casefold() in {".jsonl", ".json"}:
            # Skip obvious non-session trees.
            parts = {part.casefold() for part in path.parts}
            if parts & {"skills", "plugins", "node_modules", ".git"}:
                continue
            files.append(path)
    return files


def host_roots(home: Path) -> list[tuple[str, Path]]:
    return [
        ("grok", Path(os_environ_home(home, "GROK_HOME", ".grok")) / "sessions"),
        ("claude", Path(os_environ_home(home, "CLAUDE_CONFIG_DIR", ".claude")) / "projects"),
        ("codex", Path(os_environ_home(home, "CODEX_HOME", ".codex")) / "sessions"),
        ("gemini", Path(os_environ_home(home, "GEMINI_HOME", ".gemini")) / "tmp"),
        ("gemini", Path(os_environ_home(home, "GEMINI_HOME", ".gemini")) / "sessions"),
    ]


def os_environ_home(home: Path, env_name: str, default_name: str) -> Path:
    import os

    configured = os.environ.get(env_name)
    if configured:
        return Path(configured)
    # CLAUDE_CONFIG is a file path in mcp_policy; prefer CLAUDE_CONFIG_DIR / .claude dir.
    if env_name == "CLAUDE_CONFIG_DIR":
        return home / ".claude"
    return home / default_name


def collect(home: Path, out: Path) -> dict[str, object]:
    out.mkdir(parents=True, exist_ok=True)
    sessions_dir = out / "sessions"
    sessions_dir.mkdir(exist_ok=True)
    sessions: list[dict[str, object]] = []
    dropped: dict[str, int] = {
        "missing_roots": 0,
        "empty": 0,
        "subagent": 0,
        "synthetic": 0,
        "headless": 0,
        "no_human_turn": 0,
        "unreadable": 0,
    }
    seen_roots: set[Path] = set()
    for host, root in host_roots(home):
        resolved = root
        if resolved in seen_roots:
            continue
        seen_roots.add(resolved)
        if not resolved.is_dir():
            dropped["missing_roots"] += 1
            continue
        for path in iter_session_files(resolved):
            rows = _read_json_or_jsonl(path)
            if not rows:
                dropped["unreadable"] = dropped.get("unreadable", 0) + 1
                continue
            decision, reason = classify_session(rows, source=host)
            if decision != "keep":
                dropped[reason] = dropped.get(reason, 0) + 1
                continue
            tool_result_bytes = stamp_tool_result_bytes(rows)
            sid = session_id_for(path, host)
            payload = {
                "id": sid,
                "host": host,
                "sourcePath": str(path),
                "keptReason": reason,
                "toolResultBytes": tool_result_bytes,
                "messages": redact_rows(rows),
            }
            target = sessions_dir / f"{sid}.json"
            target.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
            # Guard: credentials must not survive redaction in written output.
            written = target.read_text(encoding="utf-8")
            if SECRET.search(written) or BEARER.search(written) or SK_TOKEN.search(written):
                # Re-redact whole file as a belt-and-suspenders pass.
                target.write_text(redact(written), encoding="utf-8")
            sessions.append(
                {
                    "id": sid,
                    "host": host,
                    "path": str(target.relative_to(out)),
                    "sourcePath": str(path),
                }
            )
    manifest = {
        "schemaVersion": 1,
        "createdAt": datetime.now(timezone.utc).isoformat(),
        "home": str(home),
        "sessions_kept": len(sessions),
        "sessions": sessions,
        "dropped": dropped,
        "next": "python3 .chaos-engine/runtime/learn_traces.py learn --out <run-dir> (or prepare/offline/finalize); see references/learn-traces.md",
    }
    (out / "manifest.json").write_text(
        json.dumps(manifest, indent=2) + "\n", encoding="utf-8"
    )
    return manifest




def _empty_pressure() -> dict[str, int]:
    return {
        "tool_results": 0,
        "tool_result_bytes": 0,
        "model_turns": 0,
        "tool_turns": 0,
        "pipe_turns": 0,
        "uncached_tokens": 0,
        "intermediate_uncached_tokens": 0,
        "usage_events": 0,
    }


def _content_blocks(row: dict[str, object]) -> list[dict[str, object]]:
    message = row.get("message")
    content = message.get("content") if isinstance(message, dict) else row.get("content")
    if isinstance(content, list):
        return [block for block in content if isinstance(block, dict)]
    return []


def _add_result_bytes(acc: dict[str, int], block: dict[str, object]) -> None:
    stamped = block.get("resultBytes")
    if isinstance(stamped, int):
        size = stamped
    else:
        payload = block.get("content", block.get("output", block.get("result", block.get("text"))))
        size = len(_payload_text(payload).encode("utf-8"))
    acc["tool_result_bytes"] += size
    acc["tool_results"] += 1


def score_claude_rows(rows: list[dict[str, object]]) -> dict[str, int]:
    """Claude transcripts: input_tokens is the uncached portion of that request."""
    acc = _empty_pressure()
    pending_one = False
    pending_tools = False
    seen: set[object] = set()
    buffer_id: object = None
    buffer_blocks: list[dict[str, object]] = []
    buffer_usage: dict[str, object] | None = None

    def flush() -> None:
        nonlocal buffer_id, buffer_blocks, buffer_usage, pending_one, pending_tools
        if buffer_id is None and not buffer_blocks and buffer_usage is None:
            pending_one = False
            pending_tools = False
            return
        tool_uses = sum(1 for block in buffer_blocks if str(block.get("type")) == "tool_use")
        texts = sum(
            1
            for block in buffer_blocks
            if str(block.get("type")) == "text" and str(block.get("text") or "").strip()
        )
        key = buffer_id if buffer_id is not None else id(buffer_usage)
        if isinstance(buffer_usage, dict) and key not in seen and "input_tokens" in buffer_usage:
            seen.add(key)
            uncached = int(buffer_usage.get("input_tokens") or 0)
            acc["uncached_tokens"] += uncached
            acc["usage_events"] += 1
            if pending_tools:
                acc["intermediate_uncached_tokens"] += uncached
        if tool_uses or texts or buffer_usage is not None:
            acc["model_turns"] += 1
            if tool_uses:
                acc["tool_turns"] += 1
            if pending_one and tool_uses == 1 and texts == 0:
                acc["pipe_turns"] += 1
        buffer_id = None
        buffer_blocks = []
        buffer_usage = None
        pending_one = False
        pending_tools = False

    for row in rows:
        if not isinstance(row, dict) or row.get("isSidechain") is True:
            continue
        kind = str(row.get("type") or "")
        if kind == "assistant":
            message = row.get("message") if isinstance(row.get("message"), dict) else {}
            message_id = message.get("id") if isinstance(message, dict) else None
            if buffer_blocks and message_id != buffer_id:
                flush()
            buffer_id = message_id
            buffer_blocks.extend(_content_blocks(row))
            usage = message.get("usage") if isinstance(message, dict) else None
            if isinstance(usage, dict):
                buffer_usage = usage
            continue
        if buffer_blocks or buffer_usage is not None:
            flush()
        if kind != "user":
            continue
        blocks = _content_blocks(row)
        tool_blocks = [block for block in blocks if str(block.get("type")) == "tool_result"]
        text_blocks = [
            block
            for block in blocks
            if str(block.get("type")) == "text" and str(block.get("text") or "").strip()
        ]
        for block in tool_blocks:
            _add_result_bytes(acc, block)
        pending_tools = bool(tool_blocks) and not text_blocks
        pending_one = len(tool_blocks) == 1 and not text_blocks
    if buffer_blocks or buffer_usage is not None:
        flush()
    return acc


def score_codex_rows(rows: list[dict[str, object]]) -> dict[str, int]:
    """Codex rollouts. Uncached is input_tokens minus cached_input_tokens on last_token_usage."""
    acc = _empty_pressure()
    pending_outputs = 0
    for row in rows:
        if not isinstance(row, dict):
            continue
        payload = row.get("payload") if isinstance(row.get("payload"), dict) else {}
        if not isinstance(payload, dict):
            continue
        kind = str(payload.get("type") or "")
        if kind == "message" and str(payload.get("role") or "").casefold() in {"user", "user_message"}:
            pending_outputs = 0
            acc["model_turns"] += 0
            continue
        if kind == "custom_tool_call_output":
            _add_result_bytes(acc, payload)
            pending_outputs += 1
            continue
        if kind == "custom_tool_call":
            acc["model_turns"] += 1
            acc["tool_turns"] += 1
            if pending_outputs == 1:
                acc["pipe_turns"] += 1
            pending_outputs = 0
            continue
        if kind != "token_count":
            continue
        info = payload.get("info") if isinstance(payload.get("info"), dict) else {}
        last = info.get("last_token_usage") if isinstance(info, dict) else None
        if not isinstance(last, dict) or "input_tokens" not in last:
            continue
        uncached = int(last.get("input_tokens") or 0) - int(last.get("cached_input_tokens") or 0)
        if uncached < 0:
            uncached = 0
        acc["uncached_tokens"] += uncached
        acc["usage_events"] += 1
        if pending_outputs:
            acc["intermediate_uncached_tokens"] += uncached
    return acc


def _merge_pressure(total: dict[str, int], part: dict[str, int]) -> None:
    for key, value in part.items():
        total[key] = total.get(key, 0) + int(value)


def _pressure_report(acc: dict[str, int], *, grok_tool_result_bytes: int, grok_tool_results: int) -> dict[str, object]:
    turns = acc["model_turns"]
    uncached = acc["uncached_tokens"]
    pipe_share = (acc["pipe_turns"] / turns) if turns else None
    intermediate_share = (acc["intermediate_uncached_tokens"] / uncached) if uncached else None
    attributable = acc["usage_events"] > 0 and turns > 0
    if pipe_share is None and intermediate_share is None:
        decision = "incomplete"
    elif (pipe_share is not None and pipe_share < 0.20) or (
        intermediate_share is not None and intermediate_share < 0.25
    ):
        decision = "drop"
    elif pipe_share is None or intermediate_share is None:
        decision = "incomplete"
    else:
        decision = "keep"
    return {
        "measurable": attributable,
        "decision": decision,
        "model_turns": turns,
        "pipe_turns": acc["pipe_turns"],
        "pipe_share": pipe_share,
        "uncached_tokens": uncached,
        "intermediate_uncached_tokens": acc["intermediate_uncached_tokens"],
        "intermediate_share": intermediate_share,
        "tool_results": acc["tool_results"],
        "tool_result_bytes": acc["tool_result_bytes"],
        "grok_tool_results": grok_tool_results,
        "grok_tool_result_bytes": grok_tool_result_bytes,
        "grok_token_share": None,
        "note": (
            "Grok usage.json is per user turn, so tool-result bytes are counted "
            "and are not converted into a share of uncached tokens."
        ),
    }


def code_mode_step0_decision(report: dict[str, object]) -> str:
    decision = report.get("decision")
    return str(decision) if decision in {"keep", "drop", "incomplete"} else "incomplete"


def _grok_tool_bytes(path: Path) -> tuple[int, int]:
    count = 0
    size = 0
    for row in _read_jsonl(path):
        if str(row.get("type") or "") != "tool_result":
            continue
        count += 1
        content = row.get("content")
        size += len(_payload_text(content).encode("utf-8"))
    return count, size


def measure_tool_result_pressure(home: Path) -> dict[str, object]:
    """Score on-disk sessions. Missing sizes or usage leave the share unset."""
    acc = _empty_pressure()
    grok_results = 0
    grok_bytes = 0
    files = 0
    for host, root in host_roots(home):
        if not root.is_dir():
            continue
        paths = (
            sorted(root.rglob("chat_history.jsonl"))
            if host == "grok"
            else [path for path in iter_session_files(root) if path.suffix.casefold() == ".jsonl"]
        )
        for path in paths:
            files += 1
            if host == "grok":
                count, size = _grok_tool_bytes(path)
                grok_results += count
                grok_bytes += size
                continue
            rows = _read_json_or_jsonl(path)
            if not rows:
                continue
            if host == "claude":
                _merge_pressure(acc, score_claude_rows(rows))
            elif host == "codex":
                _merge_pressure(acc, score_codex_rows(rows))
    report = _pressure_report(acc, grok_tool_result_bytes=grok_bytes, grok_tool_results=grok_results)
    report["files"] = files
    report["home"] = str(home)
    return report


def _load_mrv():
    import importlib.util

    path = Path(__file__).resolve().with_name("learn_traces_mrv.py")
    spec = importlib.util.spec_from_file_location("chaos_engine_learn_traces_mrv", path)
    if spec is None or spec.loader is None:
        raise RuntimeError("learn_traces_mrv.py missing")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def prepare(run_dir: Path) -> dict[str, object]:
    return _load_mrv().prepare(run_dir)


def offline_map_reduce_verify(run_dir: Path) -> dict[str, object]:
    return _load_mrv().offline_map_reduce_verify(run_dir)


def finalize(run_dir: Path) -> dict[str, object]:
    return _load_mrv().finalize(run_dir)


def learn(
    run_dir: Path,
    *,
    home: Path | None = None,
    collect_first: bool = True,
    offline: bool = True,
) -> dict[str, object]:
    return _load_mrv().learn(
        run_dir,
        collect_fn=collect,
        home=home,
        collect_first=collect_first,
        offline=offline,
    )


def is_forbidden_target(target: str) -> bool:
    return _load_mrv().is_forbidden_target(target)


def is_git_tracked_overlay_target(target: str) -> bool:
    return _load_mrv().is_git_tracked_overlay_target(target)



def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="learn_traces.py")
    sub = parser.add_subparsers(dest="cmd", required=True)
    collect_p = sub.add_parser("collect", help="collect redacted host sessions")
    collect_p.add_argument("--home", type=Path, default=Path.home())
    collect_p.add_argument("--out", type=Path, required=True)
    prepare_p = sub.add_parser(
        "prepare", help="write map/reduce/verify file layout + prompts"
    )
    prepare_p.add_argument("--run-dir", type=Path, required=True)
    offline_p = sub.add_parser(
        "offline",
        help="deterministic map-reduce-verify fill (scripts/tests; no host TUI)",
    )
    offline_p.add_argument("--run-dir", type=Path, required=True)
    finalize_p = sub.add_parser(
        "finalize", help="fail-closed report.md + actions.json from verify/"
    )
    finalize_p.add_argument("--run-dir", type=Path, required=True)
    learn_p = sub.add_parser(
        "learn",
        help="portable /learn: collect + map-reduce-verify + report (default offline)",
    )
    learn_p.add_argument("--out", type=Path, required=True)
    learn_p.add_argument("--home", type=Path, default=Path.home())
    learn_p.add_argument(
        "--no-collect",
        action="store_true",
        help="reuse existing run-dir manifest/sessions",
    )
    learn_p.add_argument(
        "--host-agents",
        action="store_true",
        help="prepare only; do not run offline map-reduce (await subagents)",
    )
    args = parser.parse_args(argv)
    if args.cmd == "collect":
        manifest = collect(args.home.expanduser(), args.out)
        print(json.dumps({"run_dir": str(args.out), **manifest}))
        return 0
    if args.cmd == "prepare":
        layout = prepare(args.run_dir)
        print(json.dumps({"run_dir": str(args.run_dir), **layout}))
        return 0
    if args.cmd == "offline":
        verdict = offline_map_reduce_verify(args.run_dir)
        print(json.dumps({"run_dir": str(args.run_dir), **verdict}))
        return 0
    if args.cmd == "finalize":
        try:
            actions = finalize(args.run_dir)
        except FileNotFoundError as error:
            print(json.dumps({"ok": False, "error": str(error)}), file=sys.stderr)
            return 2
        print(json.dumps({"run_dir": str(args.run_dir), **actions}))
        return 0
    if args.cmd == "learn":
        result = learn(
            args.out,
            home=args.home.expanduser(),
            collect_first=not args.no_collect,
            offline=not args.host_agents,
        )
        print(json.dumps(result))
        return 0
    return 2


if __name__ == "__main__":
    sys.exit(main())
