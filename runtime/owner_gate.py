"""One unverifiable owner gate ends the goal. It does not poll."""

from __future__ import annotations

import json
from pathlib import Path

_ARTIFACTS = (
    "rendered proof",
    "rendered-proof",
    "voice recording",
    "visual sign-off",
    "visual sign off",
    "visually accept",
)


def _norm(text: str) -> str:
    return " ".join((text or "").casefold().replace("-", " ").split())


def _owner_only(blocker: str) -> bool:
    folded = _norm(blocker)
    return any(_norm(name) in folded for name in _ARTIFACTS)


def decide_owner_gate(
    *,
    blocker: str,
    session_can_create: bool,
    only_remaining: bool,
    already_recorded: str = "",
) -> dict[str, object]:
    """Record `blocking: unverifiable` once. The same later continue is not new work.

    The result never asks the owner to sign, approve, or visually accept.
    """
    if session_can_create or not only_remaining or not _owner_only(blocker):
        return {
            "blocking": "",
            "end_goal": False,
            "record": False,
            "new_work": True,
            "ask": "",
            "poll": False,
        }
    same = bool(_norm(blocker)) and _norm(already_recorded) == _norm(blocker)
    return {
        "blocking": "blocking: unverifiable",
        "end_goal": True,
        "record": not same,
        "new_work": False,
        "ask": "",
        "poll": False,
    }


def _recorded_blocker(state_path: Path) -> str:
    try:
        payload = json.loads(state_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, UnicodeError):
        return ""
    if not isinstance(payload, dict):
        return ""
    return str(payload.get("blocker") or "")


def record_unverifiable_gate(state_path: Path, *, issue_id: str, reason: str) -> dict[str, object]:
    """Record `blocking: unverifiable` once for an issue. Does not fabricate sign-off."""
    path = Path(state_path)
    issue = str(issue_id).strip().lstrip("#")
    why = " ".join(str(reason or "").split())
    if not issue or not why:
        return {
            "blocking": "",
            "record": False,
            "ask": "",
            "sign_off": False,
            "poll": False,
        }
    key = f"{issue}\n{why}"
    prior = ""
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, UnicodeError):
        payload = None
    if isinstance(payload, dict):
        prior = str(payload.get("key") or "")
    same = prior == key
    if not same:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(
                {
                    "blocking": "blocking: unverifiable",
                    "issue": issue,
                    "reason": why,
                    "key": key,
                    "sign_off": False,
                },
                sort_keys=True,
            )
            + "\n",
            encoding="utf-8",
        )
    return {
        "blocking": "blocking: unverifiable",
        "record": not same,
        "issue": issue,
        "reason": why,
        "ask": "",
        "sign_off": False,
        "poll": False,
    }


def apply_owner_gate(
    state_path: Path,
    *,
    blocker: str,
    session_can_create: bool,
    only_remaining: bool,
) -> dict[str, object]:
    """Decide the gate and persist the blocker the first time it ends the goal."""
    path = Path(state_path)
    decision = decide_owner_gate(
        blocker=blocker,
        session_can_create=session_can_create,
        only_remaining=only_remaining,
        already_recorded=_recorded_blocker(path),
    )
    if decision["record"]:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"blocker": blocker}) + "\n", encoding="utf-8")
    return decision
