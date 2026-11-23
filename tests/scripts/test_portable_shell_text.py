"""PowerShell 5.1 text and the py -3 / python3 install spelling."""

from __future__ import annotations

import importlib.util
import inspect
import tempfile
import unittest
import unittest.mock as mock
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def load(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"could not load {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class PortableShellTextTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.install = load(ROOT / "install.py", "ce_portable_shell_install")
        cls.bootstrap = load(ROOT / "bootstrap.py", "ce_portable_shell_bootstrap")

    def test_desync_fix_next_fallback_is_two_git_lines(self):
        text = self.install.DESYNC_FIX_NEXT_FALLBACK
        self.assertEqual(
            "git fetch origin main\ngit merge --ff-only origin/main",
            text,
        )
        self.assertNotIn("&&", text)
        self.assertNotIn("@{", text)

    def test_local_source_example_splits_for_powershell(self):
        with mock.patch.object(self.install.os, "name", "nt"):
            windows = self.install._local_source_required_message()
        self.assertNotIn("&&", windows)
        self.assertNotIn("python3", windows)
        self.assertIn("py -3 chaos-engine/install.py", windows)
        self.assertIn("git worktree add -f --detach ../ce-src <sha>\n", windows)
        self.assertIn("--project . --consumer", windows)
        self.assertIn("--source ../ce-src/chaos-engine --commit <sha>", windows)
        self.assertIn("--source <repo>/chaos-engine --commit <40-hex-sha>", windows)
        self.assertIn("--from-bundle", windows)
        posix = self.install._local_source_required_message()
        self.assertNotIn("&&", posix)
        self.assertIn("python3 chaos-engine/install.py", posix)
        self.assertNotIn("py -3", posix)

    def test_epilog_and_missing_install_fallback_follow_os_name(self):
        with tempfile.TemporaryDirectory() as temporary:
            self.assertIsNone(self.bootstrap.installer_cli_prefix(Path(temporary)))
        # os.name == "nt" makes pathlib build WindowsPath, which Linux cannot.
        # Spell the command only. parser() and next_fix_hint build paths.
        with mock.patch.object(self.bootstrap.os, "name", "nt"):
            self.assertEqual(
                "py -3 .chaos-engine/install.py",
                self.bootstrap._installer_cli_text(),
            )
        with mock.patch.object(self.bootstrap.os, "name", "posix"):
            self.assertEqual(
                "python3 .chaos-engine/install.py",
                self.bootstrap._installer_cli_text(),
            )
        with mock.patch.object(
            self.bootstrap,
            "_installer_cli_text",
            return_value="py -3 .chaos-engine/install.py",
        ):
            epilog = self.bootstrap.parser().epilog or ""
            hint = self.bootstrap.next_fix_hint(
                "CE-MAVEN", Exception("maven tools checksum failed"), None
            )
        self.assertIn("py -3 .chaos-engine/install.py uninstall --project .", epilog)
        self.assertNotIn("python3", epilog)
        self.assertIn(
            "py -3 .chaos-engine/install.py repair --project . --component maven-tools-mcp",
            hint,
        )
        self.assertNotIn("python3", hint)
        handoff = inspect.getsource(self.bootstrap._publish_heal_handoff)
        self.assertIn("installer_cli_prefix(project) or _installer_cli_text()", handoff)
        self.assertNotIn("python3 .chaos-engine/install.py", handoff)
        epilog = self.bootstrap.parser().epilog or ""
        hint = self.bootstrap.next_fix_hint(
            "CE-MAVEN", Exception("maven tools checksum failed"), None
        )
        self.assertIn("python3 .chaos-engine/install.py uninstall --project .", epilog)
        self.assertIn(
            "python3 .chaos-engine/install.py repair --project . --component maven-tools-mcp",
            hint,
        )

    def test_rate_limit_fix_hint_names_powershell(self):
        hint = self.bootstrap.next_fix_hint(
            "CE-GITHUB-RATE-LIMIT", Exception("rate limit"), None
        )
        self.assertIn('GITHUB_TOKEN="$(gh auth token)"', hint)
        self.assertIn("$env:GITHUB_TOKEN", hint)
        self.assertIn("(PowerShell: $env:GITHUB_TOKEN = gh auth token)", hint)
        self.assertIn("gh auth login", hint)
        self.assertIn("then rerun the same install one-liner.", hint)

    def test_agents_skill_path_count_is_four(self):
        text = (ROOT / "AGENTS.md").read_text(encoding="utf-8")
        self.assertEqual(4, text.count("skills/chaos-engine/SKILL.md"))
        self.assertIn("Read one of those, not both.", text)
        self.assertIn(".chaos-engine/identity.md", text)
