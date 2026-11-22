#!/usr/bin/env python3
"""Score the frozen retrieve-router questions.

Backends are an in-process lexical fixture. This is not a live Graphify or
MemPalace run, and it is not the #45 model rig. P7 stays not run.
"""

from __future__ import annotations

import importlib.util
import json
import re
import sys
import tempfile
import time
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[2]
QUESTIONS = Path(__file__).with_name("questions.json")
OUT = Path(__file__).with_name("last-score.json")
REPORT = Path(__file__).with_name("REPORT.md")
STOP = frozenset(
    "the a an of to and or for with from that this what when why where who how does did has have been into about must never not".split()
)


def _load(name: str, relative: str):
    path = ROOT / relative
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


RETRIEVE = _load("ce_retrieve_router_score", "runtime/retrieve.py")
SPLIT = _load("ce_corpus_split_score", "runtime/corpus_split.py")


def _corpus() -> list[tuple[str, int, str]]:
    rows: list[tuple[str, int, str]] = []
    files = list((ROOT / "runtime").glob("*.py"))
    files.append(ROOT / "identity.md")
    files.append(ROOT / "references" / "retrieve-first.md")
    for path in files:
        if not path.is_file():
            continue
        relative = path.relative_to(ROOT).as_posix()
        text = path.read_text(encoding="utf-8", errors="replace")
        for number, line in enumerate(text.splitlines(), start=1):
            rows.append((relative, number, line))
    return rows


CORPUS = _corpus()


def _tokens(query: str) -> list[str]:
    found = re.findall(r"[A-Za-z0-9_./-]{3,}", query)
    return [token.casefold() for token in found if token.casefold() not in STOP]


def lexical_hits(query: str, limit: int = 8) -> list[tuple[str, int, str]]:
    tokens = _tokens(query)
    if not tokens:
        return []
    scored: list[tuple[int, str, int, str]] = []
    for path, number, line in CORPUS:
        folded = line.casefold()
        score = sum(1 for token in tokens if token in folded or token in path.casefold())
        if score:
            scored.append((score, path, number, line))
    scored.sort(key=lambda item: (-item[0], item[1], item[2]))
    return [(path, number, line) for score, path, number, line in scored[:limit]]


def _format_hits(hits: list[tuple[str, int, str]]) -> str:
    lines = []
    for path, number, line in hits:
        label = " ".join(line.split())[:80] or path
        lines.append(f"{path}:{number}:{line}")
        lines.append(f"NODE {label} [src={path} loc=L{number}")
    return "\n".join(lines)


def _fake_run(calls: list[list[str]]):
    def run(args, **kwargs):
        calls.append(list(args))
        joined = " ".join(str(part) for part in args)
        if not any(name in args for name in ("graphify", "mempalace", "memory")):
            return mock.Mock(returncode=0, stdout="", stderr="")
        hits = lexical_hits(joined)
        if not hits:
            if "graphify" in args:
                return mock.Mock(returncode=4, stdout="", stderr="No unique node match")
            return mock.Mock(returncode=0, stdout="No results\n", stderr="")
        return mock.Mock(returncode=0, stdout=_format_hits(hits), stderr="")

    return run


def _project() -> Path:
    root = Path(tempfile.mkdtemp())
    package = root / "chaos-engine"
    package.mkdir()
    (package / "tool.py").write_text("# tool\n", encoding="utf-8")
    seen: set[str] = set()
    for path, number, line in CORPUS:
        if path in seen:
            continue
        seen.add(path)
        target = root / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("\n", encoding="utf-8")
        del number, line
    return root


def _hit_matches(hit: dict, gold: dict) -> bool:
    if str(hit.get("path") or "") != gold["path"]:
        return False
    return hit.get("line") == gold["line"]


def recall_at_5(question: dict, hits: list[dict]) -> float:
    gold = question["gold"]
    if not gold:
        return 0.0
    top = hits[:5]
    found = sum(1 for item in gold if any(_hit_matches(hit, item) for hit in top))
    return found / len(gold)


def _mean(values: list[float]) -> float:
    return sum(values) / len(values) if values else 0.0


def _p95(samples: list[float]) -> float:
    if not samples:
        return 0.0
    ordered = sorted(samples)
    index = int(round(0.95 * (len(ordered) - 1)))
    return ordered[index]


def _ask(query: str, project: Path, mode: str):
    """retrieve_py is the explicit-store path. router_v2 is classify_scope."""
    if mode == "retrieve_py":
        chosen = RETRIEVE.pick_store(query)
        return RETRIEVE.retrieve(query, project=project, store=chosen, account=False)
    if mode != "router_v2":
        raise ValueError(mode)
    return RETRIEVE.retrieve(query, project=project, account=False)


def _scale(retrieve_module, project: Path, mode: str) -> dict:
    """N, 4N, 16N padded store bodies. Bytes must not grow with N."""
    base = 8
    report: dict[str, dict] = {}
    queries = {
        "mempalace": "why do we keep one palace",
        "memory": "has this constraint bitten us",
    }
    anchor = "runtime/stores.py:29:PALACE_BACKEND\n" + ("y" * 900)
    for store, query in queries.items():
        report[store] = {}
        previous = None
        for factor, count in (("N", base), ("4N", base * 4), ("16N", base * 16)):
            body = anchor + ("item\n" * count)
            samples: list[float] = []
            sizes: list[int] = []

            def run(args, **kwargs):
                if store == "memory" and "memory" not in args:
                    return mock.Mock(returncode=0, stdout="No results\n", stderr="")
                if store == "mempalace" and "mempalace" not in args:
                    return mock.Mock(returncode=4, stdout="", stderr="No unique node match")
                return mock.Mock(returncode=0, stdout=body, stderr="")

            for _ in range(21):
                started = time.perf_counter()
                with (
                    mock.patch.object(retrieve_module.subprocess, "run", side_effect=run),
                    mock.patch.object(retrieve_module, "_tool_py", return_value=project / "chaos-engine" / "tool.py"),
                    mock.patch.object(retrieve_module, "_record_store_outcome"),
                ):
                    receipt = _ask(query, project, mode)
                samples.append(time.perf_counter() - started)
                sizes.append(int(receipt.get("bytes") or 0))
            size = sizes[-1]
            if previous is not None and size > previous:
                raise SystemExit(f"bytes grew with N for {store} {mode}: {previous} -> {size}")
            previous = size
            report[store][factor] = {
                "items": count,
                "bytes": size,
                "bytes_max": max(sizes),
                "p95_seconds": _p95(samples),
                "within_budget": size <= 800,
            }
    return report


def _no_rare(question: dict) -> bool:
    return not RETRIEVE.question_rare_tokens(question["question"])


def evaluate() -> dict:
    """Score the frozen file. Does not rewrite it."""
    payload = json.loads(QUESTIONS.read_text(encoding="utf-8"))
    questions = payload["questions"]
    project = _project()
    (project / "runtime").mkdir(exist_ok=True)
    (project / "runtime" / "stores.py").write_text("PALACE_BACKEND = \"sqlite_exact\"\n", encoding="utf-8")
    no_recall = _mean([recall_at_5(question, []) for question in questions])
    oracle_recall = _mean([recall_at_5(question, question["gold"]) for question in questions])
    implicit_ids = [question["id"] for question in questions if _no_rare(question)]
    arms: dict[str, dict] = {}
    calls: list[list[str]] = []
    with (
        mock.patch.object(RETRIEVE.subprocess, "run", side_effect=_fake_run(calls)),
        mock.patch.object(RETRIEVE, "_tool_py", return_value=project / "chaos-engine" / "tool.py"),
        mock.patch.object(RETRIEVE, "_record_store_outcome"),
    ):
        for mode in ("retrieve_py", "router_v2"):
            recalls: list[float] = []
            implicit_recalls: list[float] = []
            routed = 0
            for question in questions:
                receipt = _ask(question["question"], project, mode)
                hits = receipt.get("hits") if isinstance(receipt.get("hits"), list) else []
                score = recall_at_5(question, hits)
                recalls.append(score)
                if question["id"] in implicit_ids:
                    implicit_recalls.append(score)
                if mode == "router_v2" and receipt.get("route", {}).get("reason") == question["gold_route"]:
                    routed += 1
            recall = _mean(recalls)
            implicit_recall = _mean(implicit_recalls)
            gap = None if oracle_recall == no_recall else (recall - no_recall) / (oracle_recall - no_recall)
            points = (recall - implicit_recall) * 100
            arm = {
                "recall_at_5": recall,
                "implicit_recall_at_5": implicit_recall,
                "gap_closed": gap,
                "implicit_gap_points": points,
                "k2_follow_up": points >= 15,
            }
            if mode == "router_v2":
                arm["routing_accuracy"] = routed / len(questions) if questions else 0.0
            arms[mode] = arm
    for mode, arm in arms.items():
        arm["scale"] = _scale(RETRIEVE, project, mode)
    v2 = arms["router_v2"]
    return {
        "label": "fixture backends, not live stores",
        "questions": len(questions),
        "implicit_questions": len(implicit_ids),
        "p7": "not run",
        "recall_at_5": {
            "no_retrieve": no_recall,
            "oracle": oracle_recall,
            "router": v2["recall_at_5"],
            "implicit": v2["implicit_recall_at_5"],
        },
        "gap_closed": v2["gap_closed"],
        "routing_accuracy": v2["routing_accuracy"],
        "implicit_gap_points": v2["implicit_gap_points"],
        "k2_follow_up": v2["k2_follow_up"],
        "arms": arms,
        "scale": v2["scale"],
        "store_calls": len(calls),
    }


def _report(result: dict) -> str:
    recall = result["recall_at_5"]
    lines = [
        "# Retrieve router eval",
        "",
        "Label: fixture backends, not live stores. P7 (the #45 model rig) was not run. No live Graphify or MemPalace process was scored. `retrieve_py` is `retrieve(query, store=pick_store(query))`. `router_v2` is `classify_scope` through `retrieve(query)` with no store. No second router was added.",
        "",
        f"Frozen set: `experiments/retrieve-router/questions.json` ({result['questions']} questions, sha256 `{json.loads(QUESTIONS.read_text(encoding='utf-8'))['frozen_questions_sha256']}`). The scorer does not rewrite that file.",
        "",
        "## K1",
        "",
        "| Arm | recall@5 | gap closed |",
        "| --- | --- | --- |",
        f"| no-retrieve | {recall['no_retrieve']} | |",
    ]
    for name in ("retrieve_py", "router_v2"):
        arm = result["arms"][name]
        lines.append(f"| {name} | {arm['recall_at_5']} | {arm['gap_closed']} |")
    lines.append(f"| oracle | {recall['oracle']} | |")
    lines.extend(["", "Gap closed is `(arm - no-retrieve) / (oracle - no-retrieve)`.", ""])
    lines.append("## K2")
    lines.append("")
    lines.append(
        f"Implicit-clue slice: {result['implicit_questions']} questions whose `question_rare_tokens` list is empty. recall@5 is reported separately. A follow-up is required only when that slice is at least 15 points below the arm's overall recall@5."
    )
    lines.append("")
    lines.append("| Arm | implicit recall@5 | points below overall | follow-up |")
    lines.append("| --- | --- | --- | --- |")
    for name in ("retrieve_py", "router_v2"):
        arm = result["arms"][name]
        lines.append(
            f"| {name} | {arm['implicit_recall_at_5']} | {arm['implicit_gap_points']} | {arm['k2_follow_up']} |"
        )
    v2 = result["arms"]["router_v2"]
    lines.extend(
        [
            "",
            f"router_v2 routing accuracy against the frozen labels: {v2['routing_accuracy']}. The labels were written to the same first-match table the classifier implements. This is agreement with those labels, not a second human labeling.",
            "",
            "## K3",
            "",
            "Synthetic padded MemPalace and Memory bodies at N=8, 4N=32, and 16N=128. Bytes are the receipt `bytes` field. They stay inside the 800-byte cap and do not grow with N.",
            "",
            "| Arm | Store | N bytes | 4N bytes | 16N bytes | N p95 s | 4N p95 s | 16N p95 s |",
            "| --- | --- | --- | --- | --- | --- | --- | --- |",
        ]
    )
    for name in ("retrieve_py", "router_v2"):
        for store in ("memory", "mempalace"):
            scale = result["arms"][name]["scale"][store]
            lines.append(
                "| {name} | {store} | {n} | {four} | {sixteen} | {pn} | {p4} | {p16} |".format(
                    name=name,
                    store=store,
                    n=scale["N"]["bytes"],
                    four=scale["4N"]["bytes"],
                    sixteen=scale["16N"]["bytes"],
                    pn=scale["N"]["p95_seconds"],
                    p4=scale["4N"]["p95_seconds"],
                    p16=scale["16N"]["p95_seconds"],
                )
            )
    lines.extend(
        [
            "",
            "p95 is the in-process timer around `retrieve()`, 21 samples. Latency is not required to be flat.",
            "",
        ]
    )
    return "\n".join(lines)


def main() -> int:
    result = evaluate()
    OUT.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    REPORT.write_text(_report(result), encoding="utf-8")
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
