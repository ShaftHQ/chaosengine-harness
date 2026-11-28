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

    def test_new_catalog_row_names_the_key(self):
        import tempfile

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            runtime = root / "runtime"
            runtime.mkdir()
            (runtime / "install_options.py").write_text(
                "_opt(key='new.key', default=False, kind='bool', levels='U', help='New.')\n",
                encoding="utf-8",
            )
            found = self.drift.gate_findings(root, ["runtime/install_options.py"])
        self.assertEqual(
            ["new.key is missing optin or effect; set both on the InstallOption in runtime/install_options.py"],
            [item for item in found if item.startswith("new.key")],
        )

    def test_new_addon_id_names_the_flag(self):
        import tempfile

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            runtime = root / "runtime"
            runtime.mkdir()
            (runtime / "install_options.py").write_text('ADDON_IDS = ("brand-new",)\n', encoding="utf-8")
            (runtime / "env_registry.json").write_text(
                '{"schema": "ce-env/v1", "addon_flags": [], "entries": []}\n',
                encoding="utf-8",
            )
            found = self.drift.gate_findings(root, ["runtime/install_options.py"])
        self.assertEqual(
            [
                "addon id brand-new has no --with-brand-new flag row in "
                "runtime/env_registry.json; add it and run scripts/docs/gen_reference.py"
            ],
            found,
        )

    def test_new_stop_phrase_names_the_phrase(self):
        import tempfile

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            hooks = root / "hooks"
            hooks.mkdir()
            (hooks / "lifecycle.py").write_text(
                "def stopped_companion_names(text):\n"
                "    if 'stop newthing' in text:\n"
                "        return set()\n",
                encoding="utf-8",
            )
            (root / "references").mkdir()
            (root / "references" / "keywords.json").write_text(
                '{"schema": "ce-keywords/v1", "keywords": []}\n',
                encoding="utf-8",
            )
            found = self.drift.gate_findings(root, ["hooks/lifecycle.py"])
        self.assertEqual(
            [
                "stop phrase stop newthing at hooks/lifecycle.py:2 has no entry in "
                "references/keywords.json; add it and run scripts/docs/gen_reference.py"
            ],
            found,
        )

    def test_generator_check_matches_committed_pages(self):
        self.assertEqual([], self.gen.check(ROOT))

    def test_human_tree_has_nine_mermaid_diagrams(self):
        text = []
        for path in (ROOT / "docs").rglob("*.md"):
            text.append(path.read_text(encoding="utf-8"))
        self.assertGreaterEqual("".join(text).count("```mermaid"), 9)
        self.assertEqual([], self.drift.mermaid_findings(ROOT))

    def test_agent_reference_is_dense_and_small(self):
        text = (ROOT / "docs/agents/reference.md").read_text(encoding="utf-8")
        self.assertLessEqual(len(text.encode("utf-8")), 32 * 1024)
        self.assertNotIn("```mermaid", text)
        self.assertNotIn("![", text)
        self.assertIn("[owner](", text)


if __name__ == "__main__":
    unittest.main()
