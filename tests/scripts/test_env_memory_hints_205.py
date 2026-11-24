"""Pre-task OS/shell/tools memory index matching (#205)."""

from __future__ import annotations

import importlib.util
import os
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]


def load_module(name: str, relative: str):
    path = ROOT / relative
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {relative}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


WINDOWS_MEMORY_INDEX = """\
# Project Memory Index

## Platform Notes
- [Windows local mock run](windows-mock.md) — MSYS path traps in Git Bash (`--base-path /` rewrite)
- [Gradle wrapper](gradle-wrapper.md) — do not carry MSYS_NO_PATHCONV=1 into Gradle shell
- [Appium server](appium-setup.md) — local Appium startup flags and port binding
- [Release checklist](release.md) — bump version and verify changelog
"""


class EnvMemoryHintsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.wake = load_module("ce_wake_pack_205", "runtime/wake_pack.py")
        cls.lifecycle = load_module("ce_lifecycle_205", "hooks/lifecycle.py")
        cls.tool = load_module("ce_tool_205", "tool.py")

    def _clean_linux_env(self, extra: dict[str, str] | None = None) -> dict[str, str]:
        env = {"SHELL": "/bin/bash"}
        if extra:
            env.update(extra)
        return env

    def _windows_git_bash_env(self, extra: dict[str, str] | None = None) -> dict[str, str]:
        env = {
            "OS": "Windows_NT",
            "MSYSTEM": "MINGW64",
            "SHELL": "/usr/bin/bash",
        }
        if extra:
            env.update(extra)
        return env

    def test_detect_env_tokens_windows_git_bash_vs_linux(self) -> None:
        win_tokens = self.wake.detect_env_tokens(self._windows_git_bash_env())
        self.assertIn("windows", win_tokens)
        self.assertIn("msys", win_tokens)
        self.assertIn("git bash", win_tokens)
        self.assertIn("mingw64", win_tokens)
        self.assertNotIn("bash", win_tokens)
        self.assertNotIn("linux", win_tokens)

        linux_tokens = self.wake.detect_env_tokens(
            self._clean_linux_env(), system_name="Linux"
        )
        self.assertIn("linux", linux_tokens)
        for forbidden in ("bash", "sh", "windows", "windows_nt", "msys", "git bash", "mingw"):
            self.assertNotIn(forbidden, linux_tokens)

        zsh_tokens = self.wake.detect_env_tokens(
            {"SHELL": "/usr/bin/zsh"}, system_name="Linux", tools=("Appium", "gradle")
        )
        self.assertIn("linux", zsh_tokens)
        self.assertIn("zsh", zsh_tokens)
        self.assertIn("appium", zsh_tokens)
        self.assertIn("gradle", zsh_tokens)

    def test_windows_git_bash_surfaces_matching_memory_entry(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp)
            mem_dir = project / ".memory"
            mem_dir.mkdir()
            (mem_dir / "MEMORY.md").write_text(WINDOWS_MEMORY_INDEX, encoding="utf-8")

            hints = self.wake.env_memory_hints(project, env=self._windows_git_bash_env())
            self.assertTrue(hints, "expected Windows/MSYS hints on Windows + Git Bash")
            self.assertIn("Windows local mock run", hints)
            self.assertIn("MSYS", hints)
            self.assertNotIn("Release checklist", hints)
            self.assertLessEqual(len(hints.encode("utf-8")), 480)

    def test_linux_prints_nothing_for_windows_msys_git_bash_entries(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp)
            mem_dir = project / ".memory"
            mem_dir.mkdir()
            (mem_dir / "MEMORY.md").write_text(WINDOWS_MEMORY_INDEX, encoding="utf-8")

            hints = self.wake.env_memory_hints(
                project, env=self._clean_linux_env(), system_name="Linux"
            )
            self.assertEqual("", hints)
            self.assertEqual(0, len(hints.encode("utf-8")))

    def test_missing_or_unmatched_memory_index_is_skipped_zero_bytes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp)
            self.assertEqual([], self.wake.find_memory_index_files(project, env={}))
            self.assertEqual("", self.wake.env_memory_hints(project, env=self._windows_git_bash_env()))

            mem_dir = project / ".memory"
            mem_dir.mkdir()
            (mem_dir / "MEMORY.md").write_text(
                "# Windows Heading Only\n\n## MSYS Section\n- [Release](release.md) — ecosystems notes\n",
                encoding="utf-8",
            )
            self.assertEqual("", self.wake.env_memory_hints(project, env=self._windows_git_bash_env()))

    def test_request_tools_matching_surfaces_tool_entries_on_linux(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp)
            mem_dir = project / ".memory"
            mem_dir.mkdir()
            (mem_dir / "MEMORY.md").write_text(WINDOWS_MEMORY_INDEX, encoding="utf-8")

            hints = self.wake.env_memory_hints(
                project,
                env=self._clean_linux_env(),
                system_name="Linux",
                tools=("appium", "gradle"),
            )
            self.assertIn("Appium server", hints)
            self.assertIn("Gradle wrapper", hints)
            self.assertNotIn("Windows local mock run", hints)
            self.assertNotIn("Release checklist", hints)

    def test_find_memory_index_files_supports_memory_dir_and_claude_home(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            project = base / "demo-project"
            project.mkdir()
            custom_dir = base / "custom-mem"
            custom_dir.mkdir()
            custom_mem = custom_dir / "MEMORY.md"
            custom_mem.write_text("- [Custom](c.md) — Windows note\n", encoding="utf-8")

            fake_home = base / "home"
            encoded = re.sub(r"[^A-Za-z0-9-]", "-", str(project.resolve()))
            claude_mem = fake_home / ".claude" / "projects" / encoded / "memory" / "MEMORY.md"
            claude_mem.parent.mkdir(parents=True)
            claude_mem.write_text("- [Claude](cl.md) — MSYS note\n", encoding="utf-8")

            found = self.wake.find_memory_index_files(
                project,
                env={"MEMORY_DIR": str(custom_dir), "HOME": str(fake_home)},
            )
            self.assertEqual([custom_mem.resolve(), claude_mem.resolve()], found)

    def test_bounds_and_invalid_limits(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp)
            mem_dir = project / ".memory"
            mem_dir.mkdir()
            lines = "\n".join(
                f"- [Win entry {i}](w{i}.md) — Windows MSYS detail {'x' * 60}"
                for i in range(12)
            )
            (mem_dir / "MEMORY.md").write_text(lines + "\n", encoding="utf-8")

            self.assertEqual("", self.wake.env_memory_hints(project, env=self._windows_git_bash_env(), max_lines=0))
            self.assertEqual("", self.wake.env_memory_hints(project, env=self._windows_git_bash_env(), max_bytes=0))

            capped_lines = self.wake.env_memory_hints(
                project, env=self._windows_git_bash_env(), max_lines=2, max_bytes=1000
            )
            entry_lines = [ln for ln in capped_lines.splitlines() if ln.startswith("- ")]
            self.assertEqual(2, len(entry_lines))

            capped_bytes = self.wake.env_memory_hints(
                project, env=self._windows_git_bash_env(), max_lines=8, max_bytes=120
            )
            self.assertTrue(capped_bytes)
            self.assertLessEqual(len(capped_bytes.encode("utf-8")), 120)

    def test_tool_cli_env_memory_subcommand(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            mem_dir = Path(tmp) / "mem"
            mem_dir.mkdir()
            (mem_dir / "MEMORY.md").write_text(WINDOWS_MEMORY_INDEX, encoding="utf-8")

            win_env = {
                "PATH": os.environ.get("PATH", ""),
                "OS": "Windows_NT",
                "MSYSTEM": "MINGW64",
                "SHELL": "/usr/bin/bash",
            }
            win_proc = subprocess.run(
                [sys.executable, str(ROOT / "tool.py"), "env-memory", "--memory-dir", str(mem_dir)],
                cwd=tmp,
                env=win_env,
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(0, win_proc.returncode, win_proc.stderr)
            self.assertIn("Windows local mock run", win_proc.stdout)
            self.assertIn("MSYS", win_proc.stdout)

            linux_env = {
                "PATH": os.environ.get("PATH", ""),
                "SHELL": "/bin/bash",
            }
            linux_proc = subprocess.run(
                [sys.executable, str(ROOT / "tool.py"), "env-memory", "--memory-dir", str(mem_dir)],
                cwd=tmp,
                env=linux_env,
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(0, linux_proc.returncode, linux_proc.stderr)
            if sys.platform.startswith("linux"):
                self.assertEqual("", linux_proc.stdout)

            tools_proc = subprocess.run(
                [
                    sys.executable,
                    str(ROOT / "tool.py"),
                    "env-memory",
                    "--memory-dir",
                    str(mem_dir),
                    "--tools",
                    "appium,gradle",
                ],
                cwd=tmp,
                env=linux_env,
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(0, tools_proc.returncode, tools_proc.stderr)
            self.assertIn("Appium server", tools_proc.stdout)
            self.assertIn("Gradle wrapper", tools_proc.stdout)

            missing_proc = subprocess.run(
                [sys.executable, str(ROOT / "tool.py"), "env-memory", "--memory-dir", str(Path(tmp) / "absent")],
                cwd=tmp,
                env=win_env,
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(0, missing_proc.returncode, missing_proc.stderr)
            self.assertEqual("", missing_proc.stdout)

    def test_tool_entry_surfaces_hints_only_on_match(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp)
            installed = project / ".chaos-engine"
            installed.mkdir()
            (installed / "identity.md").write_text("# Identity\n- Truth\n", encoding="utf-8")
            (project / ".memory").mkdir()
            (project / ".memory" / "MEMORY.md").write_text(WINDOWS_MEMORY_INDEX, encoding="utf-8")

            with mock.patch.dict(os.environ, self._clean_linux_env(), clear=True):
                with mock.patch("platform.system", return_value="Linux"):
                    linux_out = self.tool.entry_output(installed, full=True)
            self.assertNotIn("Windows local mock run", linux_out)
            self.assertNotIn("Env memory", linux_out)

            with mock.patch.dict(os.environ, self._windows_git_bash_env(), clear=True):
                win_out = self.tool.entry_output(installed, full=True)
            self.assertIn("Windows local mock run", win_out)
            self.assertIn("MSYS", win_out)

    def test_session_start_context_surfaces_hints_within_budget(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp)
            (project / ".memory").mkdir()
            (project / ".memory" / "MEMORY.md").write_text(
                "- [Win mock](win.md) — Windows MSYS Git Bash trap\n",
                encoding="utf-8",
            )
            previous = Path.cwd()
            os.chdir(project)
            try:
                with mock.patch.dict(
                    os.environ,
                    {**self._clean_linux_env(), "PYTEST_CURRENT_TEST": "1"},
                    clear=True,
                ):
                    with mock.patch("platform.system", return_value="Linux"):
                        linux_ctx = self.lifecycle.session_start_context("token-fixture", "activation")
                self.assertNotIn("Windows MSYS Git Bash trap", linux_ctx)
                self.assertNotIn("Env memory", linux_ctx)

                with mock.patch.dict(
                    os.environ,
                    {**self._windows_git_bash_env(), "PYTEST_CURRENT_TEST": "1"},
                    clear=True,
                ):
                    win_ctx = self.lifecycle.session_start_context("token-fixture", "activation")
                self.assertIn("Windows MSYS Git Bash trap", win_ctx)
                encoded = win_ctx.encode("utf-8")
                self.assertLessEqual(len(encoded), self.lifecycle.SESSION_START_MAX_BYTES)
                self.assertLessEqual(len(encoded) // 4, 512)
            finally:
                os.chdir(previous)


if __name__ == "__main__":
    unittest.main()
