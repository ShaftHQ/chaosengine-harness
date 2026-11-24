"""Non-coding SDLC gates for product owners, scrum masters, and testers.

Mechanical checks only. Whether a split is wise, or whether intent is truly
met, stays in the adversarial review.
"""

from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path
import re

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
        "test_completion",
        "incident",
    ),
}

FLOW_STAGES = (
    "ready",
    "intent-match",
    "test_completion",
    "incident",
)


def flow_stages() -> tuple[str, ...]:
    return FLOW_STAGES


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
    """An invalid partition or a non-empty boundary value. A technique name is not enough."""
    partition = str(check.get("partition") or "").strip().casefold()
    if partition in _INVALID_PARTITIONS:
        return True
    boundary = check.get("boundary")
    if boundary is False or boundary is None:
        return False
    return not _blank(boundary)


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


def _risk_level(risk: dict) -> int | None:
    likelihood = risk.get("likelihood")
    impact = risk.get("impact")
    if isinstance(likelihood, bool) or isinstance(impact, bool):
        return None
    if isinstance(likelihood, int) and isinstance(impact, int):
        return likelihood * impact
    return None


def risk_register_gate(risks) -> dict:
    """A high-impact risk with no test is an owner decision."""
    missing = []
    levels = []
    for risk in risks or []:
        if not isinstance(risk, dict):
            continue
        impact = risk.get("impact")
        high = impact in {"high", "critical"} or (
            isinstance(impact, int) and not isinstance(impact, bool) and impact >= 4
        )
        if high and _blank(risk.get("test")):
            missing.append(str(risk.get("id") or risk.get("name") or "risk"))
        level = _risk_level(risk)
        if level is not None:
            levels.append({"id": str(risk.get("id") or risk.get("name") or "risk"), "level": level})
    return {
        "ok": not missing,
        "reasons": ["owner-decision-high-impact-untested"] if missing else [],
        "missing": missing,
        "levels": levels,
    }


ISO_25010 = (
    "functional suitability",
    "performance efficiency",
    "compatibility",
    "interaction capability",
    "reliability",
    "security",
    "maintainability",
    "flexibility",
    "safety",
)
ISO_25059 = (
    "functional correctness",
    "robustness under input shift",
    "controllability of the output",
    "transparency of the decision",
)
_ISO_REQUIRED = {
    "plan": ("test item", "scope"),
    "design spec": ("feature set", "approach"),
    "case spec": ("identifier", "expected result"),
    "incident report": ("summary", "severity"),
}
_ISO_ALIAS = {
    "plan": "plan",
    "test plan": "plan",
    "design": "design spec",
    "design spec": "design spec",
    "case": "case spec",
    "case spec": "case spec",
    "completion": "completion report",
    "completion report": "completion report",
    "incident": "incident report",
    "incident report": "incident report",
}
_SEPARATOR_CELL = re.compile(r"^[:\- ]+$")
_TRACE_HEADER_WORDS = frozenset({"requirement", "check", "result"})
ORACLE_TYPES = frozenset({"specified", "derived", "metamorphic", "differential", "human"})
_DIFF_PATH = re.compile(r"^diff --git a/(.+?) b/(.+)$", re.M)


def _trace_data_line(line: str) -> bool:
    """A markdown trace row with real cells. Headers and dash separators are not data."""
    text = line.strip()
    if len(text) < 2 or not text.startswith("|") or not text.endswith("|"):
        return False
    cells = [cell.strip() for cell in text[1:-1].split("|")]
    if len(cells) < 3:
        return False
    for cell in cells:
        if not cell or _SEPARATOR_CELL.fullmatch(cell):
            return False
        if cell.casefold() in _TRACE_HEADER_WORDS:
            return False
    return True


class _TraceRowFinder:
    """Stand-in for the old row regex. `.search` returns the first real data row."""

    def search(self, body: str):
        for line in (body or "").splitlines():
            if _trace_data_line(line):
                return line
        return None


_TRACE_ROW = _TraceRowFinder()


def quality_checklist() -> dict:
    """Names only. Not a quotation of ISO/IEC 25010 or 25059."""
    return {"25010": ISO_25010, "25059": ISO_25059}


def iso_29119_template(kind: str, text: str) -> dict:
    """Check an ISO/IEC/IEEE 29119-3 style template. Completion needs a trace row."""
    name = _ISO_ALIAS.get(" ".join((kind or "").casefold().split()))
    if name is None:
        return {"ok": False, "reasons": ["unknown-template"]}
    body = text or ""
    folded = body.casefold()
    reasons: list[str] = []
    if name == "completion report":
        for word in ("requirement", "check", "result"):
            if word not in folded:
                reasons.append(f"missing-{word}")
        if _TRACE_ROW.search(body) is None:
            reasons.append("missing-requirement-check-result-trace")
    else:
        for phrase in _ISO_REQUIRED[name]:
            if phrase not in folded:
                reasons.append("missing-" + phrase.replace(" ", "-"))
    return {"ok": not reasons, "reasons": reasons}


def risk_controls(risk: dict) -> dict:
    """Likelihood times impact. Level 8 or more needs techniques and a mutation target."""
    row = risk if isinstance(risk, dict) else {}
    level = _risk_level(row)
    techniques = [str(item) for item in (row.get("techniques") or []) if str(item).strip()]
    mutation = str(row.get("mutation_target") or "").strip()
    reasons: list[str] = []
    if level is not None and level >= 8 and not techniques:
        reasons.append("missing-techniques")
    if level is not None and level >= 8 and not mutation:
        reasons.append("missing-mutation-target")
    return {
        "ok": not reasons,
        "reasons": reasons,
        "level": level,
        "techniques": techniques,
        "mutation_target": mutation,
    }


def _testish(path: str) -> bool:
    name = path.replace("\\", "/")
    lowered = name.casefold()
    return (
        "/test" in f"/{lowered}"
        or lowered.startswith("test")
        or "test_" in lowered
        or lowered.endswith("test.java")
        or lowered.endswith("tests.java")
    )


def oracle_gate(diff_text: str, checks) -> dict:
    """A changed test in the diff needs one of the five oracle types."""
    changed = []
    for match in _DIFF_PATH.finditer(diff_text or ""):
        path = match.group(2)
        if _testish(path) and path not in changed:
            changed.append(path)
    if not changed:
        return {"ok": True, "reasons": [], "missing": [], "oracles": sorted(ORACLE_TYPES)}
    declared: dict[str, str] = {}
    unknown: list[str] = []
    for check in checks or []:
        if not isinstance(check, dict):
            continue
        path = str(check.get("path") or check.get("file") or "")
        oracle = str(check.get("oracle") or "").strip().casefold()
        if not path:
            continue
        if oracle not in ORACLE_TYPES:
            unknown.append(path)
            continue
        declared[path] = oracle
    missing = [path for path in changed if path not in declared]
    reasons: list[str] = []
    if missing:
        reasons.append("missing-oracle-type")
    if unknown:
        reasons.append("unknown-oracle-type")
    return {"ok": not reasons, "reasons": reasons, "missing": missing, "oracles": sorted(ORACLE_TYPES)}


def rerun_flake(results) -> dict:
    """Three identical results are stable. Fewer than three, or a mismatch, is flake."""
    shown = list(results or [])
    if len(shown) < 3 or len({str(item) for item in shown[:3]}) != 1:
        return {"ok": False, "flake": True, "reasons": ["rerun-to-flake"], "runs": len(shown)}
    return {"ok": True, "flake": False, "reasons": [], "runs": len(shown)}


_FULL_TRACE_KEYS = ("requirement", "risk", "technique", "check", "result", "defect")
_FULL_TRACE_HEADER = (
    "| Requirement | Risk | Technique | Check | Result | Defect |\n"
    "| --- | --- | --- | --- | --- | --- |\n"
)
_DEEP_TECHNIQUES = frozenset({"decision-table", "state-transition"})
_BVA_PAIRS = ({"min-1", "min+1"}, {"max-1", "max+1"})
FLAKE_CAUSES = frozenset({
    "timing-async",
    "state-leakage",
    "network-env",
    "locator",
    "order-dependence",
    "time-random",
})
_FAIL_TOKENS = frozenset({"fail", "failed", "failure", "error", "false", "red"})
_PASS_TOKENS = frozenset({"pass", "passed", "ok", "green", "true"})
_SCOPE_MARKS = frozenset({"in", "out"})
_SARIF_BLOCK = frozenset({"error", "warning", ""})
_SARIF_NOTE = frozenset({"note", "none"})
_TEST_ATTR = re.compile(
    r"(?:#\[(?:[\w:]+::)?test\]|@Test\b|\[(?:Fact|Theory|TestMethod|Test)\b)"
)
_TEST_HEADER = re.compile(
    r"(?:"
    r"(?:async\s+)?def\s+test_\w+"
    r"|(?:\bit|\btest)\s*\("
    r"|func\s+Test\w+\s*\("
    r")"
)
_ASSERT_SIGNAL = re.compile(
    r"(?:"
    r"\bassert(?:_eq!|_ne!|!|(?!\w))"
    r"|\bexpect\s*\("
    r"|\braise\b"
    r"|pytest\.raises\b"
    r"|\bself\.assert\w+"
    r"|\bt\.(?:Error|Errorf|Fatal|Fatalf|Fail|FailNow)\b"
    r"|should_panic\b"
    r"|\bAssert\.\w+"
    r"|\.Should\s*\("
    r"|\bassert(?:Equal|Equals|True|False|That|Throws|Null|NotNull)\b"
    r")",
    re.IGNORECASE,
)


def _risk_at_least(risk_level: object, floor: int) -> bool:
    if isinstance(risk_level, bool) or not isinstance(risk_level, int):
        return False
    return risk_level >= floor


def _cell(value: object) -> str:
    if value is None:
        return ""
    return str(value).strip().replace("|", "/").replace("\n", " ")


def _full_trace_cells(row: object) -> list[str] | None:
    if isinstance(row, dict):
        folded = {str(key).strip().casefold(): value for key, value in row.items()}
        return [_cell(folded.get(key)) for key in _FULL_TRACE_KEYS]
    if isinstance(row, (list, tuple)) and not isinstance(row, str):
        cells = [_cell(item) for item in row]
        if len(cells) < len(_FULL_TRACE_KEYS):
            cells.extend("" for _ in range(len(_FULL_TRACE_KEYS) - len(cells)))
        return cells[: len(_FULL_TRACE_KEYS)]
    return None


def traceability_matrix_full(rows) -> dict:
    """Six-column requirement trace. A blank required cell is incomplete-trace-row."""
    items = list(rows or [])
    if not items:
        return {
            "ok": False,
            "reasons": ["incomplete-trace-row"],
            "missing": [],
            "matrix": _FULL_TRACE_HEADER,
        }
    body = [_FULL_TRACE_HEADER.rstrip("\n")]
    missing: list[int] = []
    for index, row in enumerate(items):
        cells = _full_trace_cells(row)
        if cells is None or any(not cell for cell in cells):
            missing.append(index)
            cells = cells or [""] * len(_FULL_TRACE_KEYS)
        body.append("| " + " | ".join(cells) + " |")
    reasons = ["incomplete-trace-row"] if missing else []
    return {
        "ok": not reasons,
        "reasons": reasons,
        "missing": missing,
        "matrix": "\n".join(body) + "\n",
    }


def _technique_name(check: dict) -> str:
    text = str(check.get("technique") or "").strip().casefold().replace("_", " ").replace("-", " ")
    return "-".join(text.split())


def _boundary_tokens(check: dict) -> set[str]:
    raw: list[object] = []
    for key in ("boundary", "boundaries", "points"):
        value = check.get(key)
        if isinstance(value, str):
            raw.extend(re.split(r"[,/\s]+", value))
        elif isinstance(value, (list, tuple)) and not isinstance(value, str):
            raw.extend(value)
    tokens = set()
    for item in raw:
        text = str(item).strip().casefold().replace(" ", "")
        if text:
            tokens.add(text)
    return tokens


def bva_depth_gate(risk_level, check) -> dict:
    """Level 8 and above needs 3-value BVA, two boundary points, or a table or transition."""
    if not _risk_at_least(risk_level, 8):
        return {"ok": True, "reasons": []}
    row = check if isinstance(check, dict) else {}
    if _technique_name(row) in _DEEP_TECHNIQUES:
        return {"ok": True, "reasons": []}
    tokens = _boundary_tokens(row)
    if len(tokens) >= 2 or any(pair <= tokens for pair in _BVA_PAIRS):
        return {"ok": True, "reasons": []}
    return {"ok": False, "reasons": ["insufficient-bva-depth"]}


def _mutation_target_exists(target: str, repo_root) -> bool:
    root = Path(repo_root).resolve()
    candidate = Path(target)
    if not candidate.is_absolute():
        candidate = root / candidate
    try:
        resolved = candidate.resolve()
    except OSError:
        return False
    if resolved != root and root not in resolved.parents:
        return False
    return resolved.is_file()


def _survivors_present(survivors: object) -> bool:
    if survivors is None or isinstance(survivors, (str, bytes)):
        return False
    try:
        return len(list(survivors)) > 0
    except TypeError:
        return False


def mutation_target_gate(risk_level, target, *, repo_root=None, survivors=None) -> dict:
    """Level 8 and above needs a real mutation target and no survivor on a changed line."""
    if not _risk_at_least(risk_level, 8):
        return {"ok": True, "reasons": []}
    reasons: list[str] = []
    text = str(target or "").strip()
    if not text or (repo_root is not None and not _mutation_target_exists(text, repo_root)):
        reasons.append("missing-mutation-target")
    if _survivors_present(survivors):
        reasons.append("survived-mutant")
    return {"ok": not reasons, "reasons": reasons}


def _number(value: object) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value)


def coverage_gate(patch_percent, repo_percent, repo_percent_base, *, strict: bool = False) -> dict:
    """Patch floor is 80, or 90 when strict. Repo coverage may not fall below its base."""
    reasons: list[str] = []
    patch = _number(patch_percent)
    floor = 90.0 if strict else 80.0
    if patch is None or patch < floor:
        reasons.append("patch-coverage")
    current = _number(repo_percent)
    base = _number(repo_percent_base)
    if current is None or base is None or current < base:
        reasons.append("coverage-ratchet")
    return {"ok": not reasons, "reasons": reasons}


def quality_scope_gate(plan_scope, *, subject: str = "software") -> dict:
    """Every quality characteristic is explicitly in or out. AI subjects add ISO 25059."""
    names = list(ISO_25010)
    if str(subject or "").strip().casefold() == "ai":
        names.extend(ISO_25059)
    scope = plan_scope if isinstance(plan_scope, dict) else {}
    folded = {str(key).strip().casefold(): value for key, value in scope.items()}
    missing = [
        name
        for name in names
        if str(folded.get(name) or "").strip().casefold() not in _SCOPE_MARKS
    ]
    return {
        "ok": not missing,
        "reasons": ["missing-quality-scope"] if missing else [],
        "missing": missing,
    }


def _posix_rel(value: object) -> str:
    text = str(value or "").strip().replace("\\", "/")
    if "://" in text:
        text = text.split("://", 1)[1]
    while text.startswith("./"):
        text = text[2:]
    return text.lstrip("/")


def _uri_matches(uri: str, changed: list[str]) -> bool:
    norm = _posix_rel(uri)
    for path in changed:
        item = _posix_rel(path)
        if item and (norm == item or norm.endswith("/" + item) or item.endswith("/" + norm)):
            return True
    return False


def _sarif_message(result: dict) -> str:
    message = result.get("message")
    if isinstance(message, dict):
        text = str(message.get("text") or message.get("markdown") or "")
    else:
        text = str(message or "")
    return " ".join(text.split())[:180]


def _sarif_results(sarif_doc: dict) -> list[dict]:
    found: list[dict] = []
    runs = sarif_doc.get("runs")
    if not isinstance(runs, list):
        return found
    for run in runs:
        if not isinstance(run, dict):
            continue
        results = run.get("results")
        if isinstance(results, list):
            found.extend(item for item in results if isinstance(item, dict))
    return found


def _sarif_uris(result: dict) -> list[str]:
    uris: list[str] = []
    locations = result.get("locations")
    if not isinstance(locations, list):
        return uris
    for location in locations:
        if not isinstance(location, dict):
            continue
        physical = location.get("physicalLocation")
        if not isinstance(physical, dict):
            continue
        artifact = physical.get("artifactLocation")
        if isinstance(artifact, dict) and artifact.get("uri"):
            uris.append(str(artifact["uri"]))
    return uris


def sarif_gate(sarif_doc, changed_paths, *, max_rows: int = 20) -> dict:
    """SARIF 2.1.0. Error, warning, and omitted level block on changed paths. Note does not."""
    if not isinstance(sarif_doc, dict) or str(sarif_doc.get("version") or "").strip() != "2.1.0":
        return {"ok": False, "reasons": ["sarif-version"], "rows": [], "notes": [], "blocked": 0}
    if isinstance(changed_paths, str):
        changed = [_posix_rel(changed_paths)]
    else:
        changed = [_posix_rel(path) for path in (changed_paths or [])]
    cap = max(0, int(max_rows)) if isinstance(max_rows, int) and not isinstance(max_rows, bool) else 20
    rows: list[dict] = []
    notes: list[dict] = []
    blocked = 0
    for result in _sarif_results(sarif_doc):
        level = result.get("level")
        folded = "" if level is None else str(level).strip().casefold()
        matched = next((uri for uri in _sarif_uris(result) if _uri_matches(uri, changed)), "")
        if not matched:
            continue
        row = {
            "path": _posix_rel(matched),
            "level": folded or "omitted",
            "rule": str(result.get("ruleId") or ""),
            "message": _sarif_message(result),
        }
        if folded in _SARIF_NOTE:
            if len(notes) < cap:
                notes.append(row)
            continue
        if folded not in _SARIF_BLOCK:
            continue
        blocked += 1
        if len(rows) < cap:
            rows.append(row)
    reasons = ["static-finding"] if blocked else []
    return {"ok": not reasons, "reasons": reasons, "rows": rows, "notes": notes, "blocked": blocked}


def _run_token(item: object) -> str:
    if isinstance(item, dict):
        item = item.get("result", item.get("status", item.get("outcome", "")))
    return str(item).strip().casefold()


def _as_date(value: object) -> date | None:
    if isinstance(value, date):
        return date(value.year, value.month, value.day)
    text = str(value or "").strip()
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", text):
        return None
    try:
        return date.fromisoformat(text)
    except ValueError:
        return None


def _expiry_in_window(expires: str, today: date) -> bool:
    day = _as_date(expires)
    if day is None:
        return False
    return today <= day <= today + timedelta(days=30)


def _quarantine_fields(quarantine: object, today: date) -> tuple[list[str], str]:
    record = quarantine if isinstance(quarantine, dict) else None
    if record is None:
        return ["flake-quarantine"], ""
    owner = str(record.get("owner") or "").strip()
    ticket = str(record.get("ticket") or "").strip()
    cause = str(record.get("cause") or "").strip()
    expires = str(record.get("expires") or "").strip()
    known = cause in FLAKE_CAUSES
    if owner and ticket and known and _expiry_in_window(expires, today):
        return [], cause
    return ["flake-quarantine"], cause if known else ""


def flake_quarantine_gate(runs, quarantine=None, *, today=None) -> dict:
    """Three identical failures are a defect. A flake needs a quarantine and is never a pass."""
    judged = rerun_flake(runs)
    window = [_run_token(item) for item in list(runs or [])[:3]]
    anchor = _as_date(today) if today is not None else date.today()
    if anchor is None:
        anchor = date.today()
    base = {
        "flake": judged["flake"],
        "runs": judged["runs"],
        "defect_type": "",
        "quarantined": False,
        "passed": False,
    }
    if not judged["flake"] and len(window) >= 3 and all(token in _FAIL_TOKENS for token in window):
        return {**base, "ok": False, "reasons": ["stable-failure"], "flake": False}
    if not judged["flake"]:
        passed = len(window) >= 3 and all(token in _PASS_TOKENS for token in window)
        return {**base, "ok": True, "reasons": [], "passed": passed}
    reasons, cause = _quarantine_fields(quarantine, anchor)
    return {
        **base,
        "ok": not reasons,
        "reasons": reasons,
        "defect_type": cause,
        "quarantined": not reasons,
        "passed": False,
    }


def _diff_source_lines(diff_text: str) -> list[tuple[str, str]]:
    rows: list[tuple[str, str]] = []
    for raw in (diff_text or "").splitlines():
        if not raw or raw.startswith(("diff ", "index ", "@@", "\\", "+++", "---")):
            continue
        mark = raw[0]
        if mark in "+- ":
            if mark == "-":
                continue
            rows.append((mark, raw[1:]))
            continue
        rows.append(("+", raw))
    return rows


def _sibling_function(text: str) -> bool:
    if not text or text[0].isspace() or text[0] in "})]":
        return False
    if _TEST_HEADER.search(text) or _TEST_ATTR.search(text):
        return False
    return bool(re.match(r"(?:async\s+def |def |func |fn |class )\w", text))


def _added_test_lines(diff_text: str) -> list[str]:
    rows = _diff_source_lines(diff_text)
    saw = False
    in_test = False
    armed = False
    captured: list[str] = []
    for mark, text in rows:
        if _TEST_ATTR.search(text):
            saw = True
            in_test = True
            armed = True
            if mark == "+":
                captured.append(text)
            continue
        if armed:
            armed = False
            in_test = True
            if mark == "+":
                captured.append(text)
            continue
        if _TEST_HEADER.search(text):
            saw = True
            in_test = True
            if mark == "+":
                captured.append(text)
            continue
        if in_test and _sibling_function(text):
            in_test = False
        if in_test and mark == "+":
            captured.append(text)
    if not saw:
        return [text for mark, text in rows if mark == "+"]
    return captured


def _blank_keep_breaks(chunk: str) -> str:
    return "".join("\n" if char == "\n" else " " for char in chunk)


def _slash_line_comment(text: str, index: int) -> bool:
    """True when ``//`` starts a comment, not Python floor division."""
    if not text.startswith("//", index):
        return False
    line_start = text.rfind("\n", 0, index) + 1
    prefix = text[line_start:index]
    if prefix.strip() == "":
        return True
    return prefix.rstrip().endswith((";", "{", "}"))


def _mask_source(text: str) -> str:
    """Blank comments and string contents. Newlines stay so line counts hold."""
    out: list[str] = []
    index = 0
    limit = len(text)
    while index < limit:
        if text.startswith(("'''", '"""'), index):
            quote = text[index : index + 3]
            out.append(quote)
            end = text.find(quote, index + 3)
            if end == -1:
                out.append(_blank_keep_breaks(text[index + 3 :]))
                break
            out.append(_blank_keep_breaks(text[index + 3 : end]))
            out.append(quote)
            index = end + 3
            continue
        if text[index] in "\"'":
            quote = text[index]
            out.append(quote)
            cursor = index + 1
            while cursor < limit and text[cursor] != "\n":
                if text[cursor] == "\\":
                    out.append(" ")
                    if cursor + 1 < limit and text[cursor + 1] != "\n":
                        out.append(" ")
                        cursor += 2
                        continue
                    cursor += 1
                    continue
                if text[cursor] == quote:
                    out.append(quote)
                    cursor += 1
                    break
                out.append(" ")
                cursor += 1
            index = cursor
            continue
        if text[index] == "#":
            end = text.find("\n", index)
            if end == -1:
                out.append(" " * (limit - index))
                break
            out.append(" " * (end - index))
            index = end
            continue
        if text.startswith("/*", index):
            end = text.find("*/", index + 2)
            if end == -1:
                out.append(_blank_keep_breaks(text[index:]))
                break
            out.append(_blank_keep_breaks(text[index : end + 2]))
            index = end + 2
            continue
        if _slash_line_comment(text, index):
            end = text.find("\n", index)
            if end == -1:
                out.append(" " * (limit - index))
                break
            out.append(" " * (end - index))
            index = end
            continue
        out.append(text[index])
        index += 1
    return "".join(out)


def _mask_comments_and_strings(lines: list[str]) -> list[str]:
    if not lines:
        return lines
    masked = _mask_source("\n".join(lines)).split("\n")
    if len(masked) != len(lines):
        return lines
    return masked


def assertion_signal_gate(diff_text, *, is_new_file: bool = True) -> dict:
    """A new test file with no assertion signal blocks. An edit without one is a review warning.

    Comments and string literals are blanked before the signal check, so a
    title, a docstring, or a commented-out assert cannot satisfy it.
    """
    lines = _mask_comments_and_strings(_added_test_lines(diff_text or ""))
    if lines and not any(_ASSERT_SIGNAL.search(line) for line in lines):
        if is_new_file:
            return {"ok": False, "status": "block", "reasons": ["assertion-free"]}
        return {"ok": True, "status": "review", "reasons": ["assertion-free"]}
    return {"ok": True, "status": "pass", "reasons": []}
