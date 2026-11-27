"""The delegation ladder is one router section, enforced on every hook host."""

from __future__ import annotations

import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {path}")
    module = importlib.util.module_from_spec(spec)
    import sys
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


GATE = load("ce_delegation_gate_test", ROOT / "hooks" / "delegation_gate.py")
KERNEL = load("ce_kernel_delegation_test", ROOT / "hooks" / "kernel.py")

BRIEF = "\n".join(
    [
        "goal: fix the parser",
        "file scope: rules/operation_boundary.py",
        "behavior to preserve: true force pushes stay refused",
        "acceptance checks: the new tests fail before the fix",
        "test command: python3 -m pytest -q tests/scripts/test_delete_guard_parser_and_marker_251.py",
        "stop conditions: stop if another production file is required",
    ]
)


class DelegationReceiptTest(unittest.TestCase):
    def _receipt(self, root: Path, **overrides: object) -> dict:
        payload = {
            "rung": "free",
            "effort": "high",
            "free": "selected",
            "why": "smartest reachable free model",
            "mechanical": False,
            "escalated": False,
            "prior": "",
            "tier": "cheapest",
            "brief_ok": True,
            "brief": "",
            "root": root.resolve().as_posix(),
            "recorded_at": 1_000.0,
        }
        payload.update(overrides)
        path = GATE.receipt_path(root)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload), encoding="utf-8")
        return payload

    def test_host_writer_is_refused_without_a_paid_receipt(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "skills" / "chaos-engine").mkdir(parents=True)
            (root / "skills" / "chaos-engine" / "SKILL.md").write_text("x", encoding="utf-8")
            reason = GATE.writer_block(
                "spawn_subagent",
                {"subagent_type": "chaos-engine-implementer", "prompt": "implement the fix"},
                (),
                root,
                now=1_000.0,
            )
            self.assertIn("record a receipt", reason or "")
            self._receipt(root, rung="paid", free="too-complex", effort="low")
            self.assertIsNone(
                GATE.writer_block(
                    "spawn_subagent",
                    {"subagent_type": "chaos-engine-implementer", "prompt": "implement the fix"},
                    (),
                    root,
                    now=1_000.0,
                )
            )

    def _brief(self, root: Path, text: str = BRIEF) -> str:
        path = root / "brief.md"
        path.write_text(text, encoding="utf-8")
        return path.resolve().as_posix()

    def test_free_opencode_requires_high_effort_and_a_free_receipt(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "skills" / "chaos-engine").mkdir(parents=True)
            (root / "skills" / "chaos-engine" / "SKILL.md").write_text("x", encoding="utf-8")
            brief = self._brief(root)
            self._receipt(root, brief=brief)
            blocked = GATE.writer_block(
                "run_terminal_command",
                {},
                (f"opencode run --variant medium --model example {brief}",),
                root,
                now=1_000.0,
            )
            self.assertIn("--variant high", blocked or "")
            self.assertIsNone(
                GATE.writer_block(
                    "run_terminal_command",
                    {},
                    (f"opencode run --variant high --model example {brief}",),
                    root,
                    now=1_100.0,
                )
            )

    def test_unlabeled_host_spawns_need_a_paid_receipt(self) -> None:
        prompts = (
            ("Task", {"subagent_type": "general-purpose", "prompt": "Fix hooks/guard.py and add the regression test."}),
            ("spawn_subagent", {"prompt": "Edit hooks/delegation_gate.py so unlabeled spawns are refused."}),
            ("Task", {"prompt": "Implement the parser fix. Do not edit unrelated files."}),
            ("Agent", {"agent_type": "coder", "prompt": "change the gate"}),
        )
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            for tool, payload in prompts:
                with self.subTest(tool=tool, prompt=payload.get("prompt")):
                    reason = GATE.writer_block(tool, payload, (), root, now=1_000.0)
                    self.assertIn("record a receipt", reason or "")

    def test_read_only_spawn_is_not_a_writer(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self.assertIsNone(
                GATE.writer_block(
                    "spawn_subagent",
                    {"prompt": "Read the file. Do not edit."},
                    (),
                    root,
                    now=1_000.0,
                )
            )

    def test_direct_edit_needs_rung_direct(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "skills" / "chaos-engine").mkdir(parents=True)
            (root / "skills" / "chaos-engine" / "SKILL.md").write_text("x", encoding="utf-8")
            reason = GATE.writer_block("Write", {"path": "rules/operation_boundary.py"}, (), root, now=1_000.0)
            self.assertIn("rung=direct", reason or "")
            for tool in (
                "write_to_file",
                "replace_file_content",
                "multi_replace_file_content",
                "create_file",
                "replace_string_in_file",
            ):
                with self.subTest(tool=tool):
                    missed = GATE.writer_block(tool, {"path": "rules/operation_boundary.py"}, (), root, now=1_000.0)
                    self.assertIn("rung=direct", missed or "")
            self._receipt(root, rung="direct", free="not-applicable", effort="low", brief_ok=True)
            self.assertIsNone(
                GATE.writer_block("Edit", {"path": "rules/operation_boundary.py"}, (), root, now=1_000.0)
            )

    def test_free_receipt_is_bound_to_its_brief_and_variant(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "skills" / "chaos-engine").mkdir(parents=True)
            (root / "skills" / "chaos-engine" / "SKILL.md").write_text("x", encoding="utf-8")
            brief = self._brief(root)
            self._receipt(root, brief=brief)
            unrelated = GATE.writer_block(
                "run_terminal_command",
                {},
                ("opencode run --variant high --prompt other",),
                root,
                now=1_000.0,
            )
            self.assertIn("brief file", unrelated or "")
            low = GATE.writer_block(
                "run_terminal_command",
                {},
                (f"dispatch.py argv --variant low {brief}",),
                root,
                now=1_000.0,
            )
            self.assertIn("--variant high", low or "")
            self._receipt(root, brief=brief, mechanical=True, effort="medium")
            medium = GATE.writer_block(
                "run_terminal_command",
                {},
                (f"opencode run --variant medium {brief}",),
                root,
                now=1_000.0,
            )
            self.assertIn("mechanical", medium or "")

    def test_reviewer_spawn_is_not_a_writer(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self.assertIsNone(
                GATE.writer_block(
                    "spawn_subagent",
                    {"subagent_type": "chaos-engine-reviewer", "prompt": "adversarial review"},
                    (),
                    root,
                    now=1_000.0,
                )
            )

    def test_paid_effort_starts_low_until_escalated(self) -> None:
        payload = {
            "rung": "paid",
            "effort": "high",
            "free": "too-complex",
            "why": "the free writer failed the acceptance checks",
            "mechanical": False,
            "escalated": False,
            "prior": "",
            "tier": "cheapest",
            "brief_ok": True,
        }
        self.assertIn("starts at low", GATE.validate(payload) or "")
        payload["escalated"] = True
        payload["prior"] = "low effort missed the acceptance check"
        self.assertIsNone(GATE.validate(payload))

    def test_brief_markers_are_required(self) -> None:
        self.assertTrue(GATE.brief_ok(BRIEF))
        self.assertFalse(GATE.brief_ok("implement the issue"))


class AllHostsShareTheGateTest(unittest.TestCase):
    def test_every_hook_host_registers_pretooluse(self) -> None:
        expected = {"codex", "claude", "gemini", "grok", "copilot", "cursor", "opencode", "antigravity"}
        self.assertEqual(expected, set(KERNEL.HOST_CAPABILITIES))
        for name, capability in KERNEL.HOST_CAPABILITIES.items():
            with self.subTest(host=name):
                self.assertIn("PreToolUse", capability.supported_events)

    def test_shared_guard_and_matchers_cover_writer_tools(self) -> None:
        guard = (ROOT / "hooks" / "guard.py").read_text(encoding="utf-8")
        self.assertIn("def _delegation_block", guard)
        self.assertIn("delegation_gate", guard)
        matchers = json.loads((ROOT / "hooks" / "matchers.json").read_text(encoding="utf-8"))
        preventive = " ".join(matchers["preventive"])
        for tool in ("spawn_subagent", "spawn_agent", "Task", "run_terminal_command", "Bash", "search_replace"):
            with self.subTest(tool=tool):
                self.assertIn(tool, preventive)

    def test_hookless_clients_receive_the_same_ladder(self) -> None:
        entry = (ROOT / "references" / "bot-entry.md").read_text(encoding="utf-8")
        self.assertIn("Grok Bot", entry)
        self.assertIn("OpenBot", entry)
        self.assertIn("delegation ladder", entry.casefold())
        lifecycle = (ROOT / "hooks" / "lifecycle.py").read_text(encoding="utf-8")
        self.assertIn("Delegation ladder:", lifecycle)
        dispatch = (ROOT / "skills" / "local-agency" / "scripts" / "dispatch.py").read_text(encoding="utf-8")
        self.assertIn("_free_writer_block", dispatch)

    def test_ladder_prose_has_one_source(self) -> None:
        skill = (ROOT / "skills" / "chaos-engine" / "SKILL.md").read_text(encoding="utf-8")
        self.assertEqual(1, skill.count("### Delegation ladder"))
        self.assertIn("highest available reasoning effort", skill)
        for relative in (
            "references/delegation.md",
            "references/roles.md",
            "skills/local-agency/SKILL.md",
            "skills/local-runtimes/SKILL.md",
            "guides/local-agency.md",
        ):
            body = (ROOT / relative).read_text(encoding="utf-8")
            with self.subTest(path=relative):
                self.assertNotIn("highest available reasoning effort", body)
                self.assertIn("delegation ladder", body.casefold())


if __name__ == "__main__":
    unittest.main()
