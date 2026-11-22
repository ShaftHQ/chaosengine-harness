#!/usr/bin/env python3
"""Score frozen harness A/B/C runs. Heuristics are fixed in procedure.md."""

from __future__ import annotations

import argparse
import csv
import json
import re
import statistics
import textwrap
import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parent
RAW = ROOT / "raw"
ARMS = ("A", "B", "C")
LONG_CONTEXT = 200_000
PRICE = {
    "input": 2.00,
    "cached": 0.50,
    "output": 6.00,
    "long_input": 4.00,
    "long_cached": 1.00,
    "long_output": 12.00,
}
QUALITY_MAX = {
    "design": 15,
    "shaft_idioms": 15,
    "robustness": 10,
    "test_data": 5,
    "readability": 10,
    "hygiene": 5,
}
COMPLETE_MARKERS = (
    "checkout-complete",
    "checkout_complete",
    "Checkout: Complete",
    "Thank you for your order",
)
SOURCE_SUFFIXES = {".java", ".xml", ".properties", ".md", ".json", ".txt"}
STRIP_NAMES = {
    "AGENTS.md",
    ".chaos-engine-hosts.json",
}
STRIP_DIRS = {".chaos-engine", ".grok", ".git", "target", ".agents", ".memory"}


def estimate_usd(usage: dict) -> float | None:
    if not usage:
        return None
    try:
        inp = int(usage.get("input_tokens") or 0)
        cached = int(usage.get("cache_read_input_tokens") or 0)
        out = int(usage.get("output_tokens") or 0)
    except (TypeError, ValueError):
        return None
    long = inp + cached >= LONG_CONTEXT
    in_rate = PRICE["long_input"] if long else PRICE["input"]
    cache_rate = PRICE["long_cached"] if long else PRICE["cached"]
    out_rate = PRICE["long_output"] if long else PRICE["output"]
    return round((inp * in_rate + cached * cache_rate + out * out_rate) / 1_000_000, 6)


def _passing_cases(surefire: Path) -> list[tuple[str, str]]:
    found: list[tuple[str, str]] = []
    if not surefire.is_dir():
        return found
    for path in sorted(surefire.glob("*.xml")):
        try:
            root = ET.parse(path).getroot()
        except ET.ParseError:
            continue
        for case in root.iter("testcase"):
            if any(child.tag in {"failure", "error", "skipped"} for child in case):
                continue
            classname = case.attrib.get("classname") or ""
            name = case.attrib.get("name") or ""
            if classname and name:
                found.append((classname, name))
    return found


def _java_files(project: Path) -> list[Path]:
    root = project / "src" / "test"
    if not root.is_dir():
        root = project
    return [path for path in root.rglob("*.java") if "target" not in path.parts]


def _class_name(text: str, fallback: str) -> str:
    package = ""
    matched = re.search(r"^\s*package\s+([\w.]+)\s*;", text, re.M)
    if matched:
        package = matched.group(1) + "."
    named = re.search(r"\b(?:class|interface|enum)\s+(\w+)", text)
    return package + (named.group(1) if named else fallback)


def method_bodies(text: str) -> list[tuple[str, str]]:
    """Return (method name, body) for each @Test method, else one whole-file body."""
    if "@Test" not in text:
        return [("", text)]
    bodies: list[tuple[str, str]] = []
    parts = re.split(r"@Test\b", text)
    for part in parts[1:]:
        signature = re.search(r"\b(\w+)\s*\([^;]*\)\s*(?:throws\s+[\w.,\s]+)?\{", part)
        if signature is None:
            bodies.append(("", part))
            continue
        start = signature.end()
        depth = 1
        index = start
        while index < len(part) and depth:
            if part[index] == "{":
                depth += 1
            elif part[index] == "}":
                depth -= 1
            index += 1
        bodies.append((signature.group(1), part[start:index]))
    return bodies or [("", text)]


def _indexed_bodies(project: Path) -> dict[tuple[str, str], str]:
    indexed: dict[tuple[str, str], str] = {}
    for path in _java_files(project):
        text = path.read_text(encoding="utf-8", errors="replace")
        classname = _class_name(text, path.stem)
        for name, body in method_bodies(text):
            indexed[(classname, name)] = body
            indexed[(path.stem, name)] = body
    return indexed


def _body_for(indexed: dict[tuple[str, str], str], classname: str, name: str) -> str:
    if (classname, name) in indexed:
        return indexed[(classname, name)]
    simple = classname.rsplit(".", 1)[-1]
    return indexed.get((simple, name), "")


def correctness(project: Path, raw_run: Path, *, timed_out: bool) -> dict[str, int]:
    zeros = {"build": 0, "login": 0, "checkout": 0, "determinism": 0, "negative": 0, "correctness": 0}
    if timed_out:
        return zeros
    if not any(project.rglob("pom.xml")):
        return zeros
    log1 = (raw_run / "mvn-1.log").read_text(encoding="utf-8", errors="replace") if (raw_run / "mvn-1.log").is_file() else ""
    surefire = _passing_cases(raw_run / "surefire-1")
    reached = bool(surefire) or "Tests run:" in log1
    compiled = "COMPILATION ERROR" not in log1
    build = 10 if reached and compiled else 0
    indexed = _indexed_bodies(project)
    login = checkout = negative = 0
    for classname, name in surefire:
        body = _body_for(indexed, classname, name)
        folded = body.casefold()
        if "standard_user" in body:
            login = 8
        if "checkout" in folded and any(marker.casefold() in folded for marker in COMPLETE_MARKERS):
            checkout = 12
        if "locked_out_user" in body or ("wrong" in folded and "password" in folded):
            negative = 5
    determinism = 5
    for number in (1, 2, 3):
        exit_path = raw_run / f"mvn-{number}.exit"
        if not exit_path.is_file() or exit_path.read_text(encoding="utf-8").strip() != "0":
            determinism -= 5
    determinism = max(0, determinism)
    total = build + login + checkout + determinism + negative
    return {
        "build": build,
        "login": login,
        "checkout": checkout,
        "determinism": determinism,
        "negative": negative,
        "correctness": total,
    }


def load_meta(raw_run: Path) -> dict:
    path = raw_run / "meta.json"
    if not path.is_file():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def iter_runs() -> list[tuple[str, str, Path]]:
    found = []
    for arm in ARMS:
        arm_dir = RAW / arm
        if not arm_dir.is_dir():
            continue
        for run_dir in sorted(path for path in arm_dir.iterdir() if path.is_dir()):
            found.append((arm, run_dir.name, run_dir))
    return found


def project_for(arm: str, run: str) -> Path:
    folders = {"A": "A-bare", "B": "B-agentsmd", "C": "C-chaosengine"}
    return ROOT / "exp" / folders[arm] / f"run-{run}"


def cli_document(text: str) -> dict | None:
    """Last JSON object the Grok CLI wrote that carries a result."""
    decoder = json.JSONDecoder()
    last = None
    for index, char in enumerate(text):
        if char != "{":
            continue
        try:
            obj, _end = decoder.raw_decode(text[index:])
        except json.JSONDecodeError:
            continue
        if isinstance(obj, dict) and ("usage" in obj or "text" in obj or "total_cost_usd" in obj):
            last = obj
    return last


def meter_cost(meta: dict, raw_run: Path) -> float | str:
    """CLI ``total_cost_usd`` from meta, else from the saved stdout. Never estimated."""
    stored = meta.get("meter_cost_usd")
    if type(stored) in {int, float}:
        return stored
    stdout = raw_run / "grok-stdout.txt"
    if not stdout.is_file():
        return ""
    document = cli_document(stdout.read_text(encoding="utf-8", errors="replace"))
    cost = document.get("total_cost_usd") if isinstance(document, dict) else None
    if type(cost) in {int, float}:
        return cost
    return ""


def row_for(arm: str, run: str, raw_run: Path) -> dict:
    meta = load_meta(raw_run)
    usage = meta.get("usage") or {}
    timed_out = bool(meta.get("timed_out"))
    project = project_for(arm, run)
    scores = correctness(project, raw_run, timed_out=timed_out)
    quality = meta.get("quality")
    total = None if quality is None else scores["correctness"] + quality
    tokens = usage.get("total_tokens")
    seconds = meta.get("session_seconds")
    per_tokens = None
    per_minute = None
    if quality is not None and tokens:
        per_tokens = round(quality / (tokens / 100_000), 4)
    if quality is not None and seconds:
        per_minute = round(quality / (seconds / 60), 4)
    return {
        "arm": arm,
        "run": run,
        **scores,
        "quality": quality if quality is not None else "",
        "quality_grader_1": meta.get("quality_grader_1", ""),
        "quality_grader_2": meta.get("quality_grader_2", ""),
        "total": total if total is not None else "",
        "input_tokens": usage.get("input_tokens", ""),
        "output_tokens": usage.get("output_tokens", ""),
        "cached_input_tokens": usage.get("cache_read_input_tokens", ""),
        "total_tokens": tokens if tokens is not None else "",
        "estimated_usd": estimate_usd(usage) if usage else "",
        "meter_cost_usd": meter_cost(meta, raw_run),
        "session_seconds": seconds if seconds is not None else "",
        "turns": meta.get("num_turns", ""),
        "tool_calls": meta.get("tool_calls", ""),
        "questions": meta.get("questions", ""),
        "timed_out": timed_out,
        "quality_per_100k_tokens": per_tokens if per_tokens is not None else "",
        "quality_per_minute": per_minute if per_minute is not None else "",
        "model": meta.get("model", ""),
    }


def write_results() -> Path:
    rows = [row_for(arm, run, raw_run) for arm, run, raw_run in iter_runs()]
    target = ROOT / "results.csv"
    fieldnames = list(rows[0].keys()) if rows else ["arm", "run"]
    with target.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)
    write_charts(rows)
    return target


def _numeric(rows: list[dict], arm: str, key: str) -> list[float]:
    values = []
    for row in rows:
        if row["arm"] != arm or row.get(key) == "" or row.get(key) is None:
            continue
        values.append(float(row[key]))
    return values


def write_charts(rows: list[dict]) -> None:
    charts = ROOT / "charts"
    charts.mkdir(exist_ok=True)
    try:
        import matplotlib

        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except ImportError:
        (charts / "MISSING.txt").write_text("matplotlib is not installed\n", encoding="utf-8")
        return
    if (charts / "MISSING.txt").is_file():
        (charts / "MISSING.txt").unlink()

    def bars(key: str, title: str, filename: str) -> None:
        means = []
        for arm in ARMS:
            values = _numeric(rows, arm, key)
            means.append(statistics.fmean(values) if values else 0)
        figure, axis = plt.subplots()
        axis.bar(list(ARMS), means)
        axis.set_title(title)
        axis.set_ylabel(key)
        figure.tight_layout()
        figure.savefig(charts / filename)
        plt.close(figure)

    bars("total", "Mean total score", "score-bar.png")
    bars("quality", "Mean quality", "quality-bar.png")
    bars("correctness", "Mean correctness", "correctness-bar.png")
    bars("total_tokens", "Mean total tokens", "tokens-bar.png")
    bars("session_seconds", "Mean session seconds", "time-bar.png")

    figure, axis = plt.subplots()
    for arm in ARMS:
        xs = _numeric(rows, arm, "total_tokens")
        ys = _numeric(rows, arm, "total")
        if xs and ys and len(xs) == len(ys):
            axis.scatter(xs, ys, label=arm)
    axis.set_xlabel("total tokens")
    axis.set_ylabel("total score")
    axis.legend()
    figure.tight_layout()
    figure.savefig(charts / "score-vs-tokens.png")
    plt.close(figure)

    figure, axis = plt.subplots()
    series = [_numeric(rows, arm, "total") or [0] for arm in ARMS]
    axis.boxplot(series, labels=list(ARMS))
    axis.set_ylabel("total score")
    figure.tight_layout()
    figure.savefig(charts / "score-box.png")
    plt.close(figure)


def summarize() -> str:
    rows = [row_for(arm, run, raw_run) for arm, run, raw_run in iter_runs()]
    lines = []
    for arm in ARMS:
        arm_rows = [row for row in rows if row["arm"] == arm]
        if not arm_rows:
            continue
        for key in ("correctness", "quality", "total", "total_tokens", "session_seconds", "estimated_usd"):
            values = _numeric(arm_rows, arm, key)
            if not values:
                lines.append(f"{arm} {key}: n=0")
                continue
            lines.append(
                f"{arm} {key}: n={len(values)} mean={statistics.fmean(values):.4f} "
                f"median={statistics.median(values):.4f} min={min(values):.4f} max={max(values):.4f}"
            )
    return "\n".join(lines)


def grader_schema() -> dict:
    properties = {name: {"type": "integer", "minimum": 0, "maximum": maximum} for name, maximum in QUALITY_MAX.items()}
    properties["notes"] = {"type": "string"}
    return {
        "type": "object",
        "additionalProperties": False,
        "required": [*QUALITY_MAX.keys(), "notes"],
        "properties": properties,
    }


def blind_tree(project: Path, destination: Path) -> None:
    import shutil

    if destination.exists():
        shutil.rmtree(destination)
    shutil.copytree(
        project,
        destination,
        ignore=shutil.ignore_patterns("target", ".git", "*.sock"),
        dirs_exist_ok=False,
    )
    for path in list(destination.rglob("*")):
        if path.name in STRIP_NAMES or path.name in STRIP_DIRS:
            if path.is_dir():
                shutil.rmtree(path, ignore_errors=True)
            elif path.exists():
                path.unlink()


def source_bundle(project: Path, limit: int = 120_000) -> str:
    chunks = []
    size = 0
    for path in sorted(project.rglob("*")):
        if not path.is_file() or path.suffix.lower() not in SOURCE_SUFFIXES:
            continue
        if any(part in STRIP_DIRS for part in path.parts):
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        relative = path.relative_to(project)
        piece = f"\n\n# FILE {relative}\n{text}"
        if size + len(piece) > limit:
            chunks.append("\n\n# TRUNCATED\n")
            break
        chunks.append(piece)
        size += len(piece)
    return "".join(chunks)


def grader_prompt(bundle: str) -> str:
    rubric = (ROOT / "rubric.md").read_text(encoding="utf-8")
    quality = rubric.split("## Quality, 0-60 (blind)", 1)[1].split("## Scoring protocol", 1)[0]
    return textwrap.dedent(
        f"""
        Score this blinded project. Do not call tools. Use only the source below.
        Return JSON matching the schema. Integers must respect each maximum.
        Award points only for evidence in the source. Missing evidence scores 0 for that item.

        {quality}

        SOURCE:
        {bundle}
        """
    ).strip()


def grade_payload_total(payload: object) -> int | None:
    """Sum a grader object. Reject missing, bool, or out-of-range items."""
    if not isinstance(payload, dict):
        return None
    total = 0
    for name, maximum in QUALITY_MAX.items():
        value = payload.get(name)
        if type(value) is not int or value < 0 or value > maximum:
            return None
        total += value
    if not isinstance(payload.get("notes"), str):
        return None
    return total


def parse_grader_score(text: str) -> dict | None:
    """Pull the grader JSON out of a CLI transcript or a bare JSON document."""
    document = cli_document(text)
    candidates = []
    if isinstance(document, dict):
        candidates.append(document)
        body = document.get("text")
        if isinstance(body, str):
            candidates.append(body)
    candidates.append(text)
    for candidate in candidates:
        if isinstance(candidate, dict):
            if grade_payload_total(candidate) is not None:
                return candidate
            continue
        if not isinstance(candidate, str):
            continue
        decoder = json.JSONDecoder()
        for index, char in enumerate(candidate):
            if char != "{":
                continue
            try:
                obj, _end = decoder.raw_decode(candidate[index:])
            except json.JSONDecodeError:
                continue
            if grade_payload_total(obj) is not None:
                return obj
    return None


def quality_mean(first: int | None, second: int | None) -> float | None:
    scores = [score for score in (first, second) if score is not None]
    if not scores:
        return None
    return statistics.fmean(scores)


def _invoke_grader(prompt_file: Path, cwd: Path, schema: dict, socket: Path, session_id: str) -> str:
    import subprocess

    command = [
        "grok",
        "--cwd",
        str(cwd),
        "--leader-socket",
        str(socket),
        "--session-id",
        session_id,
        "--model",
        "grok-4.7",
        "--permission-mode",
        "bypassPermissions",
        "--max-turns",
        "1",
        "--disable-web-search",
        "--output-format",
        "json",
        "--verbatim",
        "--json-schema",
        json.dumps(schema, separators=(",", ":")),
        "--prompt-file",
        str(prompt_file),
    ]
    completed = subprocess.run(
        command,
        capture_output=True,
        text=True,
        timeout=600,
        check=False,
    )
    return completed.stdout if completed.stdout else completed.stderr


def grade_runs() -> list[str]:
    """Blind each run and record two grader totals. Does not edit the rubric."""
    import uuid

    notes: list[str] = []
    mapping: dict[str, dict[str, str]] = {}
    schema = grader_schema()
    blind_root = ROOT / "raw" / "blind"
    blind_root.mkdir(parents=True, exist_ok=True)
    for arm, run, raw_run in iter_runs():
        project = project_for(arm, run)
        if not project.is_dir():
            notes.append(f"{arm}{run}: project missing")
            continue
        blind_id = uuid.uuid4().hex
        destination = blind_root / blind_id
        mapping[blind_id] = {"arm": arm, "run": run}
        blind_tree(project, destination)
        bundle = source_bundle(destination)
        prompt_file = raw_run / "grader-prompt.txt"
        prompt_file.write_text(grader_prompt(bundle), encoding="utf-8")
        parsed: list[dict | None] = []
        totals: list[int | None] = []
        for index in (1, 2):
            session_id = str(uuid.uuid4())
            socket = raw_run / f"grader-{index}.sock"
            try:
                text = _invoke_grader(prompt_file, destination, schema, socket, session_id)
            except (OSError, subprocess_timeout()) as error:
                text = str(error)
            (raw_run / f"grader-{index}.txt").write_text(text, encoding="utf-8")
            payload = parse_grader_score(text)
            parsed.append(payload)
            totals.append(None if payload is None else grade_payload_total(payload))
            if payload is None:
                notes.append(f"{arm}{run} grader {index}: no parseable score")
        meta = load_meta(raw_run)
        meta["quality_grader_1"] = totals[0] if totals[0] is not None else ""
        meta["quality_grader_2"] = totals[1] if totals[1] is not None else ""
        meta["quality_grader_1_items"] = parsed[0] or {}
        meta["quality_grader_2_items"] = parsed[1] or {}
        mean = quality_mean(totals[0], totals[1])
        meta["quality"] = mean
        (raw_run / "meta.json").write_text(json.dumps(meta, indent=2) + "\n", encoding="utf-8")
        notes.append(f"{arm}{run}: quality={mean} graders={totals}")
    (RAW / "blind-map.json").write_text(json.dumps(mapping, indent=2) + "\n", encoding="utf-8")
    return notes


def subprocess_timeout() -> type[BaseException]:
    import subprocess

    return subprocess.TimeoutExpired


def ct_genai_metrics(*, requirements=None, checks=None, executions=None) -> dict:
    """CT-GenAI 2.3.1 rates. None when the denominator is empty. No model call."""
    reqs = [row for row in (requirements or []) if isinstance(row, dict) and row.get("id")]
    req_ids = [str(row["id"]) for row in reqs]
    negative = [str(row["id"]) for row in reqs if row.get("negative") or row.get("boundary")]
    rows = [row for row in (checks or []) if isinstance(row, dict)]
    covered: set[str] = set()
    hallucinated = 0
    for row in rows:
        requirement_id = str(row.get("requirement_id") or row.get("criterion_id") or "")
        if requirement_id in req_ids:
            covered.add(requirement_id)
        if row.get("hallucination") is True or row.get("hallucinated") is True:
            hallucinated += 1
    runs = list(executions) if executions is not None else None
    successes = 0
    if runs is not None:
        for item in runs:
            if item is True or (isinstance(item, dict) and item.get("success") is True):
                successes += 1

    def ratio(numerator: int, denominator: int) -> float | None:
        if denominator == 0:
            return None
        return numerator / denominator

    return {
        "requirement_recall": ratio(len(covered), len(req_ids)),
        "negative_boundary_recall": ratio(len([item for item in negative if item in covered]), len(negative)),
        "execution_success_rate": None if runs is None else ratio(successes, len(runs)),
        "hallucination_rate": ratio(hallucinated, len(rows)),
    }


def self_check() -> None:
    import tempfile

    prompt = (ROOT / "PROMPT.txt").read_text(encoding="utf-8").strip()
    expected = (
        "Create SHAFT_Engine UI tests for https://www.saucedemo.com: "
        "a login test, and a test that adds an item to the cart and completes checkout."
    )
    if prompt != expected:
        raise SystemExit("PROMPT.txt drifted from the frozen sentence")
    canned = (ROOT / "CANNED.txt").read_text(encoding="utf-8").strip()
    if canned != "Use your best judgement and proceed.":
        raise SystemExit("CANNED.txt drifted")
    agents = (ROOT / "fixtures" / "AGENTS.md").read_text(encoding="utf-8")
    for banned in ("SHAFT", "ChaosEngine", "saucedemo", "SauceDemo"):
        if banned in agents:
            raise SystemExit(f"AGENTS.md contains {banned}")
    pin = (ROOT / "harness-pin.txt").read_text(encoding="utf-8").strip()
    if not re.fullmatch(r"[0-9a-f]{40}", pin):
        raise SystemExit("harness pin is not 40 hex chars")
    usage = {"input_tokens": 1000, "cache_read_input_tokens": 2000, "output_tokens": 500}
    if estimate_usd(usage) != round((1000 * 2 + 2000 * 0.5 + 500 * 6) / 1_000_000, 6):
        raise SystemExit("price table mismatch")
    long_usage = {"input_tokens": 200_000, "cache_read_input_tokens": 0, "output_tokens": 10}
    if estimate_usd(long_usage) != round((200_000 * 4 + 10 * 12) / 1_000_000, 6):
        raise SystemExit("long-context price mismatch")

    with tempfile.TemporaryDirectory() as temporary:
        project = Path(temporary) / "project"
        raw_run = Path(temporary) / "raw"
        java = project / "src" / "test" / "java" / "demo"
        java.mkdir(parents=True)
        raw_run.mkdir()
        (java / "LoginTest.java").write_text(
            "package demo;\nclass LoginTest {\n @Test public void logsIn() {\n"
            "  String user = \"standard_user\";\n }\n}\n",
            encoding="utf-8",
        )
        (java / "CheckoutTest.java").write_text(
            "package demo;\nclass CheckoutTest {\n @Test public void checksOut() {\n"
            "  open(\"checkout\");\n  assertText(\"checkout-complete\");\n }\n}\n",
            encoding="utf-8",
        )
        (java / "LockedTest.java").write_text(
            "package demo;\nclass LockedTest {\n @Test public void rejectsLocked() {\n"
            "  login(\"locked_out_user\");\n }\n}\n",
            encoding="utf-8",
        )
        (project / "pom.xml").write_text("<project/>\n", encoding="utf-8")
        (raw_run / "mvn-1.log").write_text("Tests run: 3, Failures: 0\nBUILD SUCCESS\n", encoding="utf-8")
        for number in (1, 2, 3):
            (raw_run / f"mvn-{number}.exit").write_text("0\n", encoding="utf-8")
        surefire = raw_run / "surefire-1"
        surefire.mkdir()
        (surefire / "TEST-demo.xml").write_text(
            """<?xml version="1.0"?>
            <testsuite>
              <testcase classname="demo.LoginTest" name="logsIn"/>
              <testcase classname="demo.CheckoutTest" name="checksOut"/>
              <testcase classname="demo.LockedTest" name="rejectsLocked"/>
            </testsuite>
            """,
            encoding="utf-8",
        )
        scored = correctness(project, raw_run, timed_out=False)
        if scored["correctness"] != 40:
            raise SystemExit(f"expected 40, got {scored}")
        (raw_run / "mvn-2.exit").write_text("1\n", encoding="utf-8")
        flaky = correctness(project, raw_run, timed_out=False)
        if flaky["determinism"] != 0 or flaky["login"] != 8:
            raise SystemExit(f"flake scoring drifted: {flaky}")
        timed = correctness(project, raw_run, timed_out=True)
        if timed["correctness"] != 0:
            raise SystemExit("timeout must score correctness 0")
    schema = grader_schema()
    if schema["properties"]["design"]["maximum"] != 15:
        raise SystemExit("grader schema drifted")
    sample = {
        "design": 15,
        "shaft_idioms": 15,
        "robustness": 10,
        "test_data": 5,
        "readability": 10,
        "hygiene": 5,
        "notes": "fixture",
    }
    if grade_payload_total(sample) != 60:
        raise SystemExit("grader total drifted")
    if grade_payload_total({**sample, "design": True}) is not None:
        raise SystemExit("bool scores must be rejected")
    if grade_payload_total({**sample, "design": 16}) is not None:
        raise SystemExit("over-max scores must be rejected")
    wrapped = json.dumps({"text": json.dumps(sample), "usage": {}})
    if grade_payload_total(parse_grader_score(wrapped) or {}) != 60:
        raise SystemExit("wrapped grader JSON was not parsed")
    if quality_mean(10, 20) != 15 or quality_mean(None, 8) != 8 or quality_mean(None, None) is not None:
        raise SystemExit("quality mean drifted")
    with tempfile.TemporaryDirectory() as temporary:
        project = Path(temporary) / "project"
        project.mkdir()
        (project / "AGENTS.md").write_text("harness\n", encoding="utf-8")
        (project / ".chaos-engine-hosts.json").write_text("{}\n", encoding="utf-8")
        nested = project / ".grok" / "hooks"
        nested.mkdir(parents=True)
        (nested / "lifecycle.json").write_text("{}\n", encoding="utf-8")
        (project / "pom.xml").write_text("<project/>\n", encoding="utf-8")
        blinded = Path(temporary) / "blind"
        blind_tree(project, blinded)
        if (blinded / "AGENTS.md").exists() or (blinded / ".grok").exists():
            raise SystemExit("blind copy kept harness files")
        if not (blinded / "pom.xml").is_file():
            raise SystemExit("blind copy dropped the project")
        raw = Path(temporary) / "raw"
        raw.mkdir()
        (raw / "meta.json").write_text("{}\n", encoding="utf-8")
        (raw / "grok-stdout.txt").write_text(
            json.dumps({"total_cost_usd": 1.25, "usage": {"input_tokens": 1}}),
            encoding="utf-8",
        )
        if meter_cost({}, raw) != 1.25:
            raise SystemExit("meter cost was not read from the CLI document")
    print("self-check ok")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--self-check", action="store_true")
    parser.add_argument("--grade", action="store_true")
    parser.add_argument("--write-results", action="store_true")
    parser.add_argument("--summary", action="store_true")
    parser.add_argument("--print-schema", action="store_true")
    args = parser.parse_args()
    if args.self_check:
        self_check()
    if args.print_schema:
        print(json.dumps(grader_schema()))
    if args.grade:
        for line in grade_runs():
            print(line, flush=True)
    if args.write_results:
        print(write_results())
    if args.summary or args.write_results:
        print(summarize())
    if not any((args.self_check, args.grade, args.write_results, args.summary, args.print_schema)):
        parser.print_help()


if __name__ == "__main__":
    main()
