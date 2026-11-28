"""Docs drift fails a new CHAOS_ENGINE_* read and passes the committed tree."""

from __future__ import annotations

import importlib.util
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def load(name: str, relative: str):
    spec = importlib.util.spec_from_file_location(name, ROOT / relative)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class DocsDriftTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.drift = load("docs_drift_under_test", "scripts/ci/docs_drift.py")
        cls.gen = load("gen_reference_under_test", "scripts/docs/gen_reference.py")

    def test_clean_tree_has_no_docs_drift(self):
        self.assertEqual([], self.drift.gate_findings(ROOT, None))

    def test_new_env_read_fails_with_one_line_fix_next(self):
        import tempfile

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            runtime = root / "runtime"
            runtime.mkdir()
            (runtime / "env_registry.json").write_text(
                '{"schema": "ce-env/v1", "entries": []}\n',
                encoding="utf-8",
            )
            (runtime / "x.py").write_text(
                'import os\nos.environ.get("CHAOS_ENGINE_NEW_THING")\n',
                encoding="utf-8",
            )
            found = self.drift.gate_findings(root, ["runtime/x.py"])
        self.assertEqual(
            [
                "CHAOS_ENGINE_NEW_THING read at runtime/x.py:2 has no entry in "
                "runtime/env_registry.json; add it and run scripts/docs/gen_reference.py"
            ],
            found,
        )

    def test_unrelated_diff_skips_the_scan(self):
        self.assertEqual([], self.drift.gate_findings(ROOT, ["README.md"]))

    def test_generator_check_matches_committed_pages(self):
        self.assertEqual([], self.gen.check(ROOT))

    def test_agent_reference_is_dense_and_small(self):
        text = (ROOT / "docs/agents/reference.md").read_text(encoding="utf-8")
        self.assertLessEqual(len(text.encode("utf-8")), 32 * 1024)
        self.assertNotIn("```mermaid", text)
        self.assertNotIn("![", text)
        self.assertIn("[owner](", text)


if __name__ == "__main__":
    unittest.main()
