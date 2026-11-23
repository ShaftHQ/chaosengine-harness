"""#170: tool.py maintain help must not install."""

from __future__ import annotations

import importlib.util
import io
import json
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[2]


def load_tool():
    spec = importlib.util.spec_from_file_location("ce_tool_maintain_170", ROOT / "tool.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class MaintainHelpTest(unittest.TestCase):
    def setUp(self):
        self.tool = load_tool()

    def _dispatch(self, arguments):
        stdout, stderr = io.StringIO(), io.StringIO()
        with redirect_stdout(stdout), redirect_stderr(stderr):
            code = self.tool._dispatch_core(ROOT, "maintain", arguments)
        return code, stdout.getvalue(), stderr.getvalue()

    def test_help_exits_0_and_does_not_install(self):
        with mock.patch.object(self.tool, "maintain", side_effect=AssertionError("maintain")), \
             mock.patch.object(self.tool, "maintain_sync", side_effect=AssertionError("sync")):
            for arguments in (["--help"], ["-h"], ["help"]):
                code, stdout, stderr = self._dispatch(arguments)
                self.assertEqual(0, code, arguments)
                self.assertIn("usage: tool.py maintain", stdout)
                self.assertEqual("", stderr)

    def test_unknown_argument_exits_2_without_install(self):
        with mock.patch.object(self.tool, "maintain", side_effect=AssertionError("maintain")), \
             mock.patch.object(self.tool, "maintain_sync", side_effect=AssertionError("sync")):
            code, stdout, stderr = self._dispatch(["--bogus"])
        self.assertEqual(2, code)
        self.assertEqual("", stdout)
        self.assertIn("usage: tool.py maintain", stderr)

    def test_no_arguments_still_runs_maintain(self):
        with mock.patch.object(self.tool, "maintain", return_value=0) as maintain:
            code, _stdout, _stderr = self._dispatch([])
        self.assertEqual(0, code)
        maintain.assert_called_once_with(ROOT)


class EntryRefreshTest(unittest.TestCase):
    def test_entry_triggers_nonblocking_refresh(self):
        tool = load_tool()
        seen = []
        original = tool._load_stores

        def load_stores(installed_root):
            module = dict(original(installed_root))

            def spy(project, popen=None):
                seen.append(project)
                return "skipped"

            module["maybe_spawn_refresh"] = spy
            return module

        with mock.patch.object(tool, "_load_stores", side_effect=load_stores):
            stdout = io.StringIO()
            with redirect_stdout(stdout):
                code = tool._dispatch_core(ROOT, "entry", [])
        self.assertEqual(0, code)
        self.assertEqual([ROOT], seen)


class ToolSearchTest(unittest.TestCase):
    def test_search_respects_limit(self):
        tool = load_tool()
        rows = tool.search_local_tools("chaos engine skill retrieve", limit=5, root=ROOT)
        self.assertLessEqual(len(rows), 5)
        self.assertGreater(len(rows), 0)
        one = tool.search_local_tools("chaos engine skill retrieve", limit=1, root=ROOT)
        self.assertEqual(1, len(one))
        stdout = io.StringIO()
        with redirect_stdout(stdout):
            code = tool.tools_command(ROOT, ["search", "skill", "--limit", "5"])
        self.assertEqual(0, code)
        self.assertLessEqual(len(json.loads(stdout.getvalue())), 5)


class UpgradeCommandTest(unittest.TestCase):
    def setUp(self):
        self.tool = load_tool()

    def test_upgrade_help_exits_0_and_does_not_invoke_bootstrap(self):
        runner = mock.Mock(side_effect=AssertionError("bootstrap should not run"))
        for flag in ("--help", "-h", "help"):
            stdout, stderr = io.StringIO(), io.StringIO()
            with redirect_stdout(stdout), redirect_stderr(stderr):
                code = self.tool.upgrade(ROOT, [flag], runner=runner)
            self.assertEqual(0, code, flag)
            self.assertIn("usage: tool.py upgrade", stdout.getvalue())
            self.assertEqual("", stderr.getvalue())
        with mock.patch.object(self.tool.subprocess, "run", side_effect=AssertionError("subprocess.run")):
            for flag in ("--help", "-h"):
                stdout, stderr = io.StringIO(), io.StringIO()
                with redirect_stdout(stdout), redirect_stderr(stderr):
                    code = self.tool._dispatch_core(ROOT, "upgrade", [flag])
                self.assertEqual(0, code, flag)
                self.assertIn("usage: tool.py upgrade", stdout.getvalue())
                self.assertEqual("", stderr.getvalue())

    def test_upgrade_invokes_bootstrap_and_propagates_exit_code(self):
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp)
            installed = project / ".chaos-engine"
            installed.mkdir()
            bootstrap = installed / "bootstrap.py"
            bootstrap.write_text("#!/usr/bin/env python3\n", encoding="utf-8")
            (installed / "manifest.json").write_text(
                json.dumps({"source": {"repository": "ShaftHQ/chaosengine-harness", "branch": "dev"}}),
                encoding="utf-8",
            )
            runner = mock.Mock(return_value=subprocess.CompletedProcess(args=[], returncode=7))
            code = self.tool.upgrade(
                installed,
                ["--branch", "main", "--yes", "--allow-dirty"],
                runner=runner,
            )
            self.assertEqual(7, code)
            runner.assert_called_once_with(
                [
                    sys.executable,
                    str(bootstrap),
                    "--project",
                    str(project.resolve()),
                    "--repository",
                    "ShaftHQ/chaosengine-harness",
                    "--branch",
                    "main",
                    "--yes",
                    "--allow-dirty",
                ],
                cwd=project.resolve(),
                check=False,
            )

    def test_upgrade_defaults_to_recorded_source_or_default_repository_and_branch(self):
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp)
            installed = project / ".chaos-engine"
            installed.mkdir()
            bootstrap = installed / "bootstrap.py"
            bootstrap.write_text("#!/usr/bin/env python3\n", encoding="utf-8")
            (installed / "manifest.json").write_text(
                json.dumps({"source": {"repository": "Acme/custom-harness", "branch": "release"}}),
                encoding="utf-8",
            )
            runner = mock.Mock(return_value=subprocess.CompletedProcess(args=[], returncode=0))
            code = self.tool.upgrade(installed, ["--yes"], runner=runner)
            self.assertEqual(0, code)
            runner.assert_called_once_with(
                [
                    sys.executable,
                    str(bootstrap),
                    "--project",
                    str(project.resolve()),
                    "--repository",
                    "Acme/custom-harness",
                    "--branch",
                    "release",
                    "--yes",
                ],
                cwd=project.resolve(),
                check=False,
            )

        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp)
            installed = project / ".chaos-engine"
            installed.mkdir()
            bootstrap = installed / "bootstrap.py"
            bootstrap.write_text("#!/usr/bin/env python3\n", encoding="utf-8")
            runner = mock.Mock(return_value=subprocess.CompletedProcess(args=[], returncode=0))
            with mock.patch.dict(self.tool.os.environ, {}, clear=False):
                self.tool.os.environ.pop("CHAOS_ENGINE_REPOSITORY", None)
                self.tool.os.environ.pop("CHAOS_ENGINE_BRANCH", None)
                code = self.tool.upgrade(installed, [], runner=runner)
            self.assertEqual(0, code)
            runner.assert_called_once_with(
                [
                    sys.executable,
                    str(bootstrap),
                    "--project",
                    str(project.resolve()),
                    "--repository",
                    "ShaftHQ/chaosengine-harness",
                    "--branch",
                    "main",
                ],
                cwd=project.resolve(),
                check=False,
            )


if __name__ == "__main__":
    unittest.main()
