"""#153: record one unverifiable owner gate and do not poll it again."""

from __future__ import annotations

import importlib.util
import json
import tempfile
import unittest
import uuid
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

    def test_apply_persists_the_blocker_once(self):
        import tempfile

        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "owner-gate.json"
            first = self.gate.apply_owner_gate(
                path,
                blocker="rendered proof for Windows Terminal",
                session_can_create=False,
                only_remaining=True,
            )
            self.assertTrue(first["record"])
            self.assertTrue(first["end_goal"])
            second = self.gate.apply_owner_gate(
                path,
                blocker="rendered proof for Windows Terminal",
                session_can_create=False,
                only_remaining=True,
            )
            self.assertFalse(second["record"])
            self.assertTrue(second["end_goal"])
            self.assertFalse(second["new_work"])
            self.assertEqual("", second["ask"])

    def test_delivery_references_point_at_the_gate(self):
        for relative in (
            "references/delivery-cycle.md",
            "references/delivery-phase-gates.md",
            "references/bot-entry.md",
        ):
            text = (ROOT / relative).read_text(encoding="utf-8")
            self.assertIn("blocking: unverifiable", text)
            self.assertIn("runtime/owner_gate.py", text)


def _load_guard():
    path = ROOT / "hooks" / "guard.py"
    spec = importlib.util.spec_from_file_location("ce_guard_stop_153", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module._deny = lambda event, event_name, tool_name, reason: 2
    return module


class StopPathTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.guard = _load_guard()
        cls.gate = _load()

    def _open_pr(self, root: Path) -> None:
        state = root / ".chaos-engine-state"
        state.mkdir(parents=True)
        (state / "open-pull-request.json").write_text(
            json.dumps({"active": True, "state": "open", "pullRequest": 157}) + "\n",
            encoding="utf-8",
        )

    def _stop(self, root: Path, message: str):
        session_id = "owner-gate-" + uuid.uuid4().hex
        event = {
            "hook_event_name": "Stop",
            "cwd": str(root),
            "session_id": session_id,
            "last_assistant_message": message,
        }
        return self.guard._stop_block(event, "Stop", "", session_id)

    def test_a_short_owner_artifact_yields_the_open_pull_request_once(self):
        message = "rendered proof for the frame"
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self._open_pr(root)
            reason = self.guard._open_pull_request_reason("unused-session", {
                "cwd": str(root),
                "hook_event_name": "Stop",
            })
            self.assertTrue(
                reason.startswith("Delivery is not complete while the pull request is open.")
            )
            self.assertIsNone(self._stop(root, message))
            path = root / ".chaos-engine-state" / "owner-gate.json"
            written = path.read_bytes()
            again = self.gate.apply_owner_gate(
                path,
                blocker=message,
                session_can_create=False,
                only_remaining=True,
            )
            self.assertEqual("blocking: unverifiable", again["blocking"])
            self.assertFalse(again["record"])
            self.assertIsNone(self._stop(root, message))
            self.assertEqual(written, path.read_bytes())

    def test_a_long_essay_that_mentions_the_artifact_stays_denied(self):
        essay = "rendered proof " + ("still open " * 20)
        self.assertGreater(len(essay), 120)
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self._open_pr(root)
            self.assertEqual(2, self._stop(root, essay))
            self.assertFalse((root / ".chaos-engine-state" / "owner-gate.json").exists())

    def test_an_ordinary_stop_still_denies_the_open_pull_request(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self._open_pr(root)
            self.assertEqual(2, self._stop(root, "checks are still running"))
            self.assertFalse((root / ".chaos-engine-state" / "owner-gate.json").exists())


if __name__ == "__main__":
    unittest.main()
