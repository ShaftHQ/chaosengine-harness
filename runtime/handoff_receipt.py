#!/usr/bin/env python3
"""One handoff receipt (ShaftHQ/SHAFT_ENGINE#8054).

The timings ledger stays ``tool.py usage``. This file stores ``usageRef`` and
one outcome line, not a second meter. Resume text comes from the receipt alone.
"""

from __future__ import annotations

import sys
from pathlib import Path

_DIR = str(Path(__file__).resolve().parent)
if _DIR not in sys.path:
    sys.path.insert(0, _DIR)

import honesty  # noqa: E402
import session_token_usage  # noqa: E402

SCHEMA_VERSION = honesty.SCHEMA_VERSION
NewerReceiptError = honesty.NewerReceiptError


def build(
    *,
    task: str,
    head_sha: str,
    branch: str = "",
    pr: str = "",
    changed_paths: list | None = None,
    verified: list | None = None,
    open_next: str = "",
    blockers: list | None = None,
    outcome: str = "unknown",
    usage_ref: str = "",
    coverage: str = "unknown",
    unknowns: list | None = None,
    how_obtained: str | None = None,
    limitations: list | None = None,
    review_budget: dict | None = None,
    review_rounds_used: int | None = None,
    follow_ups: list | None = None,
    waste: dict | None = None,
    wip: dict | None = None,
    pr_size: int | str | None = None,
    cycle_time_seconds: int | str | None = None,
    feedback_receipt: dict | str | None = None,
) -> dict:
    """Allow-listed handoff object. Waste fields are digests, not transcripts."""
    complete = coverage == "complete"
    receipt = {
        "schemaVersion": SCHEMA_VERSION,
        "task": task,
        "headSha": head_sha or "unknown",
        "branch": branch or "",
        "pr": pr or "",
        "changedPaths": list(changed_paths or []),
        "verified": list(verified or []),
        "open": {"next": open_next or "unknown", "blockers": list(blockers or [])},
        "outcome": outcome or "unknown",
        "usageRef": usage_ref or "",
        "coverage": coverage or "unknown",
        "howObtained": how_obtained or ("measured" if complete else "guessed"),
        "limitations": list(limitations) if limitations is not None else ([] if complete else ["unmeasured"]),
        "unknowns": list(unknowns) if unknowns is not None else (
            [] if complete else [{"label": "verification", "settle": "re-run gate"}]
        ),
    }
    if review_budget is not None:
        receipt["reviewBudget"] = review_budget
    if review_rounds_used is not None:
        receipt["reviewRoundsUsed"] = review_rounds_used
    if follow_ups is not None:
        receipt["followUps"] = list(follow_ups)
    receipt["waste"] = _digest_waste(waste)
    receipt["wip"] = _digest_wip(wip)
    receipt["prSize"] = _digest_number(pr_size)
    receipt["cycleTimeSeconds"] = _digest_number(cycle_time_seconds)
    feedback = feedback_receipt
    if feedback is None and isinstance(waste, dict):
        if "feedbackReceipt" in waste:
            feedback = waste.get("feedbackReceipt")
        elif "feedback_receipt" in waste:
            feedback = waste.get("feedback_receipt")
    receipt["feedbackReceipt"] = (
        session_token_usage.feedback_receipt(feedback) if feedback is not None else "unmeasured"
    )
    return receipt


def _digest_number(value: object) -> int | str:
    if value is None or value == "unmeasured":
        return "unmeasured"
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError("digest fields are non-negative ints or unmeasured")
    return value


def _digest_waste(waste: dict | None) -> dict:
    body = waste if isinstance(waste, dict) else {}
    return {
        "tokenWaste": _digest_number(body.get("tokenWaste", body.get("token_waste"))),
        "contextWaste": _digest_number(body.get("contextWaste", body.get("context_waste"))),
        "reworkWaste": _digest_number(body.get("reworkWaste", body.get("rework_waste"))),
        "softwareWastes": (
            session_token_usage.normalize_software_wastes(
                body.get("softwareWastes", body.get("software_wastes"))
            )
            if "softwareWastes" in body or "software_wastes" in body
            else "unmeasured"
        ),
        "source": (
            str(body.get("source"))
            if body.get("source") in {"unmeasured", "digest", "fixture"}
            else "unmeasured"
        ),
    }


def _digest_wip(wip: dict | None) -> dict:
    body = wip if isinstance(wip, dict) else {}
    return {
        "items": _digest_number(body.get("items")),
        "branches": _digest_number(body.get("branches")),
        "openPrs": _digest_number(body.get("openPrs", body.get("open_prs"))),
    }


def from_step(
    *,
    task: str,
    head: str,
    branch: str = "",
    pr: str = "",
    next_step: str = "",
) -> dict:
    """Cheap receipt from checkpoint fields. Verification stays unknown."""
    return build(
        task=task,
        head_sha=head or "unknown",
        branch=branch,
        pr=pr,
        open_next=next_step or "unknown",
        coverage="unknown",
        outcome="unknown",
        usage_ref="",
    )


def path_for(directory: Path, task: str) -> Path:
    return Path(directory) / f"{task}.handoff.json"


def write(directory: Path, task: str, receipt: dict) -> Path:
    target = path_for(directory, task)
    honesty.save(target, receipt)
    return target


def read(directory: Path, task: str) -> dict | None:
    target = path_for(directory, task)
    if not target.is_file():
        return None
    return honesty.load(target)


def verification_status(receipt: dict) -> str:
    """Partial coverage and any unknown stay unknown. Never a guessed pass."""
    if not isinstance(receipt, dict):
        return "unknown"
    if (receipt.get("coverage") or "unknown") != "complete" or receipt.get("unknowns"):
        return "unknown"
    verified = receipt.get("verified")
    if not isinstance(verified, list) or not verified:
        return "unknown"
    for item in verified:
        if not isinstance(item, dict):
            return "unknown"
        if item.get("howObtained") not in {"measured", "computed"}:
            return "unknown"
        if item.get("exit") not in (0, "0"):
            return "failed"
    return "passed"


def resume_from_receipt(receipt: dict) -> str:
    """SHA, open step, verification, and one outcome line. No token meter."""
    if not isinstance(receipt, dict):
        receipt = {}
    opened = receipt.get("open") if isinstance(receipt.get("open"), dict) else {}
    outcome = " ".join(str(receipt.get("outcome") or "unknown").split()) or "unknown"
    return (
        f"SHA: {receipt.get('headSha') or 'unknown'}\n"
        f"open: {opened.get('next') or 'unknown'}\n"
        f"verification: {verification_status(receipt)}\n"
        f"outcome: {outcome}\n"
    )
