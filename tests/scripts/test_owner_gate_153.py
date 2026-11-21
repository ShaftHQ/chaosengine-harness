"""#153: record one unverifiable owner gate and do not poll it again."""

from __future__ import annotations

import importlib.util
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def _load():
    path = ROOT / "runtime" / "owner_gate.py"
    spec = importlib.util.spec_from_file_location("ce_owner_gate_153", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class OwnerGateTest(unittest.TestCase):
    def setUp(self):
        self.gate = _load()

    def _decide(self, blocker: str, **overrides: object) -> dict:
        payload = {
            "blocker": blocker,
            "session_can_create": False,
            "only_remaining": True,
            "already_recorded": "",
        }
        payload.update(overrides)
        return self.gate.decide_owner_gate(**payload)

    def test_rendered_proof_is_recorded_once_and_ends_the_goal(self):
        blocker = "rendered proof for Windows Terminal"
        first = self._decide(blocker)
        self.assertEqual("blocking: unverifiable", first["blocking"])
        self.assertTrue(first["end_goal"])
        self.assertTrue(first["record"])
        self.assertFalse(first["new_work"])
        self.assertFalse(first["poll"])
        self.assertEqual("", first["ask"])
        again = self._decide(blocker, already_recorded=blocker)
        self.assertEqual("blocking: unverifiable", again["blocking"])
        self.assertTrue(again["end_goal"])
        self.assertFalse(again["record"])
        self.assertFalse(again["new_work"])
        self.assertFalse(again["poll"])

    def test_voice_and_visual_artifacts_are_the_same_stop(self):
        for blocker in ("voice recording", "visual sign-off"):
            decision = self._decide(blocker)
            self.assertEqual("blocking: unverifiable", decision["blocking"])
            self.assertTrue(decision["end_goal"])
            self.assertEqual("", decision["ask"])

    def test_a_gate_the_session_can_create_stays_work(self):
        decision = self._decide("rendered proof", session_can_create=True)
        self.assertEqual("", decision["blocking"])
        self.assertFalse(decision["end_goal"])
        self.assertTrue(decision["new_work"])
        self.assertFalse(decision["record"])

    def test_other_remaining_work_is_not_an_owner_gate(self):
        decision = self._decide("missing unit test")
        self.assertEqual("", decision["blocking"])
        self.assertFalse(decision["end_goal"])
        self.assertTrue(decision["new_work"])

    def test_the_decision_does_not_ask_the_owner_to_accept(self):
        decision = self._decide("visual sign-off")
        folded = decision["ask"].casefold()
        self.assertNotIn("sign", folded)
        self.assertNotIn("approve", folded)
        self.assertNotIn("visually accept", folded)
        source = (ROOT / "runtime" / "owner_gate.py").read_text(encoding="utf-8")
        self.assertNotIn("while ", source)

    def test_delivery_references_point_at_the_gate(self):
        for relative in (
            "references/delivery-cycle.md",
            "references/delivery-phase-gates.md",
            "references/bot-entry.md",
        ):
            text = (ROOT / relative).read_text(encoding="utf-8")
            self.assertIn("blocking: unverifiable", text)
            self.assertIn("runtime/owner_gate.py", text)


if __name__ == "__main__":
    unittest.main()
