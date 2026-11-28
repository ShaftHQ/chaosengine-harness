"""Issue #328: local rung, same-model split, and the pull-request watch."""

from __future__ import annotations

import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SKILL = ROOT / "skills" / "chaos-engine" / "SKILL.md"


def ladder_text(skill: str) -> str:
    start = skill.index("### Delegation ladder")
    end = skill.index("## Check and deliver")
    return skill[start:end]


class DelegationRule328Test(unittest.TestCase):
    def setUp(self) -> None:
        self.skill = SKILL.read_text(encoding="utf-8")
        self.ladder = ladder_text(self.skill)
        self.folded = self.ladder.casefold()

    def test_non_mechanical_implementation_is_off_the_mandatory_local_rung(self) -> None:
        self.assertIn(
            "non-mechanical implementation is off the mandatory local rung",
            self.folded,
        )

    def test_same_model_high_subagent_is_a_context_split(self) -> None:
        self.assertIn("same-model high subagent is a context split", self.folded)

    def test_timed_follow_up_is_replaced_by_the_pull_request_watch(self) -> None:
        self.assertIn("scripts/agents/watch_pr_checks.py", self.ladder)
        self.assertRegex(self.folded, r"3[-–]5 minute stall check")
        self.assertIn(
            "timed follow-up agent is replaced by the pull-request watch",
            self.folded,
        )

    def test_the_watch_is_not_told_to_schedule_a_timed_follow_up(self) -> None:
        folded = self.skill.casefold()
        self.assertNotIn("schedule a timed follow-up agent", folded)
        self.assertIsNone(
            re.search(
                r"(?:pull-request watch|watch_pr_checks\.py)[\s\S]{0,400}schedule a timed follow-up agent",
                folded,
            )
        )


if __name__ == "__main__":
    unittest.main()
