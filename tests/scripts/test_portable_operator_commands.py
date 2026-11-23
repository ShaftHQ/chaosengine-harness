"""Windows launcher spelling and two-line git text. No shell=True."""

from __future__ import annotations

import importlib.util
import os
import subprocess
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


def _executable(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("", encoding="utf-8")
    path.chmod(0o755)


class PortableOperatorCommandTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.hosts = load(ROOT / "runtime" / "hosts.py", "ce_portable_hosts")
        cls.tool = load(ROOT / "tool.py", "ce_portable_tool")

    def test_windows_mcp_command_is_not_bare_python3(self):
        windows = self.hosts.owned_servers("nt", with_mcp=True)
        posix = self.hosts.owned_servers("posix", with_mcp=True)
        for name in ("chaosengine-memory", "chaosengine-mempalace"):
            self.assertNotEqual("python3", windows[name]["command"])
            self.assertEqual("py", windows[name]["command"])
            self.assertEqual("-3", windows[name]["args"][0])
            self.assertEqual("python3", posix[name]["command"])
            self.assertNotEqual("-3", posix[name]["args"][0])

    def test_operator_python_and_pack_commands_follow_windows(self):
        # os.name == "nt" makes pathlib build WindowsPath, which Linux cannot.
        with mock.patch.object(self.hosts.os, "name", "nt"):
            self.assertEqual("py -3", self.hosts._operator_python())
        with mock.patch.object(self.hosts, "_operator_python", return_value="py -3"):
            with tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                (root / "tests").mkdir()
                (root / "runtime").mkdir()
                commands = self.hosts.detect_pack_commands(root)
                self.assertEqual("py -3 -m pytest -q tests", commands["test"])
                self.assertNotIn("python3", commands["test"])
                palace = root / "palace"
                quarantine = palace / ".chaos-engine-quarantine"
                quarantine.mkdir(parents=True)
                (quarantine / "left").write_text("x", encoding="utf-8")
                detail = self.hosts._classify_missing_exact_after_quarantine(palace)["detail"]
                self.assertIn("py -3 .chaos-engine/tool.py stores refresh", detail)
                self.assertNotIn("python3", detail)
        with mock.patch.object(self.tool.os, "name", "nt"):
            self.assertEqual("py -3", self.tool.python_cli())
            self.assertIn("py -3 .chaos-engine/tool.py retrieve", self.tool.entry_retrieve())
            self.assertIn("py -3 .chaos-engine/tool.py retrieve", self.tool.retrieve_refusal())
            self.assertIn("py -3 .chaos-engine/tool.py entry --full", self.tool.entry_full_hint("abc"))
        with mock.patch.object(self.tool.os, "name", "posix"):
            self.assertEqual("python3", self.tool.python_cli())
            self.assertIn("python3 .chaos-engine/tool.py retrieve", self.tool.retrieve_refusal())

    def test_git_fix_next_is_two_lines_without_ampersand_or_upstream_splat(self):
        with mock.patch.object(self.tool, "default_branch_name", return_value="trunk"):
            text = self.tool.sync_fix_next(Path("."))
        self.assertEqual(
            "git fetch origin trunk\ngit merge --ff-only origin/trunk",
            text,
        )
        self.assertNotIn("&&", text)
        self.assertNotIn("@{", text)
        echoed = self.hosts._desync_fix_next(
            "fix-next: git fetch origin dev && git merge --ff-only origin/dev\n",
            "",
            None,
        )
        self.assertEqual("git fetch origin dev\ngit merge --ff-only origin/dev", echoed)
        self.assertNotIn("&&", echoed)
        self.assertNotIn("@{", echoed)
        kept = self.hosts._desync_fix_next(
            "fix-next: git fetch origin dev\ngit merge --ff-only origin/dev\n",
            "",
            None,
        )
        self.assertEqual("git fetch origin dev\ngit merge --ff-only origin/dev", kept)
        self.assertNotIn("&&", self.hosts.DESYNC_FIX_NEXT_FALLBACK)
        self.assertNotIn("@{", self.hosts.DESYNC_FIX_NEXT_FALLBACK)
        with tempfile.TemporaryDirectory() as temporary:
            named = self.hosts._desync_fix_next("no fix-next here", "", Path(temporary))
        self.assertEqual(
            "git fetch origin main\ngit merge --ff-only origin/main",
            named,
        )
        self.assertNotIn("&&", named)

    def test_powershell_adopt_uses_the_interpreter_probe(self):
        command = self.hosts.chaos_guard_locator_command(
            windows=True, host="copilot", event="userPromptSubmitted"
        )
        self.assertNotIn("python3 $s adopt", command)
        self.assertIn("u @($s,'adopt')", command)
        self.assertIn("'python3','py','python'", command)
        self.assertIn("& $c -3 @p", command)
        self.assertLessEqual(len(command), self.hosts.HOOK_COMMAND_MAX_CHARS)
        self.assertIsNone(self.hosts.powershell_hook_parse_error(command))
        unix = self.hosts.chaos_guard_locator_command(
            windows=False, host="copilot", event="Stop"
        )
        self.assertNotIn("function u(", unix)
        self.assertLessEqual(len(unix), self.hosts.HOOK_COMMAND_MAX_CHARS)

    def test_install_sh_jdk_lookup_keeps_linux_and_accepts_macos_layout(self):
        text = (ROOT / "install.sh").read_text(encoding="utf-8")
        start = text.index("_chaos_engine_jdk_home_under()")
        end = text.index("\nassert_maven_tools_jdk_preflight()")
        script = (
            "uname() { printf '%s\\n' \"$FAKE_UNAME\"; }\n"
            + text[start:end]
            + "\nfind_chaos_engine_managed_jdk_home\n"
        )

        def lookup(home: Path, uname_s: str, xdg: Path | None = None):
            env = {
                "HOME": str(home),
                "PATH": os.environ.get("PATH", "/usr/bin"),
                "FAKE_UNAME": uname_s,
            }
            if xdg is not None:
                env["XDG_DATA_HOME"] = str(xdg)
            return subprocess.run(
                ["sh", "-c", script],
                capture_output=True,
                text=True,
                env=env,
                check=False,
            )

        with tempfile.TemporaryDirectory() as temporary:
            home = Path(temporary) / "home"
            linux = home / ".local/share/chaos-engine/java/25/bin"
            _executable(linux / "java")
            _executable(linux / "javac")
            found = lookup(home, "Linux")
            self.assertEqual(0, found.returncode, found.stderr)
            self.assertEqual(str(linux.parent), found.stdout.strip())

            mac = home / "Library/Application Support/chaos-engine/java/25/Contents/Home/bin"
            _executable(mac / "java")
            _executable(mac / "javac")
            both = lookup(home, "Darwin")
            self.assertEqual(str(linux.parent), both.stdout.strip())

        with tempfile.TemporaryDirectory() as temporary:
            home = Path(temporary) / "home"
            mac = home / "Library/Application Support/chaos-engine/java/25/Contents/Home/bin"
            _executable(mac / "java")
            _executable(mac / "javac")
            found = lookup(home, "Darwin")
            self.assertEqual(0, found.returncode, found.stderr)
            self.assertEqual(str(mac.parent), found.stdout.strip())

        with tempfile.TemporaryDirectory() as temporary:
            home = Path(temporary) / "home"
            xdg = Path(temporary) / "xdg"
            data = xdg / "chaos-engine/java/21/bin"
            _executable(data / "java")
            _executable(data / "javac")
            found = lookup(home, "Linux", xdg)
            self.assertEqual(0, found.returncode, found.stderr)
            self.assertEqual(str(data.parent), found.stdout.strip())

    def test_install_ps1_also_reads_localappdata_java_root(self):
        powershell = (ROOT / "install.ps1").read_text(encoding="utf-8")
        start = powershell.index("function Get-ChaosEngineManagedJdkHome")
        end = powershell.index("function Assert-ChaosEngineMavenToolsJdkPreflight")
        body = powershell[start:end]
        self.assertIn(
            'Join-Path $env:USERPROFILE ".local\\share\\chaos-engine\\java"',
            body,
        )
        self.assertIn('Join-Path $env:LOCALAPPDATA "chaos-engine\\java"', body)


if __name__ == "__main__":
    unittest.main()
