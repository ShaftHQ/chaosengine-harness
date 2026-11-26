"""Wave 2: cost-aware delegation and expert intake routing."""

from __future__ import annotations

import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


class Wave2DelegationIntakeTest(unittest.TestCase):
    def test_delegation_and_orchestrator_rules(self) -> None:
        delegation = (ROOT / "references" / "delegation.md").read_text(encoding="utf-8")
        roles = (ROOT / "references" / "roles.md").read_text(encoding="utf-8")
        workflows = (ROOT / "references" / "execution-workflows.md").read_text(encoding="utf-8")
        self.assertIn("## Cost-aware delegation & effort scaling", delegation)
        self.assertIn("cheapest qualified model", delegation)
        self.assertIn("Quota-exhaustion failover", delegation)
        self.assertIn("GitHub tracking issue", delegation)
        self.assertIn("does not implement when it is delegating", delegation)
        self.assertIn("cheapest capable model", roles)
        self.assertIn("file-disjoint", roles)
        self.assertIn("GitHub tracking issue", roles)
        self.assertIn("Sequential orchestrated mode (`ORCHESTRATOR + SINGLE IMPLEMENTER`) is the default", workflows)
        self.assertIn("zero overlapping writable paths", workflows)

    def test_expert_rephrasing_is_on_the_intake_path(self) -> None:
        skill = (ROOT / "skills" / "chaos-engine" / "SKILL.md").read_text(encoding="utf-8")
        bigger = (ROOT / "references" / "bigger-picture-first.md").read_text(encoding="utf-8")
        lifecycle = (ROOT / "hooks" / "lifecycle.py").read_text(encoding="utf-8")
        self.assertIn("rephrase it as a domain expert", skill)
        self.assertIn("## Expert requirement refinement & complexity routing", bigger)
        self.assertIn("vague requirements", bigger)
        self.assertIn("rephrase as a domain expert", lifecycle)
        self.assertIn("spec first", lifecycle)


if __name__ == "__main__":
    unittest.main()
