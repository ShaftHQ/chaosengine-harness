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


def _scale(retrieve_module, project: Path) -> dict:
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
                    receipt = retrieve_module.retrieve(query, project=project)
                samples.append(time.perf_counter() - started)
                sizes.append(int(receipt.get("bytes") or 0))
            size = sizes[-1]
            if previous is not None and size > previous:
                raise SystemExit(f"bytes grew with N for {store}: {previous} -> {size}")
            previous = size
            report[store][factor] = {
                "items": count,
                "bytes": size,
                "bytes_max": max(sizes),
                "p95_seconds": _p95(samples),
                "within_budget": size <= 800,
            }
    return report


def main() -> int:
    payload = json.loads(QUESTIONS.read_text(encoding="utf-8"))
    questions = payload["questions"]
    project = _project()
    (project / "runtime").mkdir(exist_ok=True)
    (project / "runtime" / "stores.py").write_text("PALACE_BACKEND = \"sqlite_exact\"\n", encoding="utf-8")
    calls: list[list[str]] = []
    router_recalls: list[float] = []
    implicit_recalls: list[float] = []
    no_recalls: list[float] = []
    oracle_recalls: list[float] = []
    routed = 0
    implicit_count = 0
    with (
        mock.patch.object(RETRIEVE.subprocess, "run", side_effect=_fake_run(calls)),
        mock.patch.object(RETRIEVE, "_tool_py", return_value=project / "chaos-engine" / "tool.py"),
        mock.patch.object(RETRIEVE, "_record_store_outcome"),
    ):
        for question in questions:
            gold_text = (ROOT / question["gold"][0]["path"]).read_text(encoding="utf-8").splitlines()[
                question["gold"][0]["line"] - 1
            ]
            clue = RETRIEVE.implicit_clue(question["question"], f"{question['gold'][0]['path']} {gold_text}")
            if clue:
                implicit_count += 1
            receipt = RETRIEVE.retrieve(question["question"], project=project)
            hits = receipt.get("hits") if isinstance(receipt.get("hits"), list) else []
            score = recall_at_5(question, hits)
            router_recalls.append(score)
            if clue:
                implicit_recalls.append(score)
            no_recalls.append(recall_at_5(question, []))
            oracle_recalls.append(recall_at_5(question, question["gold"]))
            if receipt.get("route", {}).get("reason") == question["gold_route"]:
                routed += 1
    router_recall = _mean(router_recalls)
    no_recall = _mean(no_recalls)
    oracle_recall = _mean(oracle_recalls)
    gap = None
    if oracle_recall != no_recall:
        gap = (router_recall - no_recall) / (oracle_recall - no_recall)
    implicit_recall = _mean(implicit_recalls)
    gap_points = (router_recall - implicit_recall) * 100
    scale = _scale(RETRIEVE, project)
    result = {
        "label": "fixture backends, not live stores",
        "questions": len(questions),
        "implicit_questions": implicit_count,
        "p7": "not run",
        "recall_at_5": {
            "no_retrieve": no_recall,
            "oracle": oracle_recall,
            "router": router_recall,
            "implicit": implicit_recall,
        },
        "gap_closed": gap,
        "routing_accuracy": routed / len(questions) if questions else 0.0,
        "implicit_gap_points": gap_points,
        "k2_follow_up": gap_points >= 15,
        "scale": scale,
        "store_calls": len(calls),
    }
    OUT.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
