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
        self.skill = (ROOT / "skills" / "chaos-engine" / "SKILL.md").read_text(encoding="utf-8")
        self.skill_lowered = self.skill.casefold()

        # Hardware inspection stays on the local skills. The ladder is not copied into them.
        self.assertIn("hardware", self.local_agency_lowered)
        self.assertIn("hardware", self.local_runtimes_lowered)
        self.assertIn("delegation ladder", self.local_agency_lowered)
        self.assertIn("delegation ladder", self.local_runtimes_lowered)

        # Opt-in, owner-approved setup: no silent/unprompted installs.
        self.assertRegex(self.local_agency_lowered, r"opt-in|owner-approved|explicitly agrees|explicitly agree|approval|explicit owner approval")
        self.assertRegex(self.local_agency_lowered, r"silent|unprompted")

        # The child skills point at the ladder. They do not restate writer selection.

        # No contradicting "never install" / "only narrow mechanical" wording.
        self.assertNotIn("never install", self.local_agency_lowered)
        self.assertNotIn("never install", self.local_runtimes_lowered)
        self.assertNotIn("only narrow mechanical", self.local_agency_lowered)
        self.assertNotIn("only narrow mechanical", self.local_runtimes_lowered)

    def test_proactive_small_work_item_decomposition_for_free_models(self) -> None:
        text = self.skill_lowered
        self.assertIn("decompos", text)
        self.assertRegex(text, r"small|bounded")
        self.assertIn("file-disjoint", text)
        self.assertIn("free", text)
        self.assertRegex(text, r"proactive|proactively")

    def test_smartest_free_local_model_at_highest_reasoning_effort_first(self) -> None:
        text = self.skill_lowered
        self.assertRegex(text, r"smartest")
        self.assertIn("highest available reasoning effort", text)
        self.assertIn("mechanical", text)

    def test_hardware_aware_local_model_recommendations_and_opt_in_setup(self) -> None:
        text = self.skill_lowered
        self.assertIn("hardware", text)
        self.assertRegex(text, r"ram|vram|cpu")
        self.assertRegex(text, r"explicit approval|explicitly agrees|explicitly agree")
        self.assertIn("install", text)
        self.assertIn("opencode", text)

    def test_paid_fallback_ladder_newest_cheapest_at_lowest_sufficient_effort(self) -> None:
        text = self.skill_lowered
        self.assertIn("paid", text)
        self.assertIn("nothing free is reachable", text)
        self.assertIn("cheapest", text)
        self.assertIn("newer generation", text)
        self.assertIn("lowest reasoning effort sufficient", text)
        self.assertIn("older generation", text)

    def test_router_sends_writers_to_free_models_before_host_subagents(self) -> None:
        skill = self.skill_lowered
        self.assertIn("delegation ladder", skill)
        self.assertIn("highest available reasoning effort", skill)
        self.assertIn("file scope", skill)
        self.assertIn("acceptance checks", skill)
        self.assertIn("test command", skill)
        self.assertIn("stop conditions", skill)
        self.assertIn("openbot", skill)
        self.assertIn("grok bot", skill)
        self.assertIn("antigravity", skill)
        self.assertIn("dispatch.py", skill)
        self.assertNotIn("default orchestrator labor", self.local_agency_lowered)
        dispatch = (ROOT / "skills" / "local-agency" / "scripts" / "dispatch.py").read_text(encoding="utf-8")
        self.assertIn('default="high"', dispatch)
        self.assertNotIn('default="medium"', dispatch)
        self.assertIn("_free_writer_block", dispatch)

    def test_writer_brief_is_required_and_host_subagent_is_not_the_default_writer(self) -> None:
        text = self.skill_lowered
        self.assertIn("not the default writer", text)
        self.assertIn("file scope", text)
        self.assertIn("acceptance checks", text)
        self.assertIn("test command", text)
        self.assertIn("stop conditions", text)
        self.assertIn("do not restate this ladder", text)

    def test_independent_adversarial_review_stays_on_host(self) -> None:
        text = self.skill_lowered
        self.assertIn("adversarial review", text)
        self.assertIn("fresh-context", text)

    def test_hosted_free_quota_does_not_skip_a_live_local_runtime(self) -> None:
        text = self.skill_lowered
        self.assertIn(
            'hosted free quota or usage failure is not "nothing free is reachable" while a local runtime answers',
            text,
        )
        self.assertIn(
            "continue on that local model at its highest available reasoning effort before any paid writer",
            text,
        )
        self.assertIn(
            "smaller-model rule applies only while a smarter free model is still reachable",
            text,
        )

    def test_best_judgment_after_a_dismissed_question_is_silence(self) -> None:
        text = self.skill_lowered
        self.assertIn("silence: do not dispatch", text)
        self.assertIn(
            "host message to continue with best judgment after a dismissed question is silence",
            text,
        )
        self.assertIn("not owner approval", text)

    def test_delegation_stall_is_not_log_silence_with_zero_edits(self) -> None:
        guide = (ROOT / "guides" / "local-agency.md").read_text(encoding="utf-8")
        for body in (self.delegation, self.local_agency, guide):
            self.assertNotIn("log silence with 0 edits", body)
            self.assertNotIn("after spawn", body)
            self.assertIn("no product-file change", body)
            self.assertIn("delegate-log progress", body)
            self.assertIn("valid paid receipt may edit", body)
            self.assertIn("own direct edit", body)
        self.assertNotIn("log silence with 0 edits", self.delegation)

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
