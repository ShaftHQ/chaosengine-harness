"""#8032 R3: a raised harness ceiling is flagged; a shrink is not."""

from __future__ import annotations

import importlib.util
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def load():
    path = ROOT / "scripts/ci/ceiling_raise.py"
    spec = importlib.util.spec_from_file_location("ceiling_raise_8032", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class CeilingRaiseTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.mod = load()

    def test_always_loaded_bytes_are_a_measurement_not_a_ceiling(self):
        base = '{"bytes": 100, "tolerance_pct": 5, "shrink_ratchet_pct": 10}'
        raised = '{"bytes": 120, "tolerance_pct": 5, "shrink_ratchet_pct": 10}'
        shrunk = '{"bytes": 80, "tolerance_pct": 4, "shrink_ratchet_pct": 10}'
        self.assertEqual([], self.mod.findings("always-loaded-budget.json", base, raised))
        self.assertEqual([], self.mod.findings("always-loaded-budget.json", base, shrunk))

    def test_a_lower_decision_score_or_a_removed_score_is_flagged(self):
        base = '{"scores": {"correctness": 4.0, "protective_fixtures": 4.0}, "tolerance": 0}'
        dropped = '{"scores": {"correctness": 1.0}, "tolerance": 1}'
        tighter = '{"scores": {"correctness": 5.0, "protective_fixtures": 4.0}, "tolerance": 0}'
        lines = self.mod.findings("docs/evidence/decision-quality-score.baseline.json", base, dropped)
        self.assertIn("docs/evidence/decision-quality-score.baseline.json: scores.correctness 4 -> 1", lines)
        self.assertIn("docs/evidence/decision-quality-score.baseline.json: scores.protective_fixtures removed", lines)
        self.assertIn("docs/evidence/decision-quality-score.baseline.json: tolerance 0 -> 1", lines)
        self.assertEqual([], self.mod.findings("docs/evidence/decision-quality-score.baseline.json", base, tighter))

    def test_an_unrelated_path_is_ignored(self):
        self.assertEqual([], self.mod.findings("README.md", "1", "2"))


if __name__ == "__main__":
    unittest.main()
