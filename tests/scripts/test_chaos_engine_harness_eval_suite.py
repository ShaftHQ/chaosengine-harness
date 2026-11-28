"""Harness eval suite: schema, pass@k report, and PR-gate wiring (#6519)."""

from __future__ import annotations

import json
import unittest
import unittest.mock
from pathlib import Path

import sys as _sys; from pathlib import Path as _Path; _sys.path.insert(0, str(_Path(__file__).resolve().parents[2]))  # noqa: E402,E702 - self-locating under python3 -I (#7197)
from scripts.ci.chaos_engine_harness_eval_suite import (
    evaluate_suite,
    evaluate_task,
    flakiness,
    load_manifest,
    pass_at_k,
    pass_pow_k,
    summarize_usage,
    validate_manifest,
    _run_pytest,
)

ROOT = Path(__file__).resolve().parents[2]
DOC = ROOT / "references/harness-eval-suite.md"
MANIFEST = ROOT / "evals/harness-suite/manifest.json"
CATALOG = ROOT / "references/zero-llm-catalog.md"


class HarnessEvalSuiteTests(unittest.TestCase):
    def test_manifest_schema_and_coverage(self):
        document = load_manifest(MANIFEST)
        defects = validate_manifest(document)
        self.assertEqual([], defects, msg=defects)
        self.assertEqual(1, document["schema_version"])
        self.assertGreaterEqual(len(document["tasks"]), 20)
        sets = {row["set"] for row in document["tasks"]}
        self.assertEqual({"capability", "regression"}, sets)
        areas = {row["area"] for row in document["tasks"]}
        self.assertLessEqual({"installer", "doctor", "entry", "hooks", "retrieve"}, areas)
        regression_issues = {
            row["source_issue"] for row in document["tasks"] if row["set"] == "regression"
        }
        self.assertGreaterEqual(len(regression_issues), 12)

    def test_pass_at_k_helper(self):
        self.assertEqual(1.0, pass_at_k([True]))
        self.assertEqual(0.0, pass_at_k([False]))
        self.assertEqual(1.0, pass_at_k([False, True]))
        self.assertEqual(0.0, pass_at_k([]))

    def test_pass_pow_k_and_flakiness(self):
        self.assertEqual(1.0, pass_pow_k([True]))
        self.assertEqual(0.0, pass_pow_k([False]))
        self.assertEqual(1.0, pass_pow_k([True, True, True]))
        self.assertEqual(0.0, pass_pow_k([True, False, True]))
        self.assertEqual(0.0, pass_pow_k([False, False, False]))
        self.assertEqual(0.0, pass_pow_k([]))
        self.assertEqual(0.0, flakiness([True]))
        self.assertEqual(0.0, flakiness([False, False, False]))
        self.assertEqual(1.0, flakiness([True, False, True]))
        self.assertEqual(1.0, pass_at_k([True, False, True]))

    def test_null_cost_is_unknown_and_not_summed(self):
        mixed = summarize_usage([{"cost_usd": None}, {"cost_usd": 2.5}])
        self.assertEqual("cost: unknown (1 of 2 trials unmeasured)", mixed)
        self.assertNotIn("2.5", mixed)
        self.assertEqual(
            "cost: 3.500000",
            summarize_usage([{"cost_usd": 1.5}, {"cost_usd": 2}]),
        )
        self.assertEqual(
            "cost: unknown (2 of 2 trials unmeasured)",
            summarize_usage([{"cost_usd": None}, {"cost_usd": None}]),
        )

    def test_k3_mixed_reports_pass_pow_and_flakiness(self):
        document = load_manifest(MANIFEST)
        tiny = {
            **document,
            "thresholds": {
                "pass_at_k": 1.0,  # nosec B105 - suite threshold, not a credential.
                "default_k": 1,
                "min_tasks": 1,
                "min_capability": 0,
                "min_regression": 1,
            },
            "tasks": [
                {
                    "id": "reg-mixed",
                    "set": "regression",
                    "area": "doctor",
                    "source_issue": 1,
                    "k": 3,
                    "runner": "unittest",
                    "module": "tests.scripts.test_chaos_engine_ce_brief_eval_fixtures",
                }
            ],
        }
        outcomes = [(True, "ok"), (False, "no"), (True, "ok")]
        with unittest.mock.patch(
            "scripts.ci.chaos_engine_harness_eval_suite._run_unittest",
            side_effect=outcomes,
        ):
            report = evaluate_suite(tiny, root=ROOT)
        row = report["results"][0]
        self.assertEqual(1.0, row["pass_at_k"])
        self.assertEqual(0.0, row["pass_pow_k"])
        self.assertEqual(1.0, row["flakiness"])
        self.assertEqual(1.0, report["pass_at_k"])
        self.assertEqual(0.0, report["pass_pow_k"])
        self.assertEqual(1.0, report["flakiness"])
        self.assertIn("unknown", report["cost"])
        self.assertIsNone(row["attempts"][0]["usage"]["cost_usd"])
        self.assertIsInstance(row["attempts"][0]["usage"]["wall_s"], float)

    def test_k3_all_pass_and_all_fail(self):
        self.assertEqual((1.0, 1.0, 0.0), (pass_at_k([True, True, True]), pass_pow_k([True, True, True]), flakiness([True, True, True])))
        task = {
            "id": "reg-all-fail",
            "set": "regression",
            "area": "doctor",
            "source_issue": 1,
            "k": 3,
            "runner": "unittest",
            "module": "tests.scripts.does_not_run",
        }
        with unittest.mock.patch(
            "scripts.ci.chaos_engine_harness_eval_suite._run_unittest",
            return_value=(False, "no"),
        ):
            row = evaluate_task(task, root=ROOT, default_k=1, timeout=5)
        self.assertEqual(0.0, row["pass_at_k"])
        self.assertEqual(0.0, row["pass_pow_k"])
        self.assertEqual(0.0, row["flakiness"])
        self.assertFalse(row["passed"])

    def test_documented_runner_and_gate(self):
        text = DOC.read_text(encoding="utf-8")
        self.assertIn("scripts/ci/chaos_engine_harness_eval_suite.py", text)
        self.assertIn("pass@k", text)
        self.assertIn("capability", text)
        self.assertIn("regression", text)
        self.assertIn("harness-eval-suite-contract", text)
        catalog = CATALOG.read_text(encoding="utf-8")
        self.assertIn("chaos_engine_harness_eval_suite.py", catalog)

    def test_runner_executes_a_live_module(self):
        document = load_manifest(MANIFEST)
        task = next(row for row in document["tasks"] if row["id"] == "cap-ce-brief-fixtures")
        tiny = {
            **document,
            "thresholds": {
                "pass_at_k": 1.0,  # nosec B105 - suite threshold, not a credential.
                "default_k": 1,
                "min_tasks": 1,
                "min_capability": 1,
                "min_regression": 0,
            },
            "tasks": [task],
        }
        report = evaluate_suite(tiny, root=ROOT, timeout=90)
        self.assertEqual([], report["defects"], msg=report["defects"])
        self.assertTrue(report["passed"], msg=json.dumps(report["results"], indent=2)[:4000])
        self.assertEqual(1.0, report["pass_at_k"])
        self.assertEqual(1.0, report["pass_pow_k"])
        self.assertEqual(0.0, report["flakiness"])
        self.assertEqual(1.0, report["case_pass_rate"])
        usage = report["results"][0]["attempts"][0]["usage"]
        self.assertIsNone(usage["input_tokens"])
        self.assertIsNone(usage["output_tokens"])
        self.assertIsNone(usage["cost_usd"])
        self.assertGreaterEqual(usage["wall_s"], 0.0)
        self.assertIn("unknown", report["cost"])

    def test_pytest_runner_executes_a_live_module(self):
        ok, output = _run_pytest(
            "tests.scripts.test_chaos_engine_ce_brief_eval_fixtures",
            root=ROOT,
            timeout=90,
        )
        self.assertTrue(ok, msg=output[-2000:])

    def test_validate_rejects_empty_corpus(self):
        document = {
            "schema_version": 1,
            "package": "chaos-engine",
            "thresholds": {
                "pass_at_k": 1.0,  # nosec B105 - suite threshold, not a credential.
                "default_k": 1,
                "min_tasks": 20,
                "min_capability": 6,
                "min_regression": 12,
            },
            "tasks": [],
        }
        defects = validate_manifest(document)
        self.assertTrue(any("tasks" in item for item in defects))

    def test_evaluate_suite_reports_failure(self):
        document = load_manifest(MANIFEST)
        tiny = {
            **document,
            "thresholds": {
                "pass_at_k": 1.0,  # nosec B105 - suite threshold, not a credential.
                "default_k": 1,
                "min_tasks": 1,
                "min_capability": 0,
                "min_regression": 1,
            },
            "tasks": [
                {
                    "id": "reg-fake",
                    "set": "regression",
                    "area": "doctor",
                    "source_issue": 1,
                    "k": 1,
                    "runner": "unittest",
                    "module": "tests.scripts.does_not_exist_module",
                }
            ],
        }
        with unittest.mock.patch(
            "scripts.ci.chaos_engine_harness_eval_suite._run_unittest",
            return_value=(False, "boom"),
        ):
            report = evaluate_suite(tiny, root=ROOT)
        self.assertFalse(report["passed"])
        self.assertEqual(0.0, report["pass_at_k"])


if __name__ == "__main__":
    unittest.main()
