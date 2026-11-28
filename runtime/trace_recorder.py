#!/usr/bin/env python3
"""Opt-in local session trace. Default off. Fail-open.

Set CHAOS_ENGINE_TRACE=1 to append one JSONL file per session under
.chaos-engine-state/traces/. Secrets and client-name tokens are not stored.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
from pathlib import Path
from typing import Any

ENV_NAME = "CHAOS_ENGINE_TRACE"
_ON = frozenset({"1", "true", "yes", "on"})
EXCERPT_LIMIT = 80
TOKEN = re.compile(r"eyJ[A-Za-z0-9_-]{10,}\.eyJ[A-Za-z0-9_-]{10,}")
ASSIGNMENT = re.compile(
    r"(?i)(client_?secret|access_?key|password|api_?key|session_?id)[\"']?\s*[:=]\s*[\"']?"
    r"[A-Za-z0-9._~+/=-]{16,}"
)
_ADVISORY = {"sent": False}


def enabled(environ: dict[str, str] | None = None) -> bool:
    env = os.environ if environ is None else environ
    return str(env.get(ENV_NAME, "")).strip().casefold() in _ON


def reset_advisory() -> None:
    _ADVISORY["sent"] = False


def _redact(text: str, *, denylist: tuple[str, ...] = ()) -> dict[str, str]:
    raw = text or ""
    secret = bool(TOKEN.search(raw) or ASSIGNMENT.search(raw))
    excerpt_source = raw
    for token in denylist:
        if token:
            excerpt_source = re.compile(re.escape(token), re.IGNORECASE).sub("[redacted-client]", excerpt_source)
    if secret:
        excerpt = ""
    else:
        excerpt = excerpt_source[:EXCERPT_LIMIT]
    digest = hashlib.sha256(excerpt_source.encode("utf-8", errors="replace")).hexdigest()
    return {"sha256": digest, "excerpt": excerpt}


def record_event(
    project: Path,
    session_id: str,
    event: dict[str, Any],
    *,
    environ: dict[str, str] | None = None,
    denylist: tuple[str, ...] = (),
) -> dict[str, Any]:
    """Append one span, or no-op when disabled. OSError becomes one advisory."""
    if not enabled(environ):
        return {"recorded": False, "reason": "disabled"}
    safe_id = re.sub(r"[^A-Za-z0-9._-]+", "-", str(session_id or "").strip()) or "session"
    try:
        directory = Path(project) / ".chaos-engine-state" / "traces"
        directory.mkdir(parents=True, exist_ok=True)
        redacted = _redact(str(event.get("text") or ""), denylist=denylist)
        span = {
            "operation": str(event.get("operation") or "execute_tool"),
            "host": str(event.get("host") or ""),
            "tool": str(event.get("tool") or ""),
            "parent": str(event.get("parent") or ""),
            "decision": str(event.get("decision") or ""),
            "rule_id": event.get("rule_id"),
            "exit_code": event.get("exit_code"),
            "duration_s": event.get("duration_s"),
            "input_sha256": redacted["sha256"],
            "input_excerpt": redacted["excerpt"],
        }
        line = json.dumps(span, sort_keys=True) + "\n"
        if _sensitive(str(event.get("text") or "")) and str(event.get("text") or "") in line:
            raise OSError("refusing to write a secret")
        with (directory / f"{safe_id}.jsonl").open("a", encoding="utf-8") as handle:
            handle.write(line)
        return {"recorded": True, "bytes": len(line.encode("utf-8"))}
    except OSError:
        if not _ADVISORY["sent"]:
            _ADVISORY["sent"] = True
            return {"recorded": False, "advisory": "trace recorder failed open"}
        return {"recorded": False, "advisory": None}


def _sensitive(text: str) -> bool:
    return bool(TOKEN.search(text) or ASSIGNMENT.search(text))


def read_trace(project: Path, session_id: str) -> list[dict[str, Any]]:
    safe_id = re.sub(r"[^A-Za-z0-9._-]+", "-", str(session_id or "").strip()) or "session"
    path = Path(project) / ".chaos-engine-state" / "traces" / f"{safe_id}.jsonl"
    if not path.is_file():
        return []
    rows = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        document = json.loads(line)
        if isinstance(document, dict):
            rows.append(document)
    return rows
