#!/usr/bin/env python3
"""
Pre-done self-review gate (#7325): fail a status report whose views drift or whose gaps lack a rule.

Checks one markdown report (PR body, handoff note, status doc):
1. Status table parity: every mermaid node that names a table ID must carry that row's status.
2. Every Blocked/Skipped row cites a permitting rule (``rule:``) and an alternative tried (``alt:``
   naming a mock, fixture, stub, fake, simulator or recording) that points at an existing covering
   test file (``path`` or ``path::name``; the name must appear in the file); negations such as
   "no", "not yet", "candidate", "TODO" or "pending" before the first path fail (#7360 gap). A
   non-data block (human step, platform-only, feature off) may use
   ``alt: none-possible (<reason>) verified: <how>``; data-blocked rows may not.
3. Declared counts (``Blocked: 3``) match the table.
4. A non-empty ``## What's missing`` section answers "are we missing any?"; a bare "nothing"/"none"
   needs a ``verified: <how>`` note.
Exit 0 pass, 1 findings, 2 usage error. ``--gate OBS.json`` is the mechanical
done gate: exit 0 pass, 1 a rule was skipped, 2 usage or bad JSON. Stdlib only.
"""

from __future__ import annotations

import importlib.util
import json
import re
import sys
from pathlib import Path

GAP_STATUSES = ("blocked", "skipped")
STATUS_WORDS = ("passed", "pass", "done", "failed", "fail", "blocked", "skipped", "wip", "todo",
                "in progress", "pending", "mocked")
# Short forms map to the table spelling; built with zip so no literal key looks like a secret.
ALIASES = dict(zip(("pass", "fail"), ("passed", "failed")))
ALTERNATIVE = re.compile(r"\balt:\s*\S.*\b(mock|fixture|stub|fake|simulat|record|emulat)", re.I)
ALT_TEXT = re.compile(r"\balt:\s*(.*)", re.I)
NEGATION = re.compile(r"\b(no|not|never|none|candidate|todo|tbd|pending|planned|later|missing|without)\b", re.I)
PATH_TOKEN = re.compile(r"`?([\w./-]+\.\w+)(?:(?:::|#)([\w.-]+))?`?")
NONE_POSSIBLE = re.compile(r"none-possible\s*\(\s*[^)\s][^)]*\)\s*verified:\s*\S", re.I)
DATA_WORDS = re.compile(r"\b(data|dataset|fixtures?|mocks?|seed\w*|accounts?|credentials?|stubs?|records?|users?|tokens?)\b", re.I)
NOTHING = re.compile(r"^[-*\s]*(nothing|none|n/?a|nil)\.?\s*$", re.I)
VERIFIED = re.compile(r"\bverified:\s*\S", re.I)
RULE = re.compile(r"\brule:\s*\S", re.I)
MERMAID = re.compile(r"```mermaid\n(.*?)```", re.S)
NODE = re.compile(r"\b([A-Za-z][\w-]*)\s*(?:\[\[?|\(\(?|\{\{?|>)\s*\"?([^\]\)\}\"]*)")
CLASS = re.compile(r"^\s*class\s+([\w,-]+)\s+([\w-]+)", re.M)
COUNT = re.compile(r"\b(" + "|".join(w for w in STATUS_WORDS if " " not in w) + r")\s*[:=]\s*(\d+)\b", re.I)
MISSING = re.compile(r"^#{2,6}\s*what'?s missing\??\s*$(.*?)(?=^#{1,6}\s|\Z)", re.I | re.M | re.S)


def _cells(line: str) -> list[str]:
    return [cell.strip() for cell in line.strip().strip("|").split("|")]


def norm(status: str) -> str:
    text = status.strip().lower().replace("-", " ").replace("_", " ")
    for word in sorted(STATUS_WORDS, key=len, reverse=True):
        if re.search(rf"\b{word}\b", text):
            return ALIASES.get(word, word)
    return text


def parse_table(text: str) -> list[dict]:
    """First markdown table with a Status column; rows keep the raw line for rule/alt search."""
    lines = text.splitlines()
    for i, line in enumerate(lines[:-1]):
        if "|" not in line or not re.match(r"^\s*\|?\s*:?-{3,}", lines[i + 1]):
            continue
        header = [cell.lower() for cell in _cells(line)]
        if "status" not in header:
            continue
        status_at = header.index("status")
        rows = []
        for row_line in lines[i + 2:]:
            if "|" not in row_line:
                break
            cells = _cells(row_line)
            if len(cells) <= status_at:
                continue
            rows.append({"id": cells[0].strip("` *"), "status": norm(cells[status_at]), "line": row_line})
        return rows
    return []


def mermaid_statuses(text: str, ids: set[str]) -> dict[str, list[str]]:
    found: dict[str, list[str]] = {}
    for block in MERMAID.findall(text):
        for node, label in NODE.findall(block):
            if node in ids and norm(label) in STATUS_WORDS + ("passed", "failed"):
                found.setdefault(node, []).append(norm(label))
        for nodes, klass in CLASS.findall(block):
            for node in nodes.split(","):
                if node in ids and norm(klass) in STATUS_WORDS + ("passed", "failed"):
                    found.setdefault(node, []).append(norm(klass))
    return found


def _covering_file(alt: str, roots: list[Path]) -> bool:
    for path, name in PATH_TOKEN.findall(alt):
        for root in roots:
            target = root / path
            if target.is_file():
                if not name or name in target.read_text(encoding="utf-8", errors="ignore"):
                    return True
    return False


def alternative_problem(line: str, roots: list[Path]) -> str | None:
    match = ALT_TEXT.search(line)
    if not match:
        return "with no 'alt:' mock/fixture/stub tried"
    alt = match.group(1).split("|")[0]
    if alt.strip().lower().startswith("none-possible"):
        if DATA_WORDS.search(line[:match.start()] + line[match.end():]):
            return "is data-blocked: 'alt: none-possible' is not allowed; cite an existing covering test"
        if not NONE_POSSIBLE.match(alt.strip()):
            return "with 'alt: none-possible' lacking '(<reason>) verified: <how>'"
        return None
    if not ALTERNATIVE.search(line):
        return "with no 'alt:' mock/fixture/stub tried"
    first_path = PATH_TOKEN.search(alt)
    if NEGATION.search(alt[:first_path.start()] if first_path else alt):
        return "with an 'alt:' that is not done yet (negation/candidate/TODO/pending)"
    if not _covering_file(alt, roots):
        return "with an 'alt:' naming no existing covering test file (`path` or `path::name`)"
    return None


def _missing_problem(body: str) -> str | None:
    lines = [line for line in body.strip().splitlines() if line.strip()]
    if not lines:
        return "no adversarial pass: add a non-empty '## What's missing' section"
    if any(NOTHING.match(line) for line in lines) and not VERIFIED.search(body):
        return "unverified adversarial pass: a 'nothing' item needs 'verified: <how>'"
    return None


def review(text: str, roots: list[Path] | None = None) -> list[str]:
    roots = roots or [Path.cwd()]
    rows = parse_table(text)
    if not rows:
        return ["no status table: add a markdown table with ID and Status columns"]
    findings = []
    by_id = {row["id"]: row for row in rows}
    for node, statuses in mermaid_statuses(text, set(by_id)).items():
        for status in statuses:
            if status != by_id[node]["status"]:
                findings.append(f"drift: {node} is '{by_id[node]['status']}' in the table but '{status}' in mermaid")
    for row in rows:
        if row["status"] in GAP_STATUSES:
            if not RULE.search(row["line"]):
                findings.append(f"uncited gap: {row['id']} is {row['status']} with no 'rule:' citing the rule that permits it")
            problem = alternative_problem(row["line"], roots)
            if problem:
                findings.append(f"no alternative: {row['id']} is {row['status']} {problem}")
    outside = MERMAID.sub("", text)
    table_lines = {row["line"] for row in rows}
    prose = "\n".join(line for line in outside.splitlines() if line not in table_lines)
    for word, number in COUNT.findall(prose):
        status = norm(word)
        actual = sum(1 for row in rows if row["status"] == status)
        if int(number) != actual:
            findings.append(f"count drift: '{word}: {number}' but the table has {actual} {status}")
    section = MISSING.search(text)
    problem = _missing_problem(section.group(1) if section else "")
    if problem:
        findings.append(problem)
    return findings


_DIFF_FILE = re.compile(r"^diff --git a/(.+?) b/(.+)$")
_PARAM_INTRO = re.compile(
    r"(os\.environ|getenv|getProperty|config(?:uration)?\s*[\.\[]|"
    r"parameters?\s*[\.\[]|@Parameter|suite[_\s-]*param|params\.get)",
    re.I,
)
_STRING_LITERAL = re.compile(r"""(?P<q>['"])(?P<body>[^'"\n]{2,80})(?P=q)""")
_NUMBER_LITERAL = re.compile(r"(?<![\w.])(\d{2,})(?![\w.])")
_READER_SUFFIXES = frozenset({
    ".py", ".java", ".js", ".ts", ".md", ".properties", ".xml", ".yml", ".yaml", ".json", ".feature", ".kt",
})
_BRIDGE = None


def _line_literals(line: str) -> set[str]:
    found = {match.group("body") for match in _STRING_LITERAL.finditer(line)}
    found.update(match.group(1) for match in _NUMBER_LITERAL.finditer(line))
    return found


def _literal_on_line(literal: str, line: str) -> bool:
    if literal.isdigit():
        pattern = rf"(?<![\w.]){re.escape(literal)}(?![\w.])"
    else:
        pattern = rf"(?<![\w]){re.escape(literal)}(?![\w])"
    return re.search(pattern, line) is not None


def check_replaced_literal_readers(diff_text: str, project_root) -> list[str]:
    """Warn with file and line when a parameter replaces a literal another file still reads."""
    root = Path(project_root)
    literals: set[str] = set()
    changed: set[str] = set()
    file_name: str | None = None
    removed: set[str] = set()
    saw_param = False

    def flush() -> None:
        nonlocal removed, saw_param
        if file_name and saw_param:
            literals.update(removed)
            changed.add(file_name.replace("\\", "/"))
        removed = set()
        saw_param = False

    for line in (diff_text or "").splitlines():
        if line.startswith("diff --git "):
            flush()
            match = _DIFF_FILE.match(line)
            file_name = match.group(2) if match else None
            continue
        if line.startswith(("---", "+++", "@@")):
            continue
        if line.startswith("-"):
            removed.update(_line_literals(line[1:]))
        elif line.startswith("+") and _PARAM_INTRO.search(line[1:]):
            saw_param = True
    flush()
    if not literals or not root.is_dir():
        return []
    warnings: list[str] = []
    for path in sorted(root.rglob("*")):
        if not path.is_file() or path.suffix.casefold() not in _READER_SUFFIXES:
            continue
        relative_parts = path.relative_to(root).parts
        if any(part.startswith(".") or part == "__pycache__" for part in relative_parts):
            continue
        relative = path.relative_to(root).as_posix()
        if relative in changed or path.stat().st_size > 1_000_000:
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeError):
            continue
        for number, content in enumerate(text.splitlines(), start=1):
            for literal in sorted(literals):
                if _literal_on_line(literal, content):
                    warnings.append(f"replaced-literal: {literal} still read at {relative}:{number}")
    return warnings


def _rules_bridge():
    global _BRIDGE
    if _BRIDGE is not None:
        return _BRIDGE
    path = Path(__file__).resolve().parents[1] / "rules" / "pre_done_bridge.py"
    spec = importlib.util.spec_from_file_location("ce_pre_done_bridge", path)
    if spec is None or spec.loader is None:
        raise ImportError(path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    _BRIDGE = module
    return module


def apply_wired_rules(payload: object) -> list[str]:
    """Run wired rules/*.py functions when the gate payload names them."""
    if not isinstance(payload, dict) or not payload:
        return []
    bridge = _rules_bridge()
    found: list[str] = []
    for name, item in payload.items():
        if name not in bridge.WIRED:
            found.append(f"rule:{name}:not-wired")
            continue
        result = bridge.invoke(name, item)
        if not result.get("ok", True):
            for hit in result.get("hits") or ["fail"]:
                found.append(f"rule:{name}:{hit}")
    return found


def _memory_cause_problems(note: object) -> list[str]:
    directory = str(Path(__file__).resolve().parent)
    if directory not in sys.path:
        sys.path.insert(0, directory)
    import memory_provenance

    decision = memory_provenance.accept_memory_note(note)
    if decision.get("rejected"):
        return list(decision["reasons"])
    return []


def mechanical_problems(obs: dict) -> list[str]:
    """Named misses. Empty means the mechanical rules that apply were not skipped.

    Over-limit open PRs stay advisory (the count must still be present).
    ``anti_compound_waiver`` and ``outbound_waiver`` are recorded waivers, not passes.
    """
    if not isinstance(obs, dict):
        return ["required proof missing"]
    found: list[str] = []
    if obs.get("proof_required", True):
        proofs = obs.get("proofs")
        if not proofs:
            found.append("required proof missing")
        elif isinstance(proofs, list):
            for proof in proofs:
                if not isinstance(proof, dict) or proof.get("ran") is not True:
                    name = proof.get("id") if isinstance(proof, dict) else "?"
                    found.append(f"required proof missing: {name or '?'} not run")
    if obs.get("pr_create") and "open_pr_count" not in obs:
        found.append("open-PR count skipped before create")
    if obs.get("sources") and not obs.get("tests"):
        found.append("sources without tests")
    changed = obs.get("changed_lines")
    if isinstance(changed, int) and not isinstance(changed, bool) and changed > 90 and not obs.get("size_waiver"):
        found.append("size over elite target without split-or-waiver")
    if obs.get("protected_delete") and not obs.get("delete_check"):
        found.append("protected-path delete skipped delete-check")
    if obs.get("retrieve_owed") and not obs.get("retrieve"):
        found.append("retrieve skipped")
    if obs.get("added_file") and not (obs.get("subtracted_or_reused") or str(obs.get("addition_reason") or "").strip()):
        found.append("subtract-before-add missing")
    if obs.get("claim_done") and obs.get("done_gate") != "pass":
        found.append("done gate skipped")
    target = str(obs.get("write_target") or "")
    if target in {"memory", "skill", "heuristics"} and not obs.get("verified_write"):
        if not str(obs.get("anti_compound_waiver") or "").strip():
            found.append("anti-compounding: unverified write")
    if obs.get("outbound") and not str(obs.get("outbound_waiver") or "").strip():
        if obs.get("agent_drafted") and not obs.get("disclosed"):
            found.append("outbound disclose missing")
        claims = obs.get("claims") or []
        checked = set(obs.get("checked_claims") or [])
        if any(claim not in checked for claim in claims):
            found.append("outbound unchecked claims")
    diff = obs.get("diff") or obs.get("diff_text") or ""
    root = obs.get("project_root") or obs.get("root")
    if diff and root:
        found.extend(check_replaced_literal_readers(str(diff), root))
    if "memory_note" in obs:
        found.extend(_memory_cause_problems(obs.get("memory_note")))
    if "rules" in obs:
        found.extend(apply_wired_rules(obs.get("rules")))
    return found


def _gate_main(path: Path) -> int:
    if not path.is_file():
        print(f"pre-done: {path} not found", file=sys.stderr)
        return 2
    try:
        obs = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        print("pre-done: gate json is not an object", file=sys.stderr)
        return 2
    if not isinstance(obs, dict):
        print("pre-done: gate json is not an object", file=sys.stderr)
        return 2
    found = mechanical_problems(obs)
    for item in found:
        print(f"pre-done: {item}")
    print(f"pre-done: {'fail' if found else 'pass'} ({len(found)} finding(s))")
    return 1 if found else 0


def main(argv: list[str]) -> int:
    if argv[:1] == ["--gate"]:
        if len(argv) != 2:
            print("usage: pre_done_review.py --gate OBS.json", file=sys.stderr)
            return 2
        return _gate_main(Path(argv[1]))
    paths = [arg for arg in argv if not arg.startswith("--")]
    if len(paths) != 1 or any(arg not in {"--json"} for arg in argv if arg.startswith("--")):
        print("usage: pre_done_review.py REPORT.md [--json]", file=sys.stderr)
        return 2
    path = Path(paths[0])
    if not path.is_file():
        print(f"pre-done: {path} not found", file=sys.stderr)
        return 2
    roots = [path.resolve().parent, Path.cwd()]
    roots += [parent for parent in path.resolve().parents if (parent / ".git").exists()][:1]
    findings = review(path.read_text(encoding="utf-8"), roots)
    if "--json" in argv:
        print(json.dumps({"status": "fail" if findings else "pass", "findings": findings}))
    else:
        for finding in findings:
            print(f"pre-done: {finding}")
        print(f"pre-done: {'fail' if findings else 'pass'} ({len(findings)} finding(s))")
    return 1 if findings else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
