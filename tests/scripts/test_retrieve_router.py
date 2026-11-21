"""Scope router: Graphify exit 3/4, miss fallback, cap, and reciprocal rank fusion."""

from __future__ import annotations

import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[2]
QUESTIONS = ROOT / "experiments" / "retrieve-router" / "questions.json"


def _load(name: str, relative: str):
    path = ROOT / relative
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"unable to load {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def _project() -> Path:
    root = Path(tempfile.mkdtemp())
    package = root / "chaos-engine"
    package.mkdir()
    (package / "tool.py").write_text("# tool\n", encoding="utf-8")
    runtime = root / "runtime"
    runtime.mkdir()
    (runtime / "keep.py").write_text("def keep():\n    return 1\n", encoding="utf-8")
    return root


class RetrieveRouterTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.retrieve = _load("ce_retrieve_router", "runtime/retrieve.py")
        cls.split = _load("ce_corpus_split_router", "runtime/corpus_split.py")

    def _run(self, project: Path, query: str, responder):
        with (
            mock.patch.object(self.retrieve.subprocess, "run", side_effect=responder),
            mock.patch.object(self.retrieve, "_tool_py", return_value=project / "chaos-engine" / "tool.py"),
            mock.patch.object(self.retrieve, "_record_store_outcome"),
        ):
            return self.retrieve.retrieve(query, project=project)

    def test_classifier_matches_the_frozen_routes(self):
        payload = json.loads(QUESTIONS.read_text(encoding="utf-8"))
        questions = payload["questions"]
        self.assertGreaterEqual(len(questions), 20)
        implicit = 0
        for item in questions:
            route = self.retrieve.classify_scope(item["question"])
            self.assertEqual(item["gold_route"], route["reason"], item["id"])
            gold = item["gold"][0]
            line = (ROOT / gold["path"]).read_text(encoding="utf-8").splitlines()[gold["line"] - 1]
            self.assertIn(item["expect"], line)
            blob = f"{gold['path']} {line}"
            if self.retrieve.implicit_clue(item["question"], blob):
                implicit += 1
                self.assertTrue(item["implicit"], item["id"])
            else:
                self.assertFalse(item["implicit"], item["id"])
        self.assertGreaterEqual(implicit, 10)

    def test_graphify_exit_3_requeries_once_with_the_top_candidate(self):
        project = _project()
        calls: list[list[str]] = []

        def responder(args, **kwargs):
            calls.append(list(args))
            if len(calls) == 1:
                return mock.Mock(
                    returncode=3,
                    stdout="",
                    stderr=(
                        "Ambiguous: 'pick_store' matches 2 nodes in different files.\n"
                        "  runtime/keep.py\n"
                        "    id: node-alpha\n"
                        "  runtime/other.py\n"
                        "    id: node-beta\n"
                    ),
                )
            return mock.Mock(
                returncode=0,
                stdout="NODE pick_store [src=runtime/keep.py loc=L1\n",
                stderr="",
            )

        receipt = self._run(project, "who calls pick_store", responder)
        store_calls = _store_calls(calls)
        self.assertEqual(2, len(store_calls))
        self.assertIn("node-alpha", store_calls[1])
        self.assertNotIn("node-beta", store_calls[1])
        self.assertEqual("used", receipt["status"])
        self.assertEqual("symbol-impact", receipt["route"]["reason"])
        self.assertLessEqual(len(receipt["hits"]), 8)

    def test_graphify_exit_4_is_a_miss_and_falls_back_once(self):
        project = _project()
        calls: list[list[str]] = []

        def responder(args, **kwargs):
            calls.append(list(args))
            return mock.Mock(returncode=4, stdout="", stderr="No unique node match for pick_store")

        receipt = self._run(project, "who calls pick_store", responder)
        self.assertEqual(2, len(_store_calls(calls)))
        self.assertNotEqual("degraded", receipt["status"])
        self.assertIn(receipt["reason"], {"no-node", "no-relevant-hits", "ambiguous", "ambiguous-unparsed"})

    def test_error_does_not_fall_back(self):
        project = _project()
        calls: list[list[str]] = []

        def responder(args, **kwargs):
            calls.append(list(args))
            return mock.Mock(returncode=2, stdout="", stderr="graphify exploded")

        receipt = self._run(project, "who calls pick_store", responder)
        self.assertEqual(1, len(_store_calls(calls)))
        self.assertEqual("degraded", receipt["status"])

    def test_backend_mismatch_does_not_fall_back(self):
        project = _project()
        calls: list[list[str]] = []

        def responder(args, **kwargs):
            calls.append(list(args))
            return mock.Mock(returncode=1, stdout="", stderr="backend mismatch")

        receipt = self._run(project, "why did we decide the palace layout", responder)
        self.assertEqual(1, len(_store_calls(calls)))
        self.assertEqual("degraded", receipt["status"])
        self.assertEqual("backend-mismatch", receipt["reason"])

    def test_empty_memory_falls_back_to_mempalace(self):
        project = _project()
        calls: list[list[str]] = []

        def responder(args, **kwargs):
            calls.append(list(args))
            if "memory" in args:
                return mock.Mock(returncode=0, stdout="No results found\n", stderr="")
            return mock.Mock(returncode=0, stdout="runtime/keep.py:1:def keep\n", stderr="")

        receipt = self._run(project, "has this constraint bitten us", responder)
        self.assertEqual(["memory", "mempalace"], [_store_name(call) for call in _store_calls(calls)])
        self.assertEqual("used", receipt["status"])
        self.assertEqual("mempalace", receipt["hits"][0]["store"])
        self.assertEqual("gotcha", receipt["hits"][0]["route"])
        self.assertEqual(1, receipt["hits"][0]["line"])
        self.assertIn("score", receipt["hits"][0])

    def test_absent_path_is_dropped(self):
        project = _project()

        def responder(args, **kwargs):
            return mock.Mock(
                returncode=0,
                stdout="missing/nope.py:3:x\nruntime/keep.py:1:def keep\n",
                stderr="",
            )

        receipt = self._run(project, "has this constraint bitten us", responder)
        self.assertEqual(["runtime/keep.py"], [hit["path"] for hit in receipt["hits"]])

    def test_cap_is_eight_hits_and_800_bytes(self):
        project = _project()
        lines = []
        for index in range(20):
            relative = f"runtime/f{index}.py"
            (project / relative).write_text("def item():\n    return 1\n", encoding="utf-8")
            lines.append(f"{relative}:1:def item\n")
        body = "".join(lines) + ("x" * 5000)

        def responder(args, **kwargs):
            return mock.Mock(returncode=0, stdout=body, stderr="")

        groups = [
            [
                {"path": f"runtime/f{index}.py", "line": 1, "store": "memory", "route": "gotcha"}
                for index in range(20)
            ]
        ]
        fused = self.retrieve.reciprocal_rank_fusion(groups)
        self.assertEqual(8, len(fused))
        receipt = self._run(project, "has this constraint bitten us", responder)
        self.assertLessEqual(len(receipt["hits"]), 8)
        self.assertLessEqual(receipt["bytes"], 800)
        self.assertLessEqual(len(receipt["excerpt"].encode("utf-8")), 800)

    def test_rrf_ranks_the_shared_hit_first(self):
        fused = self.retrieve.reciprocal_rank_fusion(
            [
                [
                    {"path": "a.py", "line": 1, "store": "memory", "route": "gotcha"},
                    {"path": "b.py", "line": 2, "store": "memory", "route": "gotcha"},
                ],
                [
                    {"path": "b.py", "line": 2, "store": "mempalace", "route": "gotcha"},
                    {"path": "c.py", "line": 3, "store": "mempalace", "route": "gotcha"},
                ],
            ]
        )
        self.assertEqual("b.py", fused[0]["path"])
        self.assertGreater(fused[0]["score"], fused[1]["score"])
        self.assertEqual("mempalace", fused[0]["store"])

    def test_depth_budget_wing_and_results_are_passed(self):
        project = _project()
        (project / "mempalace.yaml").write_text("wing: harness\n", encoding="utf-8")
        calls: list[list[str]] = []

        def responder(args, **kwargs):
            calls.append(list(args))
            return mock.Mock(returncode=4, stdout="", stderr="No unique node match")

        self._run(project, "who calls pick_store", responder)
        affected = calls[0]
        self.assertIn("affected", affected)
        self.assertIn("--depth", affected)
        self.assertEqual("2", affected[affected.index("--depth") + 1])

        calls.clear()

        def history(args, **kwargs):
            calls.append(list(args))
            return mock.Mock(returncode=0, stdout="No results found\n", stderr="")

        self._run(project, "why did we decide the palace layout", history)
        search = calls[0]
        self.assertIn("mempalace", search)
        self.assertIn("--wing", search)
        self.assertEqual("harness", search[search.index("--wing") + 1])
        self.assertIn("--results", search)
        self.assertEqual("5", search[search.index("--results") + 1])

        calls.clear()

        def explain(args, **kwargs):
            calls.append(list(args))
            return mock.Mock(returncode=0, stdout="No results found\n", stderr="")

        self._run(project, "explain the module", explain)
        query = calls[0]
        self.assertIn("query", query)
        self.assertIn("--budget", query)
        self.assertEqual("1500", query[query.index("--budget") + 1])

    def test_dry_run_records_route_reason(self):
        receipt = self.retrieve.retrieve("has this constraint bitten us", dry_run=True)
        self.assertEqual("memory", receipt["store"])
        self.assertEqual("gotcha", receipt["route"]["reason"])
        self.assertEqual("two-store-on-miss", receipt["policy"])


def _store_calls(calls: list[list[str]]) -> list[list[str]]:
    return [call for call in calls if _store_name(call)]


def _store_name(argv: list[str]) -> str:
    for name in ("memory", "mempalace", "graphify"):
        if name in argv:
            return name
    return ""


if __name__ == "__main__":
    unittest.main()
