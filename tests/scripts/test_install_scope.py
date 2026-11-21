"""Opt-in user scope (#115)."""

from __future__ import annotations

import json
import os
import stat
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]


def _load(name: str, path: Path):
    import importlib.util
    import sys

    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


LAYER = _load("user_layer_runtime", ROOT / "runtime" / "user_layer.py")
STORES = _load("user_layer_stores", ROOT / "runtime" / "stores.py")


class UserLayerTests(unittest.TestCase):
    def _env(self, root: Path) -> dict[str, str]:
        env = os.environ.copy()
        for key in list(env):
            if key.startswith("CHAOS_ENGINE_") or key in {"CODEX_HOME", "COPILOT_HOME", "GROK_HOME"}:
                env.pop(key, None)
        env["CHAOS_ENGINE_USER_HOME"] = str(root / "home")
        env["CHAOS_ENGINE_USER_DIR"] = str(root / "data")
        env["CHAOS_ENGINE_CONFIG_HOME"] = str(root / "config")
        env["CHAOS_ENGINE_STATE_DIR"] = str(root / "state")
        env["CHAOS_ENGINE_CACHE_DIR"] = str(root / "cache")
        return env

    def test_user_scope_writes_home_files_and_leaves_the_project_empty(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            project = root / "project"
            project.mkdir()
            subprocess.run(["git", "-C", str(project), "init", "-q"], check=True)
            marker = project / "README.md"
            marker.write_text("project\n", encoding="utf-8")
            home = root / "home"
            (home / ".claude").mkdir(parents=True)
            (home / ".claude" / "CLAUDE.md").write_text("mine\n", encoding="utf-8")
            env = self._env(root)
            with mock.patch.dict(os.environ, env, clear=True):
                first = LAYER.install_user_layer(
                    home=home,
                    project=project,
                    source=ROOT,
                    commit="a" * 40,
                    hosts=("claude", "codex", "opencode", "grok"),
                    hooks=True,
                )
                command = (home / ".codex" / "hooks.json").read_text(encoding="utf-8")
                second = LAYER.install_user_layer(
                    home=home,
                    project=project,
                    source=ROOT,
                    commit="b" * 40,
                    hosts=("claude", "codex", "opencode", "grok"),
                    hooks=True,
                )
                command_again = (home / ".codex" / "hooks.json").read_text(encoding="utf-8")
            self.assertEqual("installed", first["status"])
            self.assertEqual(command, command_again)
            self.assertIn("current/launch.py", command)
            self.assertNotIn("/payload/a" , command)
            self.assertNotIn("/payload/b", command)
            self.assertFalse((home / ".config" / "opencode" / "AGENTS.md").exists())
            self.assertFalse((home / ".grok" / "rules" / "chaos-engine-user.md").exists())
            self.assertIn("name: chaos-engine-user", (home / ".claude" / "skills" / "chaos-engine-user" / "SKILL.md").read_text(encoding="utf-8"))
            self.assertNotIn("name: chaos-engine\n", (home / ".claude" / "skills" / "chaos-engine-user" / "SKILL.md").read_text(encoding="utf-8"))
            names = {path.name for path in project.iterdir()}
            self.assertEqual({"README.md", ".git"}, names)
            porcelain = subprocess.run(
                ["git", "-C", str(project), "status", "--porcelain"],
                check=True,
                capture_output=True,
                text=True,
            )
            self.assertIn("README.md", porcelain.stdout)
            self.assertNotIn(".claude", porcelain.stdout)
            receipt = json.loads((root / "data" / "user-receipt.json").read_text(encoding="utf-8"))
            self.assertEqual("b" * 40, receipt["commit"])
            self.assertTrue(receipt["files"])
            with mock.patch.dict(os.environ, env, clear=True):
                LAYER.uninstall_user_layer(home)
            self.assertEqual("mine\n", (home / ".claude" / "CLAUDE.md").read_text(encoding="utf-8"))
            self.assertEqual("project\n", marker.read_text(encoding="utf-8"))
            self.assertFalse((root / "data" / "user-receipt.json").exists())
            self.assertEqual("installed", second["status"])

    def test_opencode_and_grok_rules_follow_the_claude_pointer(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            home = root / "home"
            env = self._env(root)
            with mock.patch.dict(os.environ, env, clear=True):
                LAYER.install_user_layer(
                    home=home,
                    project=root / "empty",
                    source=ROOT,
                    commit="c" * 40,
                    hosts=("grok",),
                    hooks=True,
                )
            self.assertTrue((home / ".grok" / "rules" / "chaos-engine-user.md").is_file())
            self.assertFalse((home / ".config" / "opencode" / "AGENTS.md").exists())

    def test_shim_uses_the_project_install(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            project = root / "project"
            overlay = project / ".chaos-engine"
            overlay.mkdir(parents=True)
            (overlay / "install.py").write_text("print('SENTINEL')\n", encoding="utf-8")
            home = root / "home"
            env = self._env(root)
            with mock.patch.dict(os.environ, env, clear=True):
                LAYER.install_user_layer(
                    home=home,
                    project=project,
                    source=ROOT,
                    commit="d" * 40,
                    hosts=("claude",),
                    hooks=False,
                )
                shim = Path(json.loads((root / "data" / "user-receipt.json").read_text(encoding="utf-8"))["shim"])
            shim.chmod(shim.stat().st_mode | stat.S_IEXEC)
            self.assertEqual(shim.name, "chaosengine-harness.cmd" if os.name == "nt" else "chaosengine-harness")
            if os.name == "nt":
                argv = ["cmd", "/d", "/c", "call", str(shim), "doctor"]
            else:
                argv = [str(shim), "doctor"]
            completed = subprocess.run(argv, cwd=project, capture_output=True, text=True, check=False)
            self.assertEqual(0, completed.returncode, completed.stderr)
            self.assertIn("SENTINEL", completed.stdout)

    def test_windows_shim_script_prefers_the_project_install(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            project = root / "project"
            overlay = project / ".chaos-engine"
            overlay.mkdir(parents=True)
            (overlay / "install.py").write_text("print('SENTINEL')\n", encoding="utf-8")
            script = root / "bin" / "chaosengine-harness.py"
            script.parent.mkdir()
            script.write_text(LAYER._windows_shim_py(), encoding="utf-8")
            (root / "user-receipt.json").write_text(
                json.dumps({"commit": "f" * 40}),
                encoding="utf-8",
            )
            completed = subprocess.run(
                [sys.executable, str(script), "doctor"],
                cwd=project,
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(0, completed.returncode, completed.stderr)
            self.assertIn("SENTINEL", completed.stdout)

    def test_user_guard_blocks_without_a_project_and_defers_with_one(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            home = root / "home"
            project = root / "project"
            project.mkdir()
            env = self._env(root)
            with mock.patch.dict(os.environ, env, clear=True):
                LAYER.install_user_layer(
                    home=home,
                    project=project,
                    source=ROOT,
                    commit="e" * 40,
                    hosts=("claude",),
                    hooks=True,
                )
            launch = root / "data" / "current" / "launch.py"
            payload = json.dumps(
                {
                    "hook_event_name": "PreToolUse",
                    "tool_name": "Bash",
                    "tool_input": {"command": "git reset --hard"},
                }
            )
            blocked = subprocess.run(
                ["python3", str(launch), "claude", "PreToolUse", "--layer", "user"],
                input=payload,
                capture_output=True,
                text=True,
                cwd=project,
                env=env,
                check=False,
            )
            self.assertEqual(2, blocked.returncode, blocked.stderr + blocked.stdout)
            self.assertEqual("", blocked.stdout)
            self.assertEqual("block", json.loads(blocked.stderr)["decision"])
            overlay = project / ".chaos-engine"
            overlay.mkdir()
            (overlay / "install.py").write_text("print('project')\n", encoding="utf-8")
            layer = project / ".chaos-engine-state" / "sessions" / "sess-1.layer"
            layer.parent.mkdir(parents=True)
            layer.write_text("project\n", encoding="utf-8")
            deferred = subprocess.run(
                ["python3", str(launch), "claude", "PreToolUse", "--layer", "user"],
                input=json.dumps({"session_id": "sess-1", "tool_input": {"command": "git reset --hard"}}),
                capture_output=True,
                text=True,
                cwd=project,
                env=env,
                check=False,
            )
            self.assertEqual(0, deferred.returncode)
            self.assertEqual("", deferred.stdout)
            foreign = subprocess.run(
                ["python3", str(launch), "claude", "PreToolUse", "--layer", "user"],
                input=payload,
                capture_output=True,
                text=True,
                cwd=project,
                env={**env, "GROK_HOOK_EVENT": "1"},
                check=False,
            )
            self.assertEqual(0, foreign.returncode)

    def test_two_projects_do_not_retarget_the_store_timer(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            home = root / "home"
            env = self._env(root)
            env["CHAOS_ENGINE_STORE_REGISTRY"] = str(root / "registry")
            first = root / "one"
            second = root / "two"
            with mock.patch.dict(os.environ, env, clear=True):
                timer_a = STORES.install_schedule(first, home=home)
                text_a = timer_a.read_text(encoding="utf-8") + timer_a.with_name("chaosengine-stores.service").read_text(encoding="utf-8")
                timer_b = STORES.install_schedule(second, home=home)
                text_b = timer_b.read_text(encoding="utf-8") + timer_b.with_name("chaosengine-stores.service").read_text(encoding="utf-8")
            self.assertEqual(text_a, text_b)
            self.assertNotIn(str(first), text_b)
            self.assertNotIn(str(second), text_b)
            self.assertNotIn("WorkingDirectory=", text_b)


if __name__ == "__main__":
    unittest.main()
