"""The architect skill is one source every host page reaches (no per-host copies)."""

from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts" / "ci"))

import harness_reachability as reach  # noqa: E402

SKILL = "skills/architect/SKILL.md"
CARDS = [
    f"skills/architect/references/{name}.md"
    for name in ("analyze", "design", "operate", "change", "sources")
]
# Host pages in this tree are the published guides. Antigravity has no tool
# page; guides/overview.md is the page that maps that id onto AGENTS.md.
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


class ArchitectParityTest(unittest.TestCase):
    def test_every_host_reaches_the_skill_and_every_card(self) -> None:
        data = json.loads((ROOT / "scripts/ci/agent_harness_parity.json").read_text(encoding="utf-8"))
        self.assertEqual(set(data["hosts"]), set(HOST_CONTEXTS))
        for host, contexts in HOST_CONTEXTS.items():
            reached: set[str] = set()
            for context in contexts:
                reached |= reach.link_walk(ROOT, context)[0]
            with self.subTest(host=host):
                self.assertEqual([], [path for path in [SKILL, *CARDS] if path not in reached])

    def test_one_source_no_host_copies(self) -> None:
        copies = [
            path for path in ROOT.glob("**/architect/SKILL.md")
            if ".chaos-engine" not in path.parts and ".git" not in path.parts
        ]
        self.assertEqual([ROOT / SKILL], copies)

    def test_parity_row_covers_every_host(self) -> None:
        data = json.loads((ROOT / "scripts/ci/agent_harness_parity.json").read_text(encoding="utf-8"))
        row = next(item for item in data["capabilities"] if item["id"] == "architect_skill")
        self.assertEqual({SKILL}, {path for host in data["hosts"] for path in row[host]})

    def test_skill_opens_with_both_retrieves(self) -> None:
        body = (ROOT / SKILL).read_text(encoding="utf-8").split("## Tier", 1)[0]
        self.assertIn("--store graphify", body)
        self.assertIn("--store mempalace", body)


if __name__ == "__main__":
    unittest.main()
