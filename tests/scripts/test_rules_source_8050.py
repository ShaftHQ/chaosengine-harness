"""#8047 and #8050: one rules source, thin entries, closest AGENTS.md wins.

Tests call hosts.load_project_agents and rules_source.policy_drift.
"""

from __future__ import annotations

import importlib.util
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def load(path: Path, name: str):
    specification = importlib.util.spec_from_file_location(name, path)
    if specification is None or specification.loader is None:
        raise RuntimeError(f"cannot load {path}")
    module = importlib.util.module_from_spec(specification)
    specification.loader.exec_module(module)
    return module


class RulesSourceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.hosts = load(ROOT / "runtime" / "hosts.py", "ce_hosts_8050")
        cls.rules = load(ROOT / "runtime" / "rules_source.py", "ce_rules_source_8050")

    def test_published_list_matches_writers_and_the_doc(self):
        doc = ROOT / "references" / "rules-source.md"
        text = doc.read_text(encoding="utf-8")
        self.assertIn("skills/chaos-engine/SKILL.md", text)
        self.assertIn("identity.md", text)
        published = self.rules.GENERATED_ENTRY_FILES
        self.assertEqual(published, self.rules.documented_generated_set(doc))
        self.assertEqual(set(published), set(self.rules.entry_writers()))
        self.assertEqual([], self.rules.unlisted_entry_files(published))
        self.assertEqual(["NEW_HOST.md"], self.rules.unlisted_entry_files([*published, "NEW_HOST.md"]))

    def test_generated_files_share_one_sentence_until_one_is_edited(self):
        bodies = self.rules.generated_entry_bodies()
        self.assertEqual([], self.rules.policy_drift(bodies))
        self.assertEqual(b"@AGENTS.md\n", bodies["CLAUDE.md"].encode())
        self.assertEqual(b"@AGENTS.md\n", bodies["GEMINI.md"].encode())
        self.assertNotIn("Before every task, follow the canonical", bodies[".codex/hooks.json"])
        self.assertNotIn("Before every task, follow the canonical", bodies[".grok/hooks/lifecycle.json"])
        stale = dict(bodies)
        stale["AGENTS.md"] = bodies["AGENTS.md"].replace("Before every task", "Before some tasks")
        drifted = self.rules.policy_drift(stale)
        self.assertTrue(any(item.startswith("AGENTS.md:") for item in drifted))
        hand = dict(bodies)
        hand["CLAUDE.md"] = "Follow a different policy sentence.\n"
        self.assertTrue(any(item.startswith("CLAUDE.md:") for item in self.rules.policy_drift(hand)))
        copied = dict(bodies)
        copied[".grok/hooks/lifecycle.json"] = bodies[".grok/hooks/lifecycle.json"] + bodies["AGENTS.md"]
        self.assertTrue(any("copied policy sentence" in item for item in self.rules.policy_drift(copied)))

    def test_user_text_outside_the_marker_is_preserved(self):
        before = b"Project tests use pytest.\n"
        merged = self.hosts.merge_instruction(
            before, self.hosts.instruction_block(), relative="AGENTS.md",
        ).decode("utf-8")
        self.assertIn("Project tests use pytest.", merged)
        self.assertIn("Before every task", merged)
        self.assertLess(merged.index(self.hosts.START), merged.index("Project tests use pytest."))

    def test_closest_agents_file_wins_and_nested_files_are_not_written(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "AGENTS.md").write_text(
                "Build: make root\n" + self.hosts.instruction_block(), encoding="utf-8",
            )
            package = root / "packages" / "app"
            package.mkdir(parents=True)
            nested = package / "AGENTS.md"
            nested.write_text("Build: pytest packages/app\n", encoding="utf-8")
            original = nested.read_bytes()
            edited = package / "main.py"
            loaded = self.hosts.load_project_agents(root, edited)
            self.assertIn("make root", loaded)
            self.assertIn("pytest packages/app", loaded)
            self.assertGreater(loaded.rfind("pytest packages/app"), loaded.rfind("make root"))
            self.assertNotIn("CHAOSENGINE:START", loaded)
            self.assertEqual(original, nested.read_bytes())
            self.assertNotIn("packages/app/AGENTS.md", self.hosts.managed_paths())

    def test_missing_agents_file_is_empty_and_root_only_stays_root(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self.assertEqual("", self.hosts.load_project_agents(root, root / "src" / "a.py"))
            (root / "AGENTS.md").write_text(self.hosts.instruction_block(), encoding="utf-8")
            self.assertEqual("", self.hosts.load_project_agents(root, root / "src" / "a.py"))
            (root / "AGENTS.md").write_text("Only root\n", encoding="utf-8")
            self.assertEqual("Only root", self.hosts.load_project_agents(root, root / "src" / "a.py"))


if __name__ == "__main__":
    unittest.main()
