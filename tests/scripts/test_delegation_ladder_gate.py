"""The delegation ladder is one router section, enforced on every hook host."""

from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import tempfile
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

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
        prompts = (
            "Read the file. Do not edit.",
            "Read hooks/delegation_gate.py and report whether classify returns host-writer.",
            "Do not change any files. Only read and report.",
        )
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            for prompt in prompts:
                with self.subTest(prompt=prompt):
                    self.assertIsNone(
                        GATE.writer_block(
                            "spawn_subagent",
                            {"prompt": prompt},
                            (),
                            root,
                            now=1_000.0,
                        )
                    )

    def test_a_disclaimer_does_not_hide_the_edit(self) -> None:
        prompts = (
            "Modify hooks/delegation_gate.py. Do not edit unrelated files.",
            "Refactor the parser. Do not edit unrelated files.",
            "Create the missing regression test. Do not edit unrelated files.",
            "Implement the parser fix. Do not edit unrelated files.",
        )
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            for prompt in prompts:
                with self.subTest(prompt=prompt):
                    reason = GATE.writer_block("Task", {"prompt": prompt}, (), root, now=1_000.0)
                    self.assertIn("record a receipt", reason or "")

    def test_the_last_variant_is_the_effort_that_counts(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "skills" / "chaos-engine").mkdir(parents=True)
            (root / "skills" / "chaos-engine" / "SKILL.md").write_text("x", encoding="utf-8")
            brief = self._brief(root)
            self._receipt(root, brief=brief)
            slipped = GATE.writer_block(
                "run_terminal_command",
                {},
                (f"opencode run --variant high --variant low {brief}",),
                root,
                now=1_000.0,
            )
            self.assertIn("--variant high", slipped or "")

    def test_mechanical_free_writer_allows_low_effort(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "skills" / "chaos-engine").mkdir(parents=True)
            (root / "skills" / "chaos-engine" / "SKILL.md").write_text("x", encoding="utf-8")
            brief = self._brief(root, BRIEF + "\nmechanical: true\n")
            payload = self._receipt(root, brief=brief, mechanical=True, effort="low")
            self.assertIsNone(GATE.validate(payload))
            self.assertIsNone(
                GATE.writer_block(
                    "run_terminal_command",
                    {},
                    (f"opencode run --variant low {brief}",),
                    root,
                    now=1_000.0,
                )
            )

    def test_opencode_run_help_is_not_free_writer(self) -> None:
        self.assertIsNone(GATE.classify("run_terminal_command", {}, ("opencode run --help",)))
        self.assertIsNone(GATE.classify("run_terminal_command", {}, ("opencode run -h",)))
        self.assertIsNone(
            GATE.classify("Bash", {"command": "opencode run --help 2>&1 | head -n 20"}, ())
        )
        self.assertEqual(
            "free-writer",
            GATE.classify("run_terminal_command", {}, ('opencode run --help "edit foo.py"',)),
        )
        self.assertEqual(
            "free-writer",
            GATE.classify(
                "run_terminal_command",
                {},
                ("opencode run --help && opencode run --variant high brief.md",),
            ),
        )

    def test_paid_receipt_with_valid_brief_allows_subagent_direct_edit(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "skills" / "chaos-engine").mkdir(parents=True)
            (root / "skills" / "chaos-engine" / "SKILL.md").write_text("x", encoding="utf-8")
            brief = self._brief(root)
            self._receipt(root, rung="paid", free="too-complex", effort="low", brief=brief, brief_ok=True)
            self.assertIsNone(
                GATE.writer_block("edit_file", {"path": "hooks/guard.py"}, (), root, now=1_000.0)
            )
            self._receipt(root, rung="free", free="selected", effort="high", brief=brief, brief_ok=True)
            denied = GATE.writer_block("edit_file", {"path": "hooks/guard.py"}, (), root, now=1_000.0)
            self.assertIn("rung=direct", denied or "")

    def test_dispatch_carries_the_receipt_brief(self) -> None:
        dispatch = load(
            "ce_dispatch_brief_test",
            ROOT / "skills" / "local-agency" / "scripts" / "dispatch.py",
        )
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "skills" / "chaos-engine").mkdir(parents=True)
            (root / "skills" / "chaos-engine" / "SKILL.md").write_text("x", encoding="utf-8")
            brief = self._brief(root)
            missing = SimpleNamespace(project=str(root), prompt="apply the change", workdir=None)
            refused = dispatch._free_writer_block(missing, "opencode run --variant high")
            self.assertIn("record a receipt", refused or "")
            self._receipt(root, brief=brief, recorded_at=time.time())
            argv = SimpleNamespace(project=str(root), prompt="apply the change", workdir=None)
            self.assertIsNone(dispatch._free_writer_block(argv, "opencode run --variant high"))
            self.assertIn(brief, argv.prompt)
            chat = SimpleNamespace(project=str(root), prompt="apply the change", workdir=None)
            self.assertIsNone(dispatch._free_writer_block(chat, "dispatch.py argv"))
            self.assertIn(brief, chat.prompt)

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

    def test_runtime_failure_prose_follows_the_ladder(self) -> None:
        paths = (
            "skills/local-runtimes/references/freetoken.md",
            "skills/local-runtimes/references/omniroute.md",
            "skills/local-runtimes/references/local-openai-compat.md",
            "skills/local-agency/scripts/dispatch.py",
        )
        for relative in paths:
            body = (ROOT / relative).read_text(encoding="utf-8")
            with self.subTest(path=relative):
                self.assertNotIn("native implementer", body)
                self.assertNotIn("session agents", body)
                self.assertIn("delegation ladder", body.casefold())

    def test_a_quoted_mention_is_not_a_free_writer(self) -> None:
        mentioned = "python3 -c 'print(\"opencode run\")'"
        self.assertIsNone(GATE.classify("run_terminal_command", {}, (mentioned,)))
        self.assertEqual(
            "free-writer",
            GATE.classify("run_terminal_command", {}, ("opencode run --variant high",)),
        )


    def _review(self, root: Path, prompt: str) -> str | None:
        return GATE.writer_block(
            "spawn_subagent",
            {"subagent_type": "chaos-engine-reviewer", "prompt": prompt},
            (),
            root,
            now=1_000.0,
        )

    def test_a_third_adversarial_review_of_one_subject_is_refused(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "skills" / "chaos-engine").mkdir(parents=True)
            (root / "skills" / "chaos-engine" / "SKILL.md").write_text("x", encoding="utf-8")
            prompt = "Read-only adversarial review. Do not edit. review-subject: ChaosEngine/one"
            self.assertIsNone(self._review(root, prompt))
            self.assertIsNone(self._review(root, prompt))
            denied = self._review(root, prompt)
            self.assertIn("ChaosEngine/one", denied or "")
            self.assertIn("two adversarial reviews", denied or "")
            self.assertIn("Close the class", denied or "")
            other = "Read-only adversarial review. Do not edit. review-subject: ChaosEngine/two"
            self.assertIsNone(self._review(root, other))

    def test_an_unscoped_review_chain_stops_at_two(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            prompt = "Read-only adversarial review. Do not edit."
            self.assertIsNone(self._review(root, prompt))
            self.assertIsNone(self._review(root, prompt))
            denied = self._review(root, prompt)
            self.assertIn("unscoped", denied or "")
            self.assertIn("review-subject", denied or "")

    def test_a_worktree_path_in_the_prompt_is_its_own_subject(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            repo = root / "repo"
            repo.mkdir()
            subprocess.run(
                ["git", "init", "-b", "ChaosEngine/sample"],
                cwd=repo,
                check=True,
                capture_output=True,
            )
            prompt = f"Read-only adversarial review. Do not edit. Look at {repo}"
            self.assertIsNone(self._review(root, prompt))
            self.assertIsNone(self._review(root, prompt))
            denied = self._review(root, prompt)
            self.assertIn("ChaosEngine/sample", denied or "")

    def test_downstream_pretooluse_denial_does_not_consume_review_round(self) -> None:
        guard = load("ce_guard_review_chain_test", ROOT / "hooks" / "guard.py")
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "skills" / "chaos-engine").mkdir(parents=True)
            (root / "skills" / "chaos-engine" / "SKILL.md").write_text("x", encoding="utf-8")
            prompt = "Read-only adversarial review. Do not edit. review-subject: ChaosEngine/downstream"
            tool_input = {"subagent_type": "chaos-engine-reviewer", "prompt": prompt}
            self.assertIsNone(
                GATE.writer_block("spawn_subagent", tool_input, (), root, now=1_000.0, commit_review=False)
            )
            rounds_file = root / GATE.REVIEW_ROUNDS_NAME
            self.assertFalse(rounds_file.exists())

            event = {
                "hook_event_name": "PreToolUse",
                "session_id": "s2-review",
                "cwd": str(root),
                "tool_name": "spawn_subagent",
                "tool_input": tool_input,
            }
            with mock.patch.object(guard, "_kernel_block", return_value=(2, None)):
                rc = guard._run_event(event, "claude")
                self.assertEqual(2, rc)
            self.assertFalse(rounds_file.exists())

            with (
                mock.patch.object(guard, "_kernel_block", return_value=(None, None)),
                mock.patch.object(guard, "_command_guard_state", return_value=(False, False, "")),
                mock.patch.object(guard, "_open_pr_pretool", return_value=("", None)),
            ):
                rc_ok = guard._run_event(event, "claude")
                self.assertEqual(0, rc_ok)
            saved = json.loads(rounds_file.read_text(encoding="utf-8"))
            self.assertEqual(1, saved["subjects"]["ChaosEngine/downstream"])

    def test_owner_session_lift_via_receipt_and_env(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "skills" / "chaos-engine").mkdir(parents=True)
            (root / "skills" / "chaos-engine" / "SKILL.md").write_text("x", encoding="utf-8")
            prompt = "Read-only adversarial review. Do not edit. review-subject: ChaosEngine/lifted"

            # Smaller/invalid review_cap is rejected and never lowers default cap below 2.
            bad_rc = GATE.main(
                [
                    "record",
                    "--rung", "direct",
                    "--effort", "low",
                    "--free", "not-applicable",
                    "--why", "invalid cap",
                    "--review-cap", "1",
                    "--root", str(root),
                ]
            )
            self.assertEqual(2, bad_rc)

            ok_rc = GATE.main(
                [
                    "record",
                    "--rung", "direct",
                    "--effort", "low",
                    "--free", "not-applicable",
                    "--why", "owner lifted review cap",
                    "--review-cap", "4",
                    "--root", str(root),
                ]
            )
            self.assertEqual(0, ok_rc)
            for _ in range(4):
                self.assertIsNone(self._review(root, prompt))
            denied = self._review(root, prompt)
            self.assertIn("4 adversarial reviews", denied or "")

            prompt_env = "Read-only adversarial review. Do not edit. review-subject: ChaosEngine/env-lifted"
            GATE.receipt_path(root).unlink()
            with mock.patch.dict(os.environ, {GATE.REVIEW_CAP_LIFT_ENV: "3"}):
                for _ in range(3):
                    self.assertIsNone(self._review(root, prompt_env))
                denied_env = self._review(root, prompt_env)
                self.assertIn("3 adversarial reviews", denied_env or "")

    def test_the_review_chain_is_in_the_router_and_the_cycle(self) -> None:
        skill = (ROOT / "skills" / "chaos-engine" / "SKILL.md").read_text(encoding="utf-8")
        cycle = (ROOT / "references" / "delivery-cycle.md").read_text(encoding="utf-8")
        delegation = (ROOT / "references" / "delegation.md").read_text(encoding="utf-8")
        self.assertIn("The gate refuses another.", skill)
        self.assertIn("A second failed review ends the chain", skill)
        self.assertIn("PDCA cap is 3, not a quota", skill)
        self.assertIn("The gate refuses a third.", cycle)
        self.assertIn("MAX = MIN", cycle)
        self.assertIn("at most 3", cycle)
        self.assertNotIn("both reviews repeat", delegation)
        self.assertIn("does not repeat both reviews", delegation)


if __name__ == "__main__":
    unittest.main()
