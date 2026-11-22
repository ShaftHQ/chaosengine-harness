#!/usr/bin/env python3
"""Same-model review floor (ShaftHQ/SHAFT_ENGINE#8055, #8048 R2, #8063).

Does not call a model. A missing second CLI stays on Grok and spawns nothing.
"""

from __future__ import annotations

import re

CHECKLIST = (
    "missing tests",
    "hidden scope",
    "unverified claims",
    "reader-cost",
    "safety",
)
_PLAN = re.compile(r"(?m)^##\s+Plan\b")
_REASONING = re.compile(r"(?i)author reasoning|chain of thought|inner monologue|tool transcript")
_DIFF = re.compile(r"(?m)^(diff --git|## Diff\b)")
_BLOCK = ("wrong", "unsafe", "untruthful")


PROMPT_PARTS = (
    "role",
    "context",
    "instruction",
    "input_data",
    "constraints",
    "output_format",
)


def lint_structured_prompt(packet: dict) -> dict:
    """CT-GenAI structured prompt: six parts plus model, version, and sampling."""
    body = packet if isinstance(packet, dict) else {}
    missing = [name for name in PROMPT_PARTS if not str(body.get(name) or "").strip()]
    sampling = body.get("sampling")
    if sampling in (None, ""):
        sampling = "unrecorded"
    metadata = {
        "model": str(body.get("model") or "").strip() or "unrecorded",
        "version": str(body.get("version") or body.get("model_version") or "").strip() or "unrecorded",
        "sampling": sampling,
    }
    reasons = [f"missing-{name}" for name in missing]
    for key, value in metadata.items():
        if value == "unrecorded":
            reasons.append(f"missing-{key}")
    return {"ok": not reasons, "missing": missing, "metadata": metadata, "reasons": reasons}


def lint_packet(text: str) -> list[str]:
    """Fail a packet that carries a plan section or author reasoning."""
    reasons = []
    body = text or ""
    if _PLAN.search(body):
        reasons.append("packet contains ## Plan")
    if _REASONING.search(body):
        reasons.append("packet contains author reasoning")
    return reasons


def required_reviews(
    *,
    public_contract: bool = False,
    irreversible: bool = False,
    outbound: bool = False,
) -> int:
    """One review for every change. Two for a public contract, irreversible work, or outbound."""
    if public_contract or irreversible or outbound:
        return 2
    return 1


def review_sequence(rounds: int) -> tuple[str, ...]:
    """Adversarial review 1 starts with the self-accept push, beside CI.

    The two reviewers do not start in one step. A fix cycle sits between them.
    This tuple names develop, test, self-accept, then each review, then
    develop, test, accept, then finalize. CI is not a step here.
    There is no zero-review path.
    """
    count = int(rounds)
    if count < 1:
        raise ValueError("there is no zero-review path")
    steps = ["develop", "test", "self-accept"]
    for index in range(1, count + 1):
        steps.append(f"adversarial-review-{index}")
        steps.extend(("develop", "test", "accept"))
    steps.append("finalize")
    return tuple(steps)


def is_pass(review: dict) -> bool:
    """LGTM without the checklist and a SHA is not a PASS."""
    if not isinstance(review, dict) or str(review.get("verdict", "")).upper() != "PASS":
        return False
    if len(str(review.get("sha") or "")) < 7:
        return False
    cited = review.get("checklist")
    if not isinstance(cited, list):
        return False
    folded = {str(item).casefold() for item in cited}
    return all(item in folded for item in CHECKLIST)


def bounded_round(
    packet: str,
    *,
    elapsed_s: float,
    limit_s: float,
    rounds_used: int = 0,
) -> dict:
    """Diff-scoped and time-bounded. A timeout counts as the round and does not retry."""
    result = {
        "rounds_used": rounds_used + 1,
        "counted": True,
        "retry": False,
        "spawned": False,
    }
    if elapsed_s >= limit_s:
        result.update({
            "fallback": "self-review",
            "verdict": "timeout",
            "problems": [],
            "diff_scoped": False,
        })
        return result
    found = lint_packet(packet)
    result.update({
        "fallback": None,
        "verdict": "lint-fail" if found else "ready",
        "problems": found,
        "diff_scoped": bool(_DIFF.search(packet or "")) and not found,
    })
    return result


def resolve_reviewer(name: str | None, *, binary_present: bool) -> dict:
    """Default is Grok. A missing local CLI does not spawn a cloud agent."""
    if name and name != "grok" and not binary_present:
        return {"reviewer": "grok", "log": "second lens unavailable", "spawned": False}
    return {"reviewer": "grok", "log": None, "spawned": False}


def budget(
    files: int,
    lines: int,
    *,
    public_contract: bool = False,
    irreversible: bool = False,
    outbound: bool = False,
    blast: str = "low",
) -> dict:
    """MIN/MAX review rounds. MAX never exceeds the delivery-cycle cap of 3."""
    minimum = required_reviews(
        public_contract=public_contract,
        irreversible=irreversible,
        outbound=outbound,
    )
    small = files <= 1 or lines <= 90
    if small and blast != "high":
        maximum = minimum
    elif blast == "high" or files > 8 or lines > 400:
        maximum = min(minimum + 2, 3)
    else:
        maximum = min(minimum + 1, 3)
    maximum = min(max(maximum, minimum), 3)
    return {
        "min": minimum,
        "max": maximum,
        "inputs": {
            "files": files,
            "lines": lines,
            "publicContract": bool(public_contract),
            "irreversible": bool(irreversible),
            "outbound": bool(outbound),
            "blast": blast,
        },
    }


def blocks_at_max(finding: str, *, at_max: bool) -> bool:
    """At MAX, only a wrong, unsafe, or untruthful finding still blocks."""
    if not at_max:
        return True
    folded = finding.casefold()
    return any(word in folded for word in _BLOCK)
