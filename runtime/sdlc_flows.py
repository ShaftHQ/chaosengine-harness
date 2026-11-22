"""Non-coding SDLC gates for product owners, scrum masters, and testers.

Mechanical checks only. Whether a split is wise, or whether intent is truly
met, stays in the adversarial review.
"""

from __future__ import annotations

UNTESTABLE_CRITERIA = frozenset({"make it nice"})

ROLE_GATES = {
    "product-owner": (
        "acceptance-criteria",
        "single-problem",
        "intent-match-review",
    ),
    "scrum-master": (
        "acceptance-criteria",
        "single-problem",
        "ready-gate",
        "intent-match-review",
    ),
    "tester": (
        "criteria-mapping",
        "executable-checks",
        "plan-review",
        "intent-match-review",
    ),
}


def role_gates(role: str) -> tuple[str, ...]:
    try:
        return ROLE_GATES[role]
    except KeyError as error:
        raise ValueError(f"unknown role: {role}") from error


def _text(criterion: object) -> str:
    if isinstance(criterion, dict):
        return str(criterion.get("text") or "").strip()
    return str(criterion).strip()


def _criterion_id(criterion: object) -> str:
    if isinstance(criterion, dict) and criterion.get("id"):
        return str(criterion["id"])
    return _text(criterion)


def _testable(criterion: object) -> bool:
    if isinstance(criterion, dict) and criterion.get("testable") is False:
        return False
    text = _text(criterion)
    return bool(text) and text.casefold() not in UNTESTABLE_CRITERIA


def _dedupe(reasons: list[str]) -> list[str]:
    return list(dict.fromkeys(reasons))


def ready_gate(story: dict) -> dict:
    """Fail closed when criteria are missing, untestable, or hide two problems."""
    reasons: list[str] = []
    problems = list(story.get("problems") or [])
    if len(problems) > 1:
        reasons.append("mixed-problems")
    elif len(problems) != 1:
        reasons.append("missing-problem")
    criteria = list(story.get("criteria") or [])
    if not criteria:
        reasons.append("missing-criteria")
    elif any(not _testable(item) for item in criteria):
        reasons.append("untestable-criteria")
    return {"ready": not reasons, "reasons": _dedupe(reasons)}


def refine(item: dict) -> dict:
    """Backlog refinement exits through the ready gate."""
    return ready_gate(item)


def intent_match(
    *,
    criteria,
    checks,
    review_count: int,
    high_stakes: bool = False,
) -> dict:
    """Passing checks do not excuse a contradiction or a skipped review."""
    reasons: list[str] = []
    if review_count < 1:
        reasons.append("missing-intent-match-review")
    if high_stakes and review_count < 2:
        reasons.append("missing-second-review")
    ids = {_criterion_id(item) for item in criteria}
    if not checks:
        reasons.append("missing-executable-check")
    for check in checks:
        if check.get("contradicts"):
            reasons.append("contradicts-criterion")
        if check.get("criterion_id") not in ids:
            reasons.append("unmapped-check")
        if check.get("executable") is False:
            reasons.append("missing-executable-check")
    reasons = _dedupe(reasons)
    return {"ok": not reasons, "reasons": reasons}


def review_floor(
    *,
    review_count: int,
    unit_tests_green: bool,
    change: str = "change",
    high_stakes: bool = False,
) -> dict:
    """One adversarial review, two when high-stakes. A green job cannot waive it."""
    reasons: list[str] = []
    if review_count < 1:
        reasons.append("missing-intent-match-review")
    if high_stakes and review_count < 2:
        reasons.append("missing-second-review")
    return {
        "ok": not reasons,
        "reasons": reasons,
        "waived": False,
        "change": change,
        "unit_tests_green": bool(unit_tests_green),
    }


def test_plan_gate(plan: dict, criteria) -> dict:
    """Every acceptance criterion must be mapped, and the plan must be reviewed."""
    reasons: list[str] = []
    mapped = set(plan.get("mapped") or [])
    if any(_criterion_id(item) not in mapped for item in criteria):
        reasons.append("unmapped-criteria")
    if not plan.get("reviewed"):
        reasons.append("missing-plan-review")
    if plan.get("executable") is False:
        reasons.append("missing-executable-check")
    return {"ok": not reasons, "reasons": reasons}


def story_flow(story: dict, checks, *, review_count: int, high_stakes: bool = False) -> dict:
    """Story, then criteria, then executable checks, then intent-match."""
    ready = ready_gate(story)
    if not ready["ready"]:
        return {"stage": "ready", "ok": False, **ready}
    intent = intent_match(
        criteria=list(story.get("criteria") or []),
        checks=checks,
        review_count=review_count,
        high_stakes=high_stakes,
    )
    return {"stage": "intent-match", "ready": True, **intent}


def _blank(value: object) -> bool:
    if value is None:
        return True
    if isinstance(value, str):
        return not value.strip()
    if isinstance(value, (list, tuple)):
        return not any(not _blank(item) for item in value)
    return False


def thin_brief_gate(brief: dict) -> dict:
    """Refuse test-case generation until the request, behavior, and code are present.

    No vendor API. A title alone is not a brief.
    """
    if not isinstance(brief, dict):
        brief = {}
    missing = []
    if _blank(brief.get("request")):
        missing.append("request")
    if _blank(brief.get("how_it_works")):
        missing.append("how_it_works")
    if _blank(brief.get("code_under_test")):
        missing.append("code_under_test")
    return {
        "ok": not missing,
        "draft": not missing,
        "reasons": ["thin-brief"] if missing else [],
        "missing": missing,
        "cases": [],
    }


def _behavior_key(case: dict) -> str:
    return str(case.get("behavior") or case.get("name") or "").strip().casefold()


def _gap_ready(case: dict) -> bool:
    if case.get("executable") is True:
        return True
    steps = case.get("steps")
    expected = str(case.get("expected") or "").strip()
    has_steps = isinstance(steps, list) and any(str(step).strip() for step in steps)
    return bool(has_steps and expected)


def conflict_check(proposed, tree, *, owner_named=None) -> dict:
    """Do not copy a test already in the tree or overwrite a human-edited file."""
    named = {str(item) for item in (owner_named or [])}
    tree_behaviors: dict[str, dict] = {}
    tree_paths: dict[str, dict] = {}
    for item in tree or []:
        if not isinstance(item, dict):
            continue
        key = _behavior_key(item)
        if key:
            tree_behaviors[key] = item
        path = str(item.get("path") or "")
        if path:
            tree_paths[path] = item
    drafts = []
    copies = []
    overwrites = []
    gaps = []
    for case in proposed or []:
        if not isinstance(case, dict):
            continue
        key = _behavior_key(case)
        path = str(case.get("path") or "")
        if key and key in tree_behaviors:
            copies.append(key)
            continue
        existing = tree_paths.get(path)
        if existing and existing.get("human_edited") and path not in named:
            overwrites.append(path)
            continue
        if not _gap_ready(case):
            gaps.append(path or key or "case")
            continue
        drafts.append(case)
    reasons = []
    if copies:
        reasons.append("already-in-tree")
    if overwrites:
        reasons.append("would-overwrite-human-test")
    if gaps:
        reasons.append("missing-executable-or-expected")
    return {
        "ok": not reasons,
        "reasons": reasons,
        "copies": copies,
        "overwrites": overwrites,
        "gaps": gaps,
        "drafts": drafts,
    }


def prepare_test_draft(brief: dict, tree=None, *, owner_named=None) -> dict:
    """Draft only from a complete brief. Deterministic. No model call."""
    gate = thin_brief_gate(brief)
    if not gate["ok"]:
        return {
            **gate,
            "drafts": [],
            "copies": [],
            "overwrites": [],
            "gaps": [],
        }
    behavior = str(brief.get("behavior") or brief.get("request") or "").strip()
    case = {
        "behavior": behavior,
        "path": str(brief.get("path") or ""),
        "steps": list(brief.get("steps") or []),
        "expected": str(brief.get("expected") or ""),
        "executable": brief.get("executable") is True,
        "code_under_test": brief.get("code_under_test"),
    }
    if not case["steps"] and not case["executable"]:
        case["steps"] = [f"Exercise {case['code_under_test']}"]
        if not case["expected"]:
            case["expected"] = str(brief.get("how_it_works") or "")
    checked = conflict_check([case], list(tree or []), owner_named=owner_named)
    return {
        "ok": checked["ok"],
        "draft": bool(checked["drafts"]),
        "reasons": checked["reasons"],
        "missing": [],
        "cases": checked["drafts"],
        "drafts": checked["drafts"],
        "copies": checked["copies"],
        "overwrites": checked["overwrites"],
        "gaps": checked["gaps"],
    }


_INVALID_PARTITIONS = frozenset({"invalid", "negative", "error"})


def _input_bearing(criterion: object) -> bool:
    if not isinstance(criterion, dict):
        return False
    if criterion.get("input_bearing") is False:
        return False
    if criterion.get("input_bearing") is True:
        return True
    inputs = criterion.get("inputs")
    return isinstance(inputs, list) and bool(inputs)


def _is_negative_check(check: dict) -> bool:
    partition = str(check.get("partition") or "").strip().casefold()
    if partition in _INVALID_PARTITIONS:
        return True
    boundary = check.get("boundary")
    if boundary not in (None, "", False):
        return True
    technique = str(check.get("technique") or "").strip().casefold()
    return technique in {"bva", "boundary", "boundary-value"}


def negative_check_gate(criteria, checks) -> dict:
    """Fail when an input-bearing criterion has no invalid or boundary check."""
    missing = []
    for criterion in criteria or []:
        if not _input_bearing(criterion):
            continue
        cid = _criterion_id(criterion)
        related = [
            check for check in checks or []
            if isinstance(check, dict) and check.get("criterion_id") == cid
        ]
        if not any(_is_negative_check(check) for check in related):
            missing.append(cid)
    return {
        "ok": not missing,
        "reasons": ["missing-negative-check"] if missing else [],
        "missing": missing,
    }


def missing_reference(symbols, tree) -> dict:
    """Fail when a cited symbol is absent from the fixture tree. No model call."""
    from pathlib import Path

    root = Path(tree)
    chunks: list[str] = []
    if root.is_dir():
        for path in sorted(root.rglob("*")):
            if not path.is_file():
                continue
            chunks.append(path.name)
            if path.stat().st_size > 1_000_000:
                continue
            try:
                chunks.append(path.read_text(encoding="utf-8"))
            except (OSError, UnicodeError):
                continue
    text = "\n".join(chunks)
    missing = [str(symbol) for symbol in symbols or [] if str(symbol) not in text]
    return {
        "ok": not missing,
        "reasons": ["missing-reference"] if missing else [],
        "missing": missing,
    }


def traceability_matrix(criteria, checks, results=None) -> str:
    """Requirement to check to result, for the completion report."""
    found = results or {}
    lines = ["| Requirement | Check | Result |", "| --- | --- | --- |"]
    for criterion in criteria or []:
        cid = _criterion_id(criterion)
        related = [
            check for check in checks or []
            if isinstance(check, dict) and check.get("criterion_id") == cid
        ]
        if not related:
            lines.append(f"| {cid} |  | unmapped |")
            continue
        for check in related:
            name = str(check.get("id") or check.get("name") or cid)
            result = str(check.get("result") or found.get(name) or "pending")
            lines.append(f"| {cid} | {name} | {result} |")
    return "\n".join(lines) + "\n"


def risk_register_gate(risks) -> dict:
    """A high-impact risk with no test is an owner decision."""
    missing = []
    for risk in risks or []:
        if not isinstance(risk, dict):
            continue
        impact = risk.get("impact")
        high = impact in {"high", "critical"} or (
            isinstance(impact, int) and not isinstance(impact, bool) and impact >= 4
        )
        if high and _blank(risk.get("test")):
            missing.append(str(risk.get("id") or risk.get("name") or "risk"))
    return {
        "ok": not missing,
        "reasons": ["owner-decision-high-impact-untested"] if missing else [],
        "missing": missing,
    }
