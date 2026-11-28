"""Hook exit-2 / hard-block fidelity across five hosts (#5579)."""

from __future__ import annotations

import importlib.util
import io
import json
import sys
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
MATRIX = ROOT / "references/host-parity-matrix.md"


def load_module(name: str, relative: str):
    path = ROOT / relative
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {relative}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class Exit2FidelityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.kernel = load_module("ce_kernel_exit2", "hooks/kernel.py")
        cls.lifecycle = load_module(
            "ce_lifecycle_exit2", "hooks/lifecycle.py"
        )

    def test_host_capability_declares_blocking_contract(self):
        expected_honored = {
            "claude": True,
            "codex": True,
            "gemini": True,
            "grok": True,
            "copilot": False,
            "cursor": False,
            "opencode": False,
            "antigravity": False,
        }
        expected_mechanism = {
            "claude": "exit_2",
            "codex": "permission_decision",
            "gemini": "decision_json",
            "grok": "decision_json",
            "copilot": "permission_decision",
            "cursor": "permission_decision",
            "opencode": "throw",
            "antigravity": "decision_json",
        }
        expected_exit = {
            "claude": 2,
            "codex": 2,
            "gemini": 2,
            "grok": 2,
            "copilot": 2,
            "cursor": 2,
            "opencode": 2,
            "antigravity": 0,
        }
        for host, capability in self.kernel.HOST_CAPABILITIES.items():
            with self.subTest(host=host):
                self.assertEqual(expected_exit[host], capability.deny_exit_code)
                self.assertEqual(expected_mechanism[host], capability.hard_block_mechanism)
                self.assertEqual(expected_honored[host], capability.process_exit2_honored)
                if capability.process_exit2_honored:
                    self.assertEqual("", capability.blocking_gap)
                else:
                    self.assertIn("GAP-EXIT2", capability.blocking_gap)

    def test_protocol_deny_returns_exit_two_with_native_payload(self):
        expected_deny = {
            "codex": {
                "hookSpecificOutput": {
                    "hookEventName": "PreToolUse",
                    "permissionDecision": "deny",
                    "permissionDecisionReason": "fixture-deny",
                }
            },
            "claude": {"decision": "block", "reason": "fixture-deny"},
            "gemini": {"decision": "block", "reason": "fixture-deny"},
            "grok": {"decision": "block", "reason": "fixture-deny"},
            "copilot": {
                "permissionDecision": "deny",
                "permissionDecisionReason": "fixture-deny",
            },
            "cursor": {
                "permission": "deny",
                "user_message": "fixture-deny",
                "agent_message": "fixture-deny",
            },
            "opencode": {"decision": "block", "reason": "fixture-deny"},
            "antigravity": {"decision": "deny", "reason": "fixture-deny"},
        }

        def deny_callback(_event, _host):
            print(json.dumps({"decision": "block", "reason": "fixture-deny"}))
            return 2

        for host in self.kernel.HOST_CAPABILITIES:
            with self.subTest(host=host):
                stdout = io.StringIO()
                stderr = io.StringIO()
                with redirect_stdout(stdout), redirect_stderr(stderr):
                    code = self.lifecycle.run_hook_protocol(
                        json.dumps(
                            {
                                "hook_event_name": "PreToolUse",
                                "tool_name": "Bash",
                                "tool_input": {"command": "true"},
                            }
                        ),
                        {"PreToolUse": deny_callback},
                        normalize=self.kernel.normalize_hook_input,
                        host_for_input=lambda _raw, selected=host: selected,
                        adapt_output=self.kernel.adapt_hook_output,
                    )
                # The protocol returns the callback code. Antigravity's process
                # exit 0 is applied in guard.main so the host reads the JSON.
                self.assertEqual(2, code)
                rendered = stderr.getvalue() if host == "claude" else stdout.getvalue()
                self.assertTrue(rendered.strip(), msg=f"empty payload host={host}")
                payload = json.loads(rendered.strip().splitlines()[-1])
                self.assertEqual(expected_deny[host], payload)

    def test_matrix_documents_gap_exit2_for_thin_hosts(self):
        text = MATRIX.read_text(encoding="utf-8")
        self.assertIn("GAP-EXIT2", text)
        self.assertIn("process_exit2_honored", text)
        self.assertIn("test_chaos_engine_exit2_fidelity.py", text)
        marker = "GAP-EXIT2-SENTENCE:"
        sentence = next(
            line[len(marker):].strip()
            for line in text.splitlines()
            if line.startswith(marker)
        )
        self.assertEqual(sentence, self.kernel._GAP_EXIT2_FALLBACK)
        self.assertEqual(sentence, self.kernel.gap_exit2_sentence())

    def test_doctor_surfaces_blocking_gap_warnings(self):
        install = load_module("ce_install_exit2", "install.py")
        document = {
            "kind": "doctor",
            "status": "healthy",
            "commit": "deadbeef",
            "components": {},
            "kernel": {
                "status": "healthy",
                "capabilities": {
                    host: {
                        "processExit2Honored": cap.process_exit2_honored,
                        "blockingGap": cap.blocking_gap,
                    }
                    for host, cap in self.kernel.HOST_CAPABILITIES.items()
                },
            },
        }
        rendered = install.format_health_report(document)
        self.assertIn("GAP-EXIT2", rendered)
        self.assertNotIn("host/grok", rendered)
        self.assertIn("host/copilot", rendered)

    def test_exit2_capability_has_three_states_and_only_unsupported_warns(self):
        install = load_module("ce_install_exit2_probe", "install.py")
        caps = self.kernel.HOST_CAPABILITIES
        self.assertEqual("verified", install.exit2_capability(caps["claude"], which=lambda _: None))
        self.assertEqual("verified", install.exit2_capability(caps["grok"], which=lambda _: None))
        self.assertEqual("verified", install.exit2_capability(caps["grok"], which=lambda cli: "/usr/bin/" + cli))
        self.assertEqual("unknown", install.exit2_capability(caps["copilot"], which=lambda _: None))
        self.assertEqual("unsupported", install.exit2_capability(caps["cursor"], which=lambda cli: "/usr/bin/" + cli))
        document = {"kernel": {"capabilities": {
            host: {"processExit2Honored": caps[host].process_exit2_honored, "blockingGap": caps[host].blocking_gap,
                   "exit2": state}
            for host, state in (("claude", "verified"), ("cursor", "unsupported"), ("copilot", "unknown"))
        }}}
        lines = install.format_blocking_fidelity_warnings(document)
        self.assertEqual(2, len(lines))
        self.assertTrue(lines[0].startswith("[info] host/copilot"))
        self.assertTrue(lines[1].startswith("[warning] host/cursor"))


if __name__ == "__main__":
    unittest.main()
