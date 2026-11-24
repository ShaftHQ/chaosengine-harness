"""#222: skill-listing budget is enforced, and the human Mermaid docs parse."""

from __future__ import annotations

import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
HOSTS = (
    "claude",
    "codex",
    "copilot",
    "gemini",
    "grok",
    "opencode",
    "cursor",
    "antigravity",
    "grok-bot",
)


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise ImportError(path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


class SkillListingBudgetEnforcementTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.skills = _load(
            "ce_listing_budget_skills", ROOT / "scripts/ci/validate_skills.py"
        )
        cls.index = _load(
            "ce_listing_budget_index", ROOT / "runtime/harness_index.py"
        )
        cls.readme = _load(
            "ce_listing_budget_readme", ROOT / "scripts/ci/validate_chaos_engine_readme.py"
        )

    def test_every_host_glob_is_wired_and_the_listing_is_under_the_cap(self):
        budget = json.loads(
            (ROOT / "scripts/ci/agent_guidance_budget.json").read_text(encoding="utf-8")
        )
        globs = budget["host_skill_metadata_globs"]
        self.assertEqual(set(HOSTS), set(globs))
        for host in HOSTS:
            self.assertEqual(["skills/*/SKILL.md"], globs[host], host)
        self.assertEqual([], self.index.listing_overflows(ROOT))
        self.assertEqual([], self.skills.check_listing_budget(ROOT))

    def test_check_listing_budget_fails_when_a_temp_tree_exceeds_the_cap(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            budget_dir = root / "scripts/ci"
            budget_dir.mkdir(parents=True)
            (budget_dir / "agent_guidance_budget.json").write_text(
                json.dumps(
                    {
                        "max_skill_listing_chars": 30,
                        "host_skill_metadata_globs": {
                            "codex": ["skills/*/SKILL.md"],
                        },
                    }
                ),
                encoding="utf-8",
            )
            skill = root / "skills/demo/SKILL.md"
            skill.parent.mkdir(parents=True)
            skill.write_text(
                "---\n"
                "name: demo\n"
                "description: Use when this fixture exceeds the configured skill listing ceiling.\n"
                "---\n"
                "# demo\n",
                encoding="utf-8",
            )
            findings = self.skills.check_listing_budget(root)
        self.assertTrue(findings)
        self.assertIn("listing overflow", findings[0])
        self.assertIn("host=codex", findings[0])
        self.assertIn("ceiling=30", findings[0])
        self.assertGreater(
            int(findings[0].split("count=", 1)[1].split(" ", 1)[0]),
            30,
        )

    def test_architecture_mermaid_includes_the_nine_host_launch_path(self):
        architecture = (ROOT / "guides/architecture.md").read_text(encoding="utf-8")
        titles, errors = self.readme._parse_mermaid(architecture)
        self.assertEqual([], errors)
        self.assertIn("Nine host launch path", titles)
        for title in (
            "Prerequisite and dependency topology",
            "Skill topology",
            "Five-host lifecycle topology",
            "Fresh installation flow",
            "Managed upgrade and repair flow",
            "Dependency provisioning flow",
            "POSIX symlink and Windows junction flow",
            "Rollback flow",
            "Ownership and foreign-file preservation flow",
            "Lifecycle terminal-state flow",
        ):
            self.assertIn(title, titles)
        report = self.readme.validate(ROOT)
        self.assertFalse(
            any("Mermaid" in item or "topology" in item for item in report),
            report,
        )

    def test_human_docs_name_the_new_diagrams(self):
        overview = (ROOT / "guides/overview.md").read_text(encoding="utf-8")
        self.assertIn("mindmap", overview)
        self.assertIn("Delivery and verification cycle", overview)
        self.assertIn("## What it does", overview)
        starter = (ROOT / "guides/start-tester.md").read_text(encoding="utf-8")
        self.assertIn("Tester evidence router", starter)

    def test_l1_skill_cards_stay_within_the_byte_cap(self):
        self.assertLessEqual(
            (ROOT / "skills/ci-cd/SKILL.md").stat().st_size, 3200
        )
        self.assertLessEqual(
            (ROOT / "skills/self-improve/SKILL.md").stat().st_size, 3200
        )


if __name__ == "__main__":
    unittest.main()
