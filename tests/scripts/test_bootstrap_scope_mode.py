"""One-liner scope and mode go through bootstrap.main, not only install.py."""

from __future__ import annotations

import io
import json
import os
import subprocess
import tempfile
import unittest
import unittest.mock as mock
from contextlib import contextmanager
from pathlib import Path

from tests.scripts.test_chaos_engine_bootstrap import ROOT, load

COMMIT = "a" * 40
_DROP = (
    "CI",
    "CHAOS_ENGINE_MODE",
    "CHAOS_ENGINE_SCOPE",
    "CHAOS_ENGINE_VERSION",
    "CHAOS_ENGINE_BRANCH",
    "CHAOS_ENGINE_REPOSITORY",
    "CHAOS_ENGINE_DRY_RUN",
    "CHAOS_ENGINE_NO_INPUT",
    "CHAOS_ENGINE_SKIP_TOOLS",
    "CHAOS_ENGINE_CONSUMER",
    "CHAOS_ENGINE_HOST",
    "CHAOS_ENGINE_JSON",
    "CHAOS_ENGINE_QUIET",
)


@contextmanager
def _isolated(home: Path, data: Path):
    overlay = {
        "CHAOS_ENGINE_USER_HOME": str(home),
        "CHAOS_ENGINE_USER_DIR": str(data),
        "CHAOS_ENGINE_CONFIG_HOME": str(home / "config"),
        "CHAOS_ENGINE_STATE_DIR": str(data / "state"),
        "CHAOS_ENGINE_CACHE_DIR": str(data / "cache"),
        "CODEX_HOME": str(home / ".codex"),
        "COPILOT_HOME": str(home / ".copilot"),
        "GROK_HOME": str(home / ".grok"),
    }
    saved = {key: os.environ.get(key) for key in set(overlay) | set(_DROP)}
    try:
        for key in _DROP:
            os.environ.pop(key, None)
        os.environ.update(overlay)
        yield
    finally:
        for key, value in saved.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


def _git(project: Path, *args: str) -> None:
    subprocess.run(
        [
            "git",
            "-c",
            "user.email=Mohab.MohieElDeen@outlook.com",
            "-c",
            "user.name=Mohab Mohie",
            "-C",
            str(project),
            *args,
        ],
        check=True,
        capture_output=True,
        text=True,
    )


def _fake_download(*_args, **_kwargs):
    _fake_download.last_root_layout = False
    _fake_download.last_actions = []
    return ROOT


class BootstrapScopeModeTests(unittest.TestCase):
    def _run(self, module, project: Path, argv: list[str], *, download):
        stderr = io.StringIO()
        stdout = io.StringIO()
        with (
            mock.patch.object(module, "resolve_latest", return_value=(COMMIT, "main")),
            mock.patch.object(module, "download_source", download),
            mock.patch.object(module, "_prepare_shaft_addons", return_value=None),
            mock.patch.object(module.sys, "argv", ["bootstrap.py", *argv]),
            mock.patch.object(module.sys, "stdout", stdout),
            mock.patch.object(module.sys, "stderr", stderr),
        ):
            code = module.main()
        return code, stdout.getvalue(), stderr.getvalue()

    def test_user_scope_writes_no_project_files(self):
        module = load()
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            project = root / "project"
            project.mkdir()
            home = root / "home"
            data = root / "data"
            home.mkdir()
            data.mkdir()
            with _isolated(home, data):
                code, _stdout, stderr = self._run(
                    module,
                    project,
                    [
                        "--project",
                        str(project),
                        "--repository",
                        "Example/Project",
                        "--scope",
                        "user",
                        "--skip-tools",
                    ],
                    download=_fake_download,
                )
            self.assertEqual(0, code, stderr)
            self.assertEqual([], list(project.iterdir()))
            receipt = data / "user-receipt.json"
            self.assertTrue(receipt.is_file(), stderr)
            self.assertEqual("user", json.loads(receipt.read_text(encoding="utf-8"))["scope"])

    def test_replace_without_yes_writes_nothing(self):
        module = load()
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            project = root / "project"
            project.mkdir()
            (project / "AGENTS.md").write_text("User rule\n", encoding="utf-8")
            home = root / "home"
            data = root / "data"
            home.mkdir()
            data.mkdir()
            download = mock.Mock(side_effect=AssertionError("downloaded"))
            with _isolated(home, data):
                code, _stdout, stderr = self._run(
                    module,
                    project,
                    [
                        "--project",
                        str(project),
                        "--repository",
                        "Example/Project",
                        "--mode",
                        "replace",
                    ],
                    download=download,
                )
            self.assertEqual(2, code, stderr)
            self.assertIn("CE_MODE_REPLACE_NEEDS_YES", stderr)
            self.assertEqual("User rule\n", (project / "AGENTS.md").read_text(encoding="utf-8"))
            self.assertFalse(download.called)
            self.assertFalse((project / ".chaos-engine-state").exists())

    def test_replace_on_a_tty_reaches_the_confirmation_prompt(self):
        module = load()
        import runtime.instruction_mode as instruction_mode

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            project = root / "project"
            project.mkdir()
            (project / "AGENTS.md").write_text("User rule\n", encoding="utf-8")
            home = root / "home"
            data = root / "data"
            home.mkdir()
            data.mkdir()
            stderr = io.StringIO()
            stdout = io.StringIO()
            stdin = io.StringIO()
            stdin.isatty = lambda: True
            download = mock.Mock(side_effect=_fake_download)
            argv = [
                "--project",
                str(project),
                "--repository",
                "Example/Project",
                "--mode",
                "replace",
                "--skip-tools",
            ]
            with _isolated(home, data):
                with (
                    mock.patch.object(module, "resolve_latest", return_value=(COMMIT, "main")),
                    mock.patch.object(module, "download_source", download),
                    mock.patch.object(module, "_prepare_shaft_addons", return_value=None),
                    mock.patch.object(module.sys, "argv", ["bootstrap.py", *argv]),
                    mock.patch.object(module.sys, "stdout", stdout),
                    mock.patch.object(module.sys, "stderr", stderr),
                    mock.patch.object(module.sys, "stdin", stdin),
                    mock.patch.object(instruction_mode.os, "isatty", return_value=True),
                    mock.patch("builtins.input", return_value="no"),
                ):
                    with self.assertRaises(SystemExit) as raised:
                        module.main()
            self.assertEqual(2, raised.exception.code)
            self.assertIn("Type replace to continue.", stdout.getvalue())
            self.assertIn("CE_MODE_REPLACE_NEEDS_YES", stderr.getvalue())
            self.assertTrue(download.called)
            self.assertEqual("User rule\n", (project / "AGENTS.md").read_text(encoding="utf-8"))
            self.assertFalse((project / ".chaos-engine-state").exists())

    def test_env_replace_is_honored(self):
        module = load()
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            project = root / "project"
            project.mkdir()
            (project / "AGENTS.md").write_text("User rule\n", encoding="utf-8")
            home = root / "home"
            data = root / "data"
            home.mkdir()
            data.mkdir()
            download = mock.Mock(side_effect=AssertionError("downloaded"))
            with _isolated(home, data):
                os.environ["CHAOS_ENGINE_MODE"] = "replace"
                code, _stdout, stderr = self._run(
                    module,
                    project,
                    ["--project", str(project), "--repository", "Example/Project"],
                    download=download,
                )
            self.assertEqual(2, code, stderr)
            self.assertIn("CE_MODE_REPLACE_NEEDS_YES", stderr)
            self.assertEqual("User rule\n", (project / "AGENTS.md").read_text(encoding="utf-8"))
            self.assertFalse(download.called)

    def test_user_scope_replace_conflicts(self):
        module = load()
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            project = root / "project"
            project.mkdir()
            home = root / "home"
            data = root / "data"
            home.mkdir()
            data.mkdir()
            download = mock.Mock(side_effect=AssertionError("downloaded"))
            with _isolated(home, data):
                code, _stdout, stderr = self._run(
                    module,
                    project,
                    [
                        "--project",
                        str(project),
                        "--repository",
                        "Example/Project",
                        "--scope",
                        "user",
                        "--mode",
                        "replace",
                        "--yes",
                    ],
                    download=download,
                )
            self.assertEqual(2, code, stderr)
            self.assertIn("CE_MODE_SCOPE_CONFLICT", stderr)
            self.assertEqual([], list(project.iterdir()))
            self.assertFalse(download.called)
            self.assertFalse((data / "user-receipt.json").exists())

    def test_replace_yes_backs_up_and_deletes_class_i(self):
        module = load()
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            project = root / "project"
            project.mkdir()
            (project / "AGENTS.md").write_text("User rule\n", encoding="utf-8")
            (project / ".cursorrules").write_text("old cursor\n", encoding="utf-8")
            (project / "notes.txt").write_text("keep\n", encoding="utf-8")
            _git(project, "init", "-q")
            _git(project, "add", "AGENTS.md", ".cursorrules", "notes.txt")
            _git(project, "commit", "-q", "-m", "seed")
            home = root / "home"
            data = root / "data"
            home.mkdir()
            data.mkdir()
            with _isolated(home, data):
                code, _stdout, stderr = self._run(
                    module,
                    project,
                    [
                        "--project",
                        str(project),
                        "--repository",
                        "Example/Project",
                        "--mode",
                        "replace",
                        "--yes",
                        "--skip-tools",
                    ],
                    download=_fake_download,
                )
            self.assertEqual(0, code, stderr)
            self.assertEqual("keep\n", (project / "notes.txt").read_text(encoding="utf-8"))
            self.assertFalse((project / ".cursorrules").exists())
            backups = list((project / ".chaos-engine-state" / "backups").glob("*-replace"))
            self.assertEqual(1, len(backups), stderr)
            self.assertEqual(
                "User rule\n",
                (backups[0] / "files" / "AGENTS.md").read_text(encoding="utf-8"),
            )
            self.assertEqual(
                "old cursor\n",
                (backups[0] / "files" / ".cursorrules").read_text(encoding="utf-8"),
            )
            live = (project / "AGENTS.md").read_text(encoding="utf-8") if (project / "AGENTS.md").is_file() else ""
            self.assertNotIn("User rule", live)
