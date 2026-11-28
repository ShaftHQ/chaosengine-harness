#!/usr/bin/env python3
"""Sample, label, rank, and pin a cohort as a regression task. No model."""

from __future__ import annotations

import random
import re
from typing import Any

VERDICTS = frozenset({"acceptable", "problematic", "uncertain"})
TOKEN = re.compile(r"eyJ[A-Za-z0-9_-]{10,}\.eyJ[A-Za-z0-9_-]{10,}")
ASSIGNMENT = re.compile(
    r"(?i)(client_?secret|access_?key|password|api_?key|session_?id)[\"']?\s*[:=]\s*[\"']?"
    r"[A-Za-z0-9._~+/=-]{16,}"
)


def sample(sessions: list[dict[str, Any]], *, n: int = 30, seed: int = 0, preset: str = "random") -> dict[str, Any]:
    if preset not in {"errors", "long", "denied", "random"}:
        raise ValueError("preset must be errors|long|denied|random")
    if n < 1:
        raise ValueError("n must be >= 1")
    chosen: list[str] = []
    dropped: list[dict[str, str]] = []
    for row in sessions:
        sid = str(row.get("id") or "")
        if not sid:
            dropped.append({"id": "", "reason": "missing-id"})
            continue
        if preset == "errors" and not row.get("error"):
            dropped.append({"id": sid, "reason": "preset"})
            continue
        if preset == "long" and int(row.get("tool_calls") or 0) < 8:
            dropped.append({"id": sid, "reason": "preset"})
            continue
        if preset == "denied" and not row.get("denied"):
            dropped.append({"id": sid, "reason": "preset"})
            continue
        chosen.append(sid)
    ordered = list(chosen)
    random.Random(seed).shuffle(ordered)
    return {"sessions": ordered[:n], "dropped": dropped, "preset": preset, "seed": seed}


def _label_error(sid: str, labels: dict[str, dict[str, Any]]) -> str | None:
    label = labels.get(sid)
    if not isinstance(label, dict):
        return "unlabeled"
    verdict = str(label.get("verdict") or "")
    if verdict not in VERDICTS:
        return "verdict"
    if verdict == "problematic" and not str(label.get("critique") or "").strip():
        return "critique"
    if verdict == "problematic" and not str(label.get("first_failure_span") or "").strip():
        return "first-failure"
    return None


def build_cohort(
    name: str,
    session_ids: list[str],
    labels: dict[str, dict[str, Any]],
    *,
    severity: int,
) -> dict[str, Any]:
    if not isinstance(severity, int) or isinstance(severity, bool) or severity < 1 or severity > 3:
        raise ValueError("severity must be 1, 2, or 3")
    for sid in session_ids:
        reason = _label_error(sid, labels)
        if reason:
            raise ValueError(f"{sid}: {reason}")
    return {"name": name, "sessions": list(session_ids), "severity": severity}


def rank(cohorts: list[dict[str, Any]]) -> list[dict[str, Any]]:
    def score(cohort: dict[str, Any]) -> int:
        return len(cohort.get("sessions") or []) * int(cohort.get("severity") or 0)

    return sorted(cohorts, key=lambda cohort: (-score(cohort), str(cohort.get("name") or "")))


def pin(name: str, evaluator: str, session: dict[str, Any], fixing_pr: str) -> dict[str, Any]:
    """One redacted session plus a code evaluator, as a regression task."""
    blob = str(session)
    if TOKEN.search(blob) or ASSIGNMENT.search(blob):
        raise ValueError("fixture still matches a secret pattern")
    slug = re.sub(r"[^a-z0-9]+", "-", name.casefold()).strip("-") or "cohort"
    return {
        "id": f"reg-cohort-{slug}",
        "set": "regression",
        "source": f"cohort:{name}",
        "evaluator": evaluator,
        "fixture": session,
        "fixing_pr": fixing_pr,
    }
