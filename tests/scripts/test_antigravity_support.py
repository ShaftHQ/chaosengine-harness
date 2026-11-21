"""Antigravity (agy) hook schema, runtime protocol, installer, user layer, and doctor tests."""

from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


class AntigravitySupportTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if str(ROOT) not in sys.path:
            sys.path.insert(0, str(ROOT))
        cls.surfaces = _load("ce_agy_surfaces", ROOT / "runtime" / "hook_surfaces.py")
        cls.hosts = _load("ce_agy_hosts", ROOT / "runtime" / "hosts.py")
        cls.kernel = _load("ce_agy_kernel", ROOT / "hooks" / "kernel.py")
        cls.launch = _load("ce_agy_launch", ROOT / "hooks" / "launch.py")
        cls.conformance = _load("ce_agy_conformance", ROOT / "runtime" / "conformance.py")
        cls.install = _load("ce_agy_install", ROOT / "install.py")
        cls.bootstrap = _load("ce_agy_bootstrap", ROOT / "bootstrap.py")
        cls.user_layer = _load("ce_agy_user_layer", ROOT / "runtime" / "user_layer.py")

    def test_hooks_document_uses_named_hook_schema_and_migrates_legacy(self):
        document = self.surfaces.antigravity_hooks_document()
        self.assertEqual(["chaos-engine"], list(document.keys()))
        spec = document["chaos-engine"]
        self.assertIsInstance(spec, dict)
        for event in ("PreToolUse", "PostToolUse"):
            self.assertIn(event, spec)
            self.assertIn("matcher", spec[event][0])
            self.assertIn("hooks", spec[event][0])
        for event in ("SessionStart", "PreInvocation", "PostInvocation", "Stop"):
            self.assertIn(event, spec)
            self.assertNotIn("matcher", spec[event][0])
            self.assertEqual("command", spec[event][0]["type"])

        # Legacy flat top-level ChaosEngine entries are migrated and foreign named hooks stay.
        legacy = {
            "my-linter": {
                "PostToolUse": [
                    {
                        "matcher": "edit_file",
                        "hooks": [{"type": "command", "command": "./lint.sh"}],
                    }
                ]
            },
            "PreToolUse": [
                {
                    "matcher": ".*",
                    "hooks": [
                        {
                            "type": "command",
                            "command": "python3 .chaos-engine/hooks/launch.py antigravity PreToolUse",
                        }
                    ],
                }
            ],
            "Stop": [
                {
                    "type": "command",
                    "command": "python3 .chaos-engine/hooks/launch.py antigravity Stop",
                }
            ],
        }
        merged = self.surfaces.merge_antigravity_hooks(legacy)
        self.assertIn("my-linter", merged)
        self.assertIn("chaos-engine", merged)
        self.assertNotIn("PreToolUse", merged)
        self.assertNotIn("Stop", merged)

        with tempfile.TemporaryDirectory() as temporary:
            project = Path(temporary)
            target = project / ".agents" / "hooks.json"
            target.parent.mkdir(parents=True)
            target.write_text(json.dumps(legacy), encoding="utf-8")
            self.surfaces.install_antigravity(project)
            written = json.loads(target.read_text(encoding="utf-8"))
            self.assertEqual({"my-linter", "chaos-engine"}, set(written))
            self.assertTrue(self.surfaces.uninstall_antigravity(project))
            remaining = json.loads(target.read_text(encoding="utf-8"))
            self.assertEqual({"my-linter"}, set(remaining))

    def test_conformance_registry_unwraps_named_antigravity_events(self):
        registry = self.conformance.production_hook_registry()
        self.assertEqual(
            {"SessionStart", "PreToolUse", "PostToolUse", "PreInvocation", "PostInvocation", "Stop"},
            registry["antigravity"],
        )

    def test_windows_command_is_cmd_safe_not_powershell(self):
        command = self.hosts.chaos_guard_locator_command(
            windows=True, host="antigravity", event="PreToolUse"
        )
        self.assertNotIn("$a=", command)
        self.assertNotIn("Get-Command", command)
        self.assertIn("py -3 -c", command)
        self.assertIn("antigravity PreToolUse", command)

    def test_kernel_normalizes_and_adapts_all_agy_events(self):
        event = self.kernel.normalize_event(
            {
                "conversationId": "conv-42",
                "hookEventName": "PreToolUse",
                "cwd": "/workspace",
                "toolCall": {
                    "id": "toolu_99",
                    "name": "run_command",
                    "args": {"CommandLine": "git status"},
                },
            },
            "antigravity",
        )
        self.assertEqual("PreToolUse", event.name)
        self.assertEqual("conv-42", event.session_id)
        self.assertEqual("toolu_99", event.tool_call_id)
        self.assertEqual("PowerShell", event.tool_name)
        self.assertEqual("git status", event.tool_input["command"])

        read_event = self.kernel.normalize_event(
            {
                "conversationId": "conv-42",
                "hookEventName": "PreToolUse",
                "toolCall": {
                    "id": "toolu_100",
                    "name": "read_file",
                    "args": {"Path": "/workspace/big.log", "StartLine": 1, "EndLine": 50},
                },
            },
            "antigravity",
        )
        self.assertEqual("Read", read_event.tool_name)
        self.assertEqual("/workspace/big.log", read_event.tool_input["file_path"])
        self.assertEqual(1, read_event.tool_input["startLine"])
        self.assertEqual(50, read_event.tool_input["endLine"])

        stop_event = self.kernel.normalize_event(
            {
                "conversationId": "conv-42",
                "hookEventName": "Stop",
                "continuationActive": True,
            },
            "antigravity",
        )
        self.assertTrue(stop_event.stop_hook_active)

        # Output adaptation for every AGY event
        ss = self.kernel.adapt_hook_output({"additionalContext": "hello"}, "SessionStart", "antigravity")
        self.assertEqual({"injectSteps": [{"systemMessage": {"systemMessage": "hello"}}]}, ss)

        pre_inv_ctx = self.kernel.adapt_hook_output(
            {"additionalContext": "ctx"}, "UserPromptSubmit", "antigravity", native_event="PreInvocation"
        )
        self.assertEqual({"injectSteps": [{"systemMessage": {"systemMessage": "ctx"}}]}, pre_inv_ctx)

        pre_inv_deny = self.kernel.adapt_hook_output(
            {"decision": "block", "reason": "nope"},
            "UserPromptSubmit",
            "antigravity",
            native_event="PreInvocation",
        )
        self.assertEqual(
            {
                "injectSteps": [{"errorMessage": {"userMessage": "nope"}}],
                "terminationBehavior": "terminate",
            },
            pre_inv_deny,
        )

        pre_allow = self.kernel.adapt_hook_output({}, "PreToolUse", "antigravity")
        self.assertEqual({"decision": "allow"}, pre_allow)

        pre_deny = self.kernel.adapt_hook_output(
            {"decision": "block", "reason": "unsafe"}, "PreToolUse", "antigravity"
        )
        self.assertEqual({"decision": "deny", "reason": "unsafe"}, pre_deny)

        post = self.kernel.adapt_hook_output(
            {"additionalContext": "ignored"}, "PostToolUse", "antigravity", native_event="PostToolUse"
        )
        self.assertEqual({}, post)

        stop = self.kernel.adapt_hook_output(
            {"decision": "block", "reason": "finish tests"}, "Stop", "antigravity"
        )
        self.assertEqual({"decision": "continue", "reason": "finish tests"}, stop)

    def test_live_launch_from_dot_agents_handles_session_start_and_pretool(self):
        with tempfile.TemporaryDirectory() as temporary:
            project = Path(temporary)
            subprocess.run(["git", "-C", str(project), "init", "-q"], check=True)
            overlay = project / ".chaos-engine"
            (overlay / "hooks").mkdir(parents=True)
            (overlay / "runtime").mkdir(parents=True)
            (overlay / "rules").mkdir(parents=True)
            (overlay / "companions").mkdir(parents=True)
            (overlay / "skills" / "chaos-engine").mkdir(parents=True)
            (project / ".agents").mkdir(parents=True)
            for name in (
                "launch.py",
                "guard.py",
                "kernel.py",
                "lifecycle.py",
                "matchers.json",
                "reflection.py",
                "repeat_reminder.py",
                "retrieve_justification.py",
                "session_scratch.py",
            ):
                src = ROOT / "hooks" / name
                if src.is_file():
                    (overlay / "hooks" / name).write_bytes(src.read_bytes())
            for name in (
                "stores.py",
                "user_paths.py",
                "delete_guard.py",
                "gate_fail_closed.py",
                "session_token_usage.py",
                "significance.py",
                "tool_output_store.py",
            ):
                src = ROOT / "runtime" / name
                if src.is_file():
                    (overlay / "runtime" / name).write_bytes(src.read_bytes())
            for name in ("large_read_deny.py", "ethics_check.py", "operation_boundary.py"):
                src = ROOT / "rules" / name
                if src.is_file():
                    (overlay / "rules" / name).write_bytes(src.read_bytes())
            (overlay / "identity.md").write_text("# Identity\n## Truth\n- Speak truth.\n", encoding="utf-8")
            (overlay / "skills" / "chaos-engine" / "SKILL.md").write_text("---\nname: chaos-engine\n---\n", encoding="utf-8")
            (project / "big.log").write_bytes(b"x" * 10000)

            env = os.environ.copy()
            env.pop("PYTHONPATH", None)
            trace = project / "trace.log"
            env["CE_HOOK_TRACE"] = str(trace)
            launcher = str(overlay / "hooks" / "launch.py")
            agents_dir = project / ".agents"

            # 1. SessionStart from .agents/ must not crash with No module named 'runtime'
            ss = subprocess.run(
                [sys.executable, launcher, "antigravity", "SessionStart"],
                input=json.dumps(
                    {
                        "conversationId": "agy-conv-1",
                        "workspacePaths": [str(project)],
                        "hookEventName": "SessionStart",
                        "cwd": str(project),
                    }
                ),
                cwd=agents_dir,
                capture_output=True,
                text=True,
                env=env,
                check=False,
            )
            self.assertEqual(0, ss.returncode, ss.stderr)
            self.assertNotIn("Hook protocol error", ss.stderr)
            ss_out = json.loads(ss.stdout)
            self.assertIn("injectSteps", ss_out)
            self.assertIn("ChaosEngine:", ss_out["injectSteps"][0]["systemMessage"]["systemMessage"])

            # 2. PreToolUse rm -rf / via AGY toolCall must deny with exit 0
            deny = subprocess.run(
                [sys.executable, launcher, "antigravity", "PreToolUse"],
                input=json.dumps(
                    {
                        "conversationId": "agy-conv-1",
                        "hookEventName": "PreToolUse",
                        "cwd": str(project),
                        "toolCall": {
                            "id": "toolu_rm",
                            "name": "run_command",
                            "args": {"CommandLine": "rm -rf /"},
                        },
                    }
                ),
                cwd=agents_dir,
                capture_output=True,
                text=True,
                env=env,
                check=False,
            )
            self.assertEqual(0, deny.returncode, deny.stderr)
            self.assertEqual("deny", json.loads(deny.stdout)["decision"])

            # 3. PreToolUse unmatched tool returns {"decision": "allow"} with exit 0
            unmatched = subprocess.run(
                [sys.executable, launcher, "antigravity", "PreToolUse"],
                input=json.dumps(
                    {
                        "conversationId": "agy-conv-1",
                        "hookEventName": "PreToolUse",
                        "cwd": str(project),
                        "toolCall": {
                            "id": "toolu_ask",
                            "name": "ask_question",
                            "args": {},
                        },
                    }
                ),
                cwd=agents_dir,
                capture_output=True,
                text=True,
                env=env,
                check=False,
            )
            self.assertEqual(0, unmatched.returncode, unmatched.stderr)
            self.assertEqual({"decision": "allow"}, json.loads(unmatched.stdout))

            # 4. Large unranged read_file with PascalCase Path denies; ranged with StartLine/EndLine allows
            large_deny = subprocess.run(
                [sys.executable, launcher, "antigravity", "PreToolUse"],
                input=json.dumps(
                    {
                        "conversationId": "agy-conv-1",
                        "hookEventName": "PreToolUse",
                        "cwd": str(project),
                        "toolCall": {
                            "id": "toolu_read1",
                            "name": "read_file",
                            "args": {"Path": str(project / "big.log")},
                        },
                    }
                ),
                cwd=agents_dir,
                capture_output=True,
                text=True,
                env=env,
                check=False,
            )
            self.assertEqual(0, large_deny.returncode, large_deny.stderr)
            self.assertEqual("deny", json.loads(large_deny.stdout)["decision"])

            ranged_allow = subprocess.run(
                [sys.executable, launcher, "antigravity", "PreToolUse"],
                input=json.dumps(
                    {
                        "conversationId": "agy-conv-1",
                        "hookEventName": "PreToolUse",
                        "cwd": str(project),
                        "toolCall": {
                            "id": "toolu_read2",
                            "name": "read_file",
                            "args": {"Path": str(project / "big.log"), "StartLine": 1, "EndLine": 10},
                        },
                    }
                ),
                cwd=agents_dir,
                capture_output=True,
                text=True,
                env=env,
                check=False,
            )
            self.assertEqual(0, ranged_allow.returncode, ranged_allow.stderr)
            self.assertEqual({"decision": "allow"}, json.loads(ranged_allow.stdout))

            # 5. State must not be written inside .agents/
            self.assertFalse((agents_dir / ".chaos-engine-state").exists())

            # 6. Trace recorded conversationId and toolCall.id
            lines = trace.read_text(encoding="utf-8").splitlines()
            self.assertTrue(any("agy-conv-1\ttoolu_rm" in line for line in lines), lines)

    def test_doctor_flags_legacy_top_level_antigravity_hooks(self):
        legacy = {
            "PreToolUse": [
                {
                    "matcher": ".*",
                    "hooks": [
                        {
                            "type": "command",
                            "command": "python3 .chaos-engine/hooks/launch.py antigravity PreToolUse",
                        }
                    ],
                }
            ]
        }
        findings = self.surfaces.antigravity_hooks_findings(legacy)
        self.assertTrue(findings)
        valid = self.surfaces.antigravity_hooks_document()
        self.assertEqual([], self.surfaces.antigravity_hooks_findings(valid))

    def test_installer_host_selection_detection_and_user_layer_support_agy(self):
        self.assertIn("antigravity", self.bootstrap.INSTALL_HOST_IDS)
        self.assertEqual(("antigravity",), self.bootstrap.parse_install_hosts("antigravity"))
        self.assertEqual(("antigravity",), self.bootstrap.parse_install_hosts("agy"))
        self.assertEqual("agy", self.kernel.HOST_CAPABILITIES["antigravity"].cli)

        detected = dict(
            (host_id, found)
            for host_id, _label, found in self.bootstrap.detect_install_hosts(
                which=lambda name: "/usr/bin/agy" if name == "agy" else None
            )
        )
        self.assertTrue(detected["antigravity"])

        with tempfile.TemporaryDirectory() as temporary:
            project = Path(temporary) / "proj"
            project.mkdir()
            self.install.apply_install_host_completion(project, ("antigravity",))
            hooks_file = project / ".agents" / "hooks.json"
            self.assertTrue(hooks_file.is_file())
            self.assertIn("chaos-engine", json.loads(hooks_file.read_text(encoding="utf-8")))
            self.assertFalse((project / ".cursor" / "hooks.json").exists())

            # User layer writes ~/.gemini/config/hooks.json in AGY named-hook format
            root = Path(temporary) / "u"
            home = root / "home"
            env = os.environ.copy()
            env["CHAOS_ENGINE_USER_HOME"] = str(home)
            env["CHAOS_ENGINE_USER_DIR"] = str(root / "data")
            env["CHAOS_ENGINE_CONFIG_HOME"] = str(root / "config")
            env["CHAOS_ENGINE_STATE_DIR"] = str(root / "state")
            env["CHAOS_ENGINE_CACHE_DIR"] = str(root / "cache")
            with mock.patch.dict(os.environ, env, clear=True):
                result = self.user_layer.install_user_layer(
                    home=home,
                    project=project,
                    source=ROOT,
                    commit="a" * 40,
                    hosts=("antigravity",),
                    hooks=True,
                )
            self.assertEqual("installed", result["status"])
            user_hooks = home / ".gemini" / "config" / "hooks.json"
            self.assertTrue(user_hooks.is_file())
            parsed = json.loads(user_hooks.read_text(encoding="utf-8"))
            self.assertIn("chaos-engine-user", parsed)
            self.assertIn("PreToolUse", parsed["chaos-engine-user"])
            self.assertIn("SessionStart", parsed["chaos-engine-user"])
            self.assertTrue(
                (home / ".gemini" / "config" / "skills" / "chaos-engine-user" / "SKILL.md").is_file()
            )
            with mock.patch.dict(os.environ, env, clear=True):
                self.user_layer.uninstall_user_layer(home)
            self.assertFalse(user_hooks.exists())


if __name__ == "__main__":
    unittest.main()
