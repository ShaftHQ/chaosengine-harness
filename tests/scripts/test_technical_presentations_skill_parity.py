"""The technical-presentations skill is one on-demand source every host page reaches."""

from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts" / "ci"))

import harness_reachability as reach  # noqa: E402

BASE = "skills/technical-presentations"
SKILL = f"{BASE}/SKILL.md"
CARDS = [
    f"{BASE}/references/{name}.md"
    for name in ("plan", "slide", "technical", "teach", "review", "sources")
]
ROUTER = ROOT / "skills/chaos-engine/SKILL.md"
HOST_CONTEXTS = {
    "claude": ["guides/tools/claude.md"],
    "codex": ["guides/tools/codex.md"],
    "grok": ["guides/tools/grok.md"],
    "gemini": ["guides/tools/gemini.md"],
    "cursor": ["guides/tools/cursor.md"],
    "copilot": ["guides/tools/copilot.md"],
    "opencode": ["guides/tools/opencode.md"],
    "grok-bot": ["guides/tools/grok-bot.md", "references/bot-entry.md"],
    "openbot": ["guides/tools/openbot.md"],
    "antigravity": ["guides/overview.md"],
}


def _text(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


class TechnicalPresentationsParityTest(unittest.TestCase):
    def test_every_host_reaches_the_skill_and_every_card(self) -> None:
        data = json.loads(_text("scripts/ci/agent_harness_parity.json"))
        self.assertEqual(set(data["hosts"]), set(HOST_CONTEXTS))
        for host, contexts in HOST_CONTEXTS.items():
            reached: set[str] = set()
            for context in contexts:
                reached |= reach.link_walk(ROOT, context)[0]
            with self.subTest(host=host):
                self.assertEqual([], [path for path in [SKILL, *CARDS] if path not in reached])

    def test_one_source_no_host_copies(self) -> None:
        copies = [
            path for path in ROOT.glob("**/technical-presentations/SKILL.md")
            if ".chaos-engine" not in path.parts and ".git" not in path.parts
        ]
        self.assertEqual([ROOT / SKILL], copies)

    def test_parity_row_covers_every_host(self) -> None:
        data = json.loads(_text("scripts/ci/agent_harness_parity.json"))
        row = next(item for item in data["capabilities"] if item["id"] == "technical_presentations_skill")
        self.assertEqual({SKILL}, {path for host in data["hosts"] for path in row[host]})

    def test_on_demand_only_never_in_the_always_loaded_router(self) -> None:
        self.assertNotIn("technical-presentations", ROUTER.read_text(encoding="utf-8"))
        self.assertIn(
            "../skills/technical-presentations/SKILL.md",
            _text("references/level-1-catalog.md"),
        )

    def test_skill_opens_with_both_retrieves(self) -> None:
        body = _text(SKILL).split("## Card index", 1)[0]
        self.assertIn("--store graphify", body)
        self.assertIn("--store mempalace", body)

    def test_hard_rule_never_removes_existing_slide_content(self) -> None:
        rules = _text(SKILL).split("## Hard rules", 1)[1].split("\n## ", 1)[0].casefold()
        self.assertIn("never remove", rules)
        self.assertIn("skip slide", rules)
        self.assertIn("speaker notes", rules)
        self.assertIn("never modify the owner's source files", rules)
        self.assertIn("new file", rules)

    def test_editable_output_rule_and_gotchas(self) -> None:
        rules = _text(SKILL).split("## Hard rules", 1)[1].split("\n## ", 1)[0].casefold()
        self.assertIn("native charts", rules)
        self.assertIn("baked into an image", rules)
        gotchas = _text(f"{BASE}/references/review.md").split("## 15 Gotchas", 1)[1]
        for phrase in ('show="0"', "PDF export", "U+2B91", "Roboto Slab", "Lato", "file id"):
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, gotchas)

    def test_brand_neutral_with_a_palette_hook(self) -> None:
        self.assertIn("brand palette file if present", _text(SKILL))
        for path in [SKILL, *CARDS]:
            with self.subTest(path=path):
                text = _text(path)
                self.assertNotRegex(text, r"#[0-9A-Fa-f]{6}\b")
                self.assertNotIn("automatest", text.casefold())


if __name__ == "__main__":
    unittest.main()
