"""Locators the always-loaded bot entry must keep (#7731, this checkout).

The SHAFT_ENGINE orphan inventory stays in that repository. This file keeps
the gate locators that bot-entry, the core card, and the delegate card must
still satisfy after the always-loaded shrink.
"""

from __future__ import annotations

import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


class EntryCoverageTest(unittest.TestCase):
    def test_bigger_picture_first_is_the_first_bot_entry_step(self) -> None:
        bot = (ROOT / "references/bot-entry.md").read_text(encoding="utf-8")
        skill = (ROOT / "skills/chaos-engine/SKILL.md").read_text(encoding="utf-8")
        section = bot.split("## Every task, before discovery", 1)[1].split("\n## ", 1)[0]
        step1: list[str] = []
        started = False
        for line in section.splitlines():
            if not started:
                if line.startswith("1. "):
                    started = True
                    step1.append(line)
                continue
            if line[:1].isdigit() and line[1:3] == ". ":
                break
            step1.append(line)
        first = "\n".join(step1)
        self.assertTrue(first.startswith("1. "), first)
        for needle in (
            "bigger-picture-first.md",
            "goal",
            "larger context",
            "local hotfix",
            "review comment",
            "CI failure",
            "just hotfix it",
        ):
            self.assertIn(needle, first, needle)
        self.assertNotIn("tool.py retrieve", first)
        self.assertLess(section.find(first), section.find("tool.py retrieve"))
        law = skill.split("1. Measure thrice", 1)[1].split("\n2. ", 1)[0]
        self.assertLess(law.find("step back"), law.find("research and plan before the first edit"))
        self.assertIn("research and plan before the first edit", law)
        self.assertIn("## Bigger picture first", skill)
        self.assertIn("../../references/bigger-picture-first.md", skill)
        self.assertIn("what a local hotfix", skill.split("## Triage", 1)[0])
        worker = (
            ROOT / "skills/local-agency/scripts/worker_ce_entry.py"
        ).read_text(encoding="utf-8")
        self.assertNotIn("bigger-picture", worker)
        self.assertNotIn("bigger_picture", worker)

    def test_delegate_card_steps_back_before_retrieve(self) -> None:
        card = (ROOT / "references/delegate-card.md").read_text(encoding="utf-8")
        self.assertLess(card.find("## Bigger picture first"), card.find("## Retrieve first"))
        beat = card.split("## Retrieve first", 1)[0]
        for needle in ("bigger-picture-first.md", "goal", "larger context", "local hotfix"):
            self.assertIn(needle, beat, needle)

    def test_entry_coverage_file_is_named_from_bot_entry(self) -> None:
        bot = (ROOT / "references/bot-entry.md").read_text(encoding="utf-8")
        self.assertIn("tests/scripts/test_ce_entry_coverage.py", bot)
        self.assertIn(".agents/skills/README.md", bot)


if __name__ == "__main__":
    unittest.main()
