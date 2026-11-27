"""Issue #252: free-first, hardware-aware local model & newest-cheapest paid fallback delegation policy."""

from __future__ import annotations

import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


class FreeFirstDelegation252Test(unittest.TestCase):
    def setUp(self) -> None:
        self.delegation = (ROOT / "references" / "delegation.md").read_text(encoding="utf-8")
        self.lowered = self.delegation.casefold()
        self.local_agency = (ROOT / "skills" / "local-agency" / "SKILL.md").read_text(encoding="utf-8")
        self.local_agency_lowered = self.local_agency.casefold()
        self.local_runtimes = (ROOT / "skills" / "local-runtimes" / "SKILL.md").read_text(encoding="utf-8")
        self.local_runtimes_lowered = self.local_runtimes.casefold()

        # Hardware inspection is documented in both skills.
        self.assertIn("hardware", self.local_agency_lowered)
        self.assertIn("hardware", self.local_runtimes_lowered)

        # Opt-in, owner-approved setup: no silent/unprompted installs.
        self.assertRegex(self.local_agency_lowered, r"opt-in|owner-approved|explicitly agrees|explicitly agree|approval|explicit owner approval")
        self.assertRegex(self.local_agency_lowered, r"silent|unprompted")

        # Smartest free/local model at highest reasoning effort.
        self.assertRegex(self.local_agency_lowered, r"smartest free|smartest .* free")
        self.assertIn("highest", self.local_agency_lowered)
        self.assertRegex(self.local_runtimes_lowered, r"highest reasoning effort|highest effort|smartest free")

        # No contradicting "never install" / "only narrow mechanical" wording.
        self.assertNotIn("never install", self.local_agency_lowered)
        self.assertNotIn("never install", self.local_runtimes_lowered)
        self.assertNotIn("only narrow mechanical", self.local_agency_lowered)
        self.assertNotIn("only narrow mechanical", self.local_runtimes_lowered)

    def test_proactive_small_work_item_decomposition_for_free_models(self) -> None:
        text = self.lowered
        self.assertIn("decompos", text)
        self.assertRegex(text, r"small|bounded")
        self.assertIn("file-disjoint", text)
        self.assertIn("free", text)
        self.assertRegex(text, r"proactive|proactively")

    def test_smartest_free_local_model_at_highest_reasoning_effort_first(self) -> None:
        text = self.lowered
        self.assertRegex(text, r"smartest free|smartest free/local|smartest .* free")
        self.assertIn("highest available reasoning effort", text)
        self.assertRegex(text, r"smaller|dumbed-down|dumbed down")
        self.assertIn("mechanical", text)

    def test_hardware_aware_local_model_recommendations_and_opt_in_setup(self) -> None:
        text = self.lowered
        self.assertIn("hardware", text)
        self.assertRegex(text, r"ram|vram|cpu")
        self.assertIn("recommend", text)
        self.assertRegex(text, r"opt-in|opt in|owner-approved|owner approved|explicitly agrees|explicitly agree")
        self.assertRegex(text, r"install|set up|setup")
        self.assertRegex(text, r"local coding|coding cli|local agent")

    def test_paid_fallback_ladder_newest_cheapest_at_lowest_sufficient_effort(self) -> None:
        text = self.lowered
        self.assertIn("paid", text)
        self.assertIn("fallback", text)
        self.assertRegex(text, r"no free|no local|declines|decline")
        self.assertIn("cheapest", text)
        self.assertRegex(text, r"newest[- ]?generation|newest generation")
        self.assertRegex(text, r"lowest .*sufficient|lowest task-appropriate|lowest sufficient")
        self.assertRegex(text, r"older generation")

    def test_router_sends_writers_to_free_models_before_host_subagents(self) -> None:
        skill = (ROOT / "skills" / "chaos-engine" / "SKILL.md").read_text(encoding="utf-8").casefold()
        self.assertIn("free-first delegation", skill)
        self.assertIn("highest reasoning effort", skill)
        self.assertIn("paid fallback", skill)
        self.assertIn("file scope", skill)
        self.assertIn("acceptance checks", skill)
        self.assertIn("test command", skill)
        self.assertIn("stop conditions", skill)
        self.assertNotIn("default orchestrator labor", (ROOT / "skills" / "local-agency" / "SKILL.md").read_text(encoding="utf-8").casefold())
        dispatch = (ROOT / "skills" / "local-agency" / "scripts" / "dispatch.py").read_text(encoding="utf-8")
        self.assertIn('default="high"', dispatch)
        self.assertNotIn('default="medium"', dispatch)

    def test_writer_brief_is_required_and_host_subagent_is_not_the_default_writer(self) -> None:
        text = self.lowered
        self.assertIn("not the default writer", text)
        self.assertIn("file scope", text)
        self.assertIn("acceptance checks", text)
        self.assertIn("test command", text)
        self.assertIn("stop conditions", text)

    def test_independent_adversarial_review_stays_on_host(self) -> None:
        text = self.lowered
        self.assertIn("adversarial review", text)
        self.assertRegex(text, r"fresh-context|fresh context|host.*most.intelligent|most-intelligent")

    def test_no_vendor_lock_in_terms_introduced(self) -> None:
        for forbidden in (
            r"\bopenai\b",
            r"\banthropic\b",
            r"\bclaude[-_0-9]",
            r"\bgpt[-_0-9]",
            r"\bgemini[-_0-9]",
            r"\bdeepseek\b",
            r"\bqwen\b",
            r"\bgrok\b",
            r"\bopenrouter\b",
        ):
            self.assertIsNone(
                re.search(forbidden, self.lowered),
                f"references/delegation.md must stay vendor-neutral; matched {forbidden}",
            )

if __name__ == "__main__":
    unittest.main()
