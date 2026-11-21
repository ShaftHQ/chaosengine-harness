"""One unverifiable owner gate ends the goal. It does not poll."""

from __future__ import annotations

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
