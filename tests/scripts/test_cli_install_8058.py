"""Guided chaosengine-harness CLI (#8058).

Calls the shipped console module, not a copy of the installer.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
MARKER_START = "<!-- CHAOSENGINE:START -->"
MARKER_END = "<!-- CHAOSENGINE:END -->"
PAIRS = (
    ("tester", "grok"),
    ("frontend", "claude"),
    ("backend", "codex"),
    ("product-owner", "gemini"),
    ("scrum-master", "cursor"),
)


def _env(home: Path) -> dict[str, str]:
    env = os.environ.copy()
    env["HOME"] = str(home)
    env["GROK_HOME"] = str(home / ".grok")
    env.pop("CHAOS_ENGINE_LEAN_GROK_SKILLS", None)
    return env


def _run(home: Path, args: list[str]) -> subprocess.CompletedProcess[str]:
    grok_home = home / ".grok"
    grok_home.mkdir(parents=True, exist_ok=True)
    return subprocess.run(
        [sys.executable, "-m", "chaosengine_harness", *args],
        cwd=ROOT,
        env=_env(home),
        capture_output=True,
        text=True,
        check=False,
        timeout=180,
    )


def _accept_doctor(test: unittest.TestCase, completed: subprocess.CompletedProcess[str]) -> None:
    combined = completed.stdout + completed.stderr
    if completed.returncode == 0:
        test.assertNotIn("doctor-not-clean", combined)
        return
    test.assertNotEqual(completed.returncode, 0)
    test.assertIn("doctor-not-clean", combined)


class CliInstall8058Tests(unittest.TestCase):
    def test_help_text_matches_across_two_sandboxes(self) -> None:
        texts: list[str] = []
        for _ in range(2):
            with tempfile.TemporaryDirectory() as temporary:
                home = Path(temporary) / "home"
                completed = _run(home, ["init", "--help"])
            self.assertEqual(0, completed.returncode, completed.stderr)
            self.assertIn("--role", completed.stdout)
            self.assertIn("--tool", completed.stdout)
            self.assertIn("--yes", completed.stdout)
            self.assertTrue(completed.stdout.strip())
            texts.append(completed.stdout)
        self.assertEqual(texts[0], texts[1])

    def test_init_upgrade_uninstall_in_two_sandboxes(self) -> None:
        helps: list[str] = []
        for role, tool in (("product-owner", "grok"), ("tester", "cursor")):
            with tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                home = root / "home"
                project = root / "project"
                project.mkdir()
                help_run = _run(home, ["init", "--help"])
                self.assertEqual(0, help_run.returncode, help_run.stderr)
                self.assertTrue(help_run.stdout.strip())
                helps.append(help_run.stdout)
                self._lifecycle(home, project, role, tool)
        self.assertEqual(helps[0], helps[1])

    def test_each_role_and_each_tool_once(self) -> None:
        seen_roles: set[str] = set()
        seen_tools: set[str] = set()
        for role, tool in PAIRS:
            with tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                home = root / "home"
                project = root / "project"
                project.mkdir()
                (project / "AGENTS.md").write_text("KEEP-OUTSIDE\n", encoding="utf-8")
                completed = _run(
                    home,
                    ["init", "--project", str(project), "--role", role, "--tool", tool, "--yes"],
                )
                text = (project / "AGENTS.md").read_text(encoding="utf-8")
                self.assertIn("KEEP-OUTSIDE", text)
                self.assertIn(MARKER_START, text)
                self.assertIn(".chaos-engine/skills/chaos-engine/SKILL.md", text)
                self.assertLess(len(text), 4000)
                _accept_doctor(self, completed)
                recorded = json.loads(
                    (project / ".chaos-engine-state" / "guided-init.json").read_text(encoding="utf-8")
                )
                self.assertEqual(role, recorded["role"])
                self.assertEqual(tool, recorded["tool"])
                seen_roles.add(role)
                seen_tools.add(tool)
        self.assertEqual(
            {"tester", "frontend", "backend", "product-owner", "scrum-master"},
            seen_roles,
        )
        self.assertEqual({"grok", "claude", "codex", "gemini", "cursor"}, seen_tools)

    def test_unknown_role_is_a_named_failure(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            home = Path(temporary) / "home"
            project = Path(temporary) / "project"
            project.mkdir()
            completed = _run(
                home,
                ["init", "--project", str(project), "--role", "shaft", "--tool", "grok", "--yes"],
            )
        self.assertNotEqual(0, completed.returncode)
        self.assertIn("role-invalid", completed.stdout + completed.stderr)
        self.assertFalse((project / ".chaos-engine").exists())

    def test_node_bin_help_matches_python_cli(self) -> None:
        node = shutil.which("node")
        if node is None:
            self.skipTest("node is not installed")
        with tempfile.TemporaryDirectory() as temporary:
            home = Path(temporary) / "home"
            python_help = _run(home, ["init", "--help"])
            grok_home = home / ".grok"
            grok_home.mkdir(parents=True, exist_ok=True)
            node_help = subprocess.run(
                [node, str(ROOT / "bin" / "chaosengine-harness.js"), "init", "--help"],
                cwd=ROOT,
                env=_env(home),
                capture_output=True,
                text=True,
                check=False,
                timeout=60,
            )
        self.assertEqual(0, python_help.returncode, python_help.stderr)
        self.assertEqual(0, node_help.returncode, node_help.stderr)
        self.assertEqual(python_help.stdout, node_help.stdout)
        self.assertTrue(python_help.stdout.strip())

    def _lifecycle(self, home: Path, project: Path, role: str, tool: str) -> None:
        memory = project / ".memory"
        memory.mkdir()
        memory.joinpath("keep.txt").write_text("knowledge", encoding="utf-8")
        graphify = project / "graphify-out"
        graphify.mkdir()
        graphify.joinpath("keep.txt").write_text("index", encoding="utf-8")
        (project / "AGENTS.md").write_text("USER-OUTSIDE-BEFORE\n", encoding="utf-8")
        init = _run(
            home,
            ["init", "--project", str(project), "--role", role, "--tool", tool, "--yes"],
        )
        agents = (project / "AGENTS.md").read_text(encoding="utf-8")
        self.assertIn("USER-OUTSIDE-BEFORE", agents)
        self.assertLess(agents.index(MARKER_START), agents.index("USER-OUTSIDE-BEFORE"))
        self.assertIn(".chaos-engine/skills/chaos-engine/SKILL.md", agents)
        _accept_doctor(self, init)
        if not agents.endswith("\n"):
            agents += "\n"
        (project / "AGENTS.md").write_text(agents + "USER-OUTSIDE-AFTER\n", encoding="utf-8")
        again = _run(
            home,
            ["init", "--project", str(project), "--role", role, "--tool", tool, "--yes"],
        )
        _accept_doctor(self, again)
        agents = (project / "AGENTS.md").read_text(encoding="utf-8")
        self.assertLess(agents.index(MARKER_END), agents.index("USER-OUTSIDE-BEFORE"))
        self.assertLess(agents.index("USER-OUTSIDE-BEFORE"), agents.index("USER-OUTSIDE-AFTER"))
        self.assertGreater(agents.index("USER-OUTSIDE-AFTER"), agents.index(MARKER_END))
        manifest = json.loads((project / ".chaos-engine" / "manifest.json").read_text(encoding="utf-8"))
        original = manifest["source"]["commit"]
        empty = project.parent / "not-a-source"
        empty.mkdir()
        refused = _run(
            home,
            ["upgrade", "--project", str(project), "--source", str(empty), "--commit", "d" * 40],
        )
        self.assertNotEqual(0, refused.returncode)
        manifest = json.loads((project / ".chaos-engine" / "manifest.json").read_text(encoding="utf-8"))
        self.assertEqual(original, manifest["source"]["commit"])
        upgraded = _run(home, ["upgrade", "--project", str(project), "--commit", "e" * 40])
        # This sandbox has no hosts plugin manifest, so doctor is blocked
        # (CE_HOSTS_RECEIPT_MISSING). The contract must not exit 0.
        combined = upgraded.stdout + upgraded.stderr
        self.assertEqual(1, upgraded.returncode, combined)
        self.assertEqual("needs-repair\n", upgraded.stdout)
        self.assertNotIn("verify: ok", combined)
        manifest = json.loads((project / ".chaos-engine" / "manifest.json").read_text(encoding="utf-8"))
        self.assertEqual("e" * 40, manifest["source"]["commit"])
        head = _run(home, ["upgrade", "--project", str(project), "--commit", "HEAD"])
        self.assertNotEqual(0, head.returncode)
        self.assertIn("pin-required", head.stdout + head.stderr)
        manifest = json.loads((project / ".chaos-engine" / "manifest.json").read_text(encoding="utf-8"))
        self.assertEqual("e" * 40, manifest["source"]["commit"])
        removed = _run(home, ["uninstall", "--project", str(project)])
        self.assertEqual(0, removed.returncode, removed.stdout + removed.stderr)
        self.assertFalse((project / ".chaos-engine").exists())
        self.assertEqual("knowledge", memory.joinpath("keep.txt").read_text(encoding="utf-8"))
        self.assertEqual("index", graphify.joinpath("keep.txt").read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
