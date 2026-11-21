"""Renderer, inline drift, VT fallback, URL layout, JSON, and exit codes (#131)."""

from __future__ import annotations

import contextlib
import hashlib
import importlib.util
import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
import unittest.mock
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    if spec is None or spec.loader is None:
        raise ImportError(path)
    spec.loader.exec_module(module)
    return module


BOOTSTRAP = load("ce_bootstrap_ui_131", ROOT / "bootstrap.py")
INSTALL = load("ce_install_ui_131", ROOT / "install.py")
SYNC = load("ce_sync_ui_131", ROOT / "scripts" / "ci" / "sync_ce_ui.py")
UI = load("ce_ui_direct_131", ROOT / "runtime" / "ce_ui.py")


class _Tty(io.StringIO):
    def isatty(self) -> bool:
        return True


class CeUiTests(unittest.TestCase):
    def test_sync_check_fails_on_drift_and_passes_when_matched(self):
        self.assertTrue(SYNC.matches())
        target = ROOT / "bootstrap.py"
        original = target.read_text(encoding="utf-8")
        start = original.index(SYNC.START)
        end = original.index(SYNC.END)
        drifted = original[: start + len(SYNC.START)] + "drift = 1\n" + original[end:]
        with unittest.mock.patch.object(Path, "read_text", return_value=drifted):
            self.assertFalse(SYNC.matches(target))
        self.assertTrue(SYNC.matches())
        self.assertFalse(SYNC.rewrite())

    def test_legacy_conhost_setconsolemode_failure_is_plain(self):
        kernel = unittest.mock.Mock()
        kernel.GetStdHandle.return_value = 1
        kernel.GetConsoleMode.return_value = 1
        kernel.SetConsoleMode.return_value = 0
        windll = unittest.mock.Mock()
        windll.kernel32 = kernel
        import ctypes

        stream = _Tty()
        with unittest.mock.patch.object(UI.os, "name", "nt"), unittest.mock.patch.object(
            ctypes, "windll", windll, create=True
        ):
            caps = UI.detect_capabilities(stream, environ={"TERM": "xterm"})
            self.assertFalse(UI.enable_windows_vt())
        self.assertFalse(caps.cursor)
        self.assertEqual("none", caps.color)
        self.assertFalse(caps.hyperlinks)
        real_detect = BOOTSTRAP.detect_capabilities

        def detect_nt(stream=None, environ=None, *, vt=None):
            with unittest.mock.patch.object(BOOTSTRAP.os, "name", "nt"):
                return real_detect(stream, environ, vt=vt)

        with unittest.mock.patch.dict(os.environ, {"TERM": "xterm"}, clear=True), unittest.mock.patch.object(
            BOOTSTRAP, "detect_capabilities", detect_nt
        ), unittest.mock.patch.object(ctypes, "windll", windll, create=True), unittest.mock.patch.object(
            BOOTSTRAP.threading.Thread, "start", lambda self: None
        ):
            plain = _Tty()
            reporter = BOOTSTRAP.InstallReporter(stream=plain, clock=lambda: 1.0)
            reporter.start("Resolve source")
            reporter.close()
        self.assertNotIn("\x1b", plain.getvalue())

    def test_urls_are_not_split_mid_scheme_at_50_80_and_120(self):
        url = "https://example.com/" + ("a" * 180)
        prose = "Read the notes then open " + url + " before you continue with the rest of the sentence."
        for width in (50, 80, 120):
            lines = UI.layout_lines(prose, width)
            self.assertIn(url, lines)
            for line in lines:
                self.assertNotIn("https:", line.replace(url, ""))
                if not UI.line_may_exceed_width(line):
                    self.assertLessEqual(len(line), width, line)
            linked = UI.layout_lines(prose, width, hyperlinks=True)
            self.assertTrue(any(line.startswith("\x1b]8;;" + url) for line in linked))
            self.assertNotIn("https:\n", "\n".join(linked))

    def _main(self, argv, *, stdout, result, env=None):
        stderr = io.StringIO()
        patches = [
            unittest.mock.patch.object(BOOTSTRAP, "install_latest", return_value=result),
            unittest.mock.patch.object(BOOTSTRAP, "write_install_trace", return_value=None),
            unittest.mock.patch.object(BOOTSTRAP, "record_install_source", return_value=None),
            unittest.mock.patch.object(BOOTSTRAP, "post_install_packs", return_value=0),
            unittest.mock.patch.object(BOOTSTRAP, "_run_framework_offers", return_value=None),
            unittest.mock.patch.object(BOOTSTRAP.sys, "stdout", stdout),
            unittest.mock.patch.object(BOOTSTRAP.sys, "stderr", stderr),
            unittest.mock.patch.object(BOOTSTRAP.sys, "argv", argv),
        ]
        if env is not None:
            patches.append(unittest.mock.patch.dict(os.environ, env, clear=False))
        with contextlib.ExitStack() as stack:
            for patch in patches:
                stack.enter_context(patch)
            code = BOOTSTRAP.main()
        return code, stdout.getvalue(), stderr.getvalue()

    def test_json_stdout_is_one_document_and_beats_quiet(self):
        with tempfile.TemporaryDirectory() as temporary:
            result = {"status": "installed", "root": temporary, "commit": "a" * 40}
            argv = ["bootstrap.py", "--project", temporary, "--repository", "owner/repo", "--json", "--quiet"]
            code, stdout, stderr = self._main(argv, stdout=io.StringIO(), result=result)
            self.assertEqual(0, code)
            self.assertEqual(result, json.loads(stdout))
            self.assertNotIn("Next:", stderr)
            tty = _Tty()
            code, stdout, stderr = self._main(
                ["bootstrap.py", "--project", temporary, "--repository", "owner/repo"],
                stdout=tty,
                result=result,
                env={"CHAOS_ENGINE_JSON": "1", "TERM": "xterm"},
            )
            self.assertEqual(0, code)
            self.assertEqual(result, json.loads(stdout))
            self.assertNotIn("Next:", stderr)

    def test_exit_codes_keep_their_meanings(self):
        stderr = io.StringIO()
        with unittest.mock.patch.object(BOOTSTRAP.sys, "version_info", (3, 10, 0)), unittest.mock.patch.object(
            BOOTSTRAP.sys, "stderr", stderr
        ):
            self.assertEqual(2, BOOTSTRAP.main())
        project = Path(tempfile.mkdtemp())
        with unittest.mock.patch.object(BOOTSTRAP, "install_latest", side_effect=BOOTSTRAP.SyncKeepEdits(["owned.md"])), \
                unittest.mock.patch.object(BOOTSTRAP.sys, "argv", ["bootstrap.py", "--project", str(project), "--repository", "owner/repo", "--keep-edits"]), \
                unittest.mock.patch.object(BOOTSTRAP.sys, "stderr", io.StringIO()):
            self.assertEqual(3, BOOTSTRAP.main())
        with unittest.mock.patch.object(BOOTSTRAP, "install_latest", side_effect=RuntimeError("boom")), \
                unittest.mock.patch.object(BOOTSTRAP.sys, "argv", ["bootstrap.py", "--project", str(project), "--repository", "owner/repo"]), \
                unittest.mock.patch.object(BOOTSTRAP, "emit_install_failure", return_value=None), \
                unittest.mock.patch.object(BOOTSTRAP, "write_install_trace", return_value=None), \
                unittest.mock.patch.object(BOOTSTRAP.sys, "stderr", io.StringIO()):
            self.assertEqual(1, BOOTSTRAP.main())
        with unittest.mock.patch.object(BOOTSTRAP, "install_latest", return_value={"status": "installed", "commit": "b" * 40}), \
                unittest.mock.patch.object(BOOTSTRAP.sys, "argv", ["bootstrap.py", "--project", str(project), "--repository", "owner/repo", "--quiet"]), \
                unittest.mock.patch.object(BOOTSTRAP, "write_install_trace", return_value=None), \
                unittest.mock.patch.object(BOOTSTRAP, "record_install_source", return_value=None), \
                unittest.mock.patch.object(BOOTSTRAP, "post_install_packs", return_value=0), \
                unittest.mock.patch.object(BOOTSTRAP, "_run_framework_offers", return_value=None), \
                unittest.mock.patch.object(BOOTSTRAP.sys, "stdout", _Tty()), \
                unittest.mock.patch.object(BOOTSTRAP.sys, "stderr", io.StringIO()):
            self.assertEqual(0, BOOTSTRAP.main())

    def test_log_and_ci_have_one_line_per_completed_step_and_no_cursor(self):
        for extra in ({}, {"CI": "true"}):
            stream = _Tty()
            env = {"TERM": "xterm", "COLUMNS": "80"}
            env.update(extra)
            with unittest.mock.patch.dict(os.environ, env, clear=True), unittest.mock.patch.object(
                BOOTSTRAP.threading.Thread, "start", lambda self: None
            ):
                reporter = BOOTSTRAP.InstallReporter(stream=stream, clock=lambda: 1.0)
                reporter.start("Resolve source", remaining=("Download source",))
                reporter.complete("Resolve source", remaining=("Download source",))
                reporter.start("Download source", remaining=())
                reporter.close()
            text = stream.getvalue()
            if extra:
                self.assertNotIn("\x1b[", text)
                self.assertEqual(text.count("DONE  "), 1)
                self.assertNotIn("START ", text)
            else:
                self.assertIn("\x1b[", text)

    def test_cursor_is_independent_of_colour(self):
        tty = _Tty()
        with unittest.mock.patch.dict(os.environ, {"TERM": "xterm", "NO_COLOR": "1"}, clear=True):
            caps = UI.detect_capabilities(tty, environ=os.environ)
        self.assertTrue(caps.cursor)
        self.assertEqual("none", caps.color)
        pipe = io.StringIO()
        self.assertFalse(UI.cursor_enabled(tty=False, environ={"TERM": "xterm", "FORCE_COLOR": "1"}))
        self.assertTrue(UI.terminal_color_enabled(tty=False, environ={"TERM": "xterm", "FORCE_COLOR": "1"}))
        self.assertFalse(UI.terminal_color_enabled(tty=True, environ={"TERM": "xterm", "NO_COLOR": "1", "FORCE_COLOR": "1"}))
        self.assertFalse(UI.terminal_color_enabled(tty=True, environ={"TERM": "xterm", "CHAOS_ENGINE_COLOR": "never"}))
        self.assertTrue(UI.terminal_color_enabled(tty=False, environ={"TERM": "xterm", "CHAOS_ENGINE_COLOR": "always"}))
        self.assertFalse(UI.detect_capabilities(pipe, environ={"TERM": "xterm", "FORCE_COLOR": "1"}).cursor)

    def test_hyperlinks_follow_the_allowlist_and_stay_out_of_log(self):
        self.assertFalse(UI.hyperlinks_allowed({"VTE_VERSION": "4999"}))
        self.assertTrue(UI.hyperlinks_allowed({"VTE_VERSION": "5000"}))
        self.assertTrue(UI.hyperlinks_allowed({"TERM_PROGRAM": "WezTerm"}))
        self.assertFalse(UI.hyperlinks_allowed({"TERM_PROGRAM": "WezTerm", "CHAOS_ENGINE_HYPERLINKS": "0"}))
        self.assertTrue(UI.hyperlinks_allowed({"CHAOS_ENGINE_HYPERLINKS": "1"}))
        with unittest.mock.patch.object(UI.subprocess, "run", side_effect=AssertionError("tmux")):
            self.assertFalse(UI.hyperlinks_allowed({"TERM": "xterm"}))
        stream = io.StringIO()
        with unittest.mock.patch.dict(os.environ, {"TERM": "xterm", "CHAOS_ENGINE_HYPERLINKS": "1", "CI": "true"}, clear=True):
            reporter = BOOTSTRAP.InstallReporter(stream=stream, clock=lambda: 1.0)
            root = Path(tempfile.mkdtemp())
            reporter.announce(root, "owner/repo", "main")
            reporter.success(root, {"status": "healthy", "commit": "c" * 40, "components": {}}, {}, repository="owner/repo")
        self.assertNotIn("\x1b]8;;", stream.getvalue())
        self.assertNotIn("\x1b[", stream.getvalue())

    def test_install_py_imports_ce_ui_and_redacts_visible_failure_text(self):
        source = (ROOT / "install.py").read_text(encoding="utf-8")
        self.assertIn("import runtime.ce_ui as ce_ui", source)
        self.assertIn("ce_ui.redact", source)
        bootstrap = (ROOT / "bootstrap.py").read_text(encoding="utf-8")
        self.assertNotIn("import runtime.ce_ui", bootstrap)
        self.assertIn("# >>> generated: ce_ui", bootstrap)
        self.assertIn("# <<< generated: ce_ui", bootstrap)
        self.assertEqual(1, bootstrap.count("def redact("))
        self.assertEqual("[path]", INSTALL.ce_ui.redact("/tmp/secret-token"))

    def test_no_color_tty_frame_has_cursor_and_no_sgr(self):
        stream = _Tty()
        with unittest.mock.patch.dict(os.environ, {"TERM": "xterm", "NO_COLOR": "1", "COLUMNS": "80"}, clear=True), \
                unittest.mock.patch.object(BOOTSTRAP.threading.Thread, "start", lambda self: None):
            reporter = BOOTSTRAP.InstallReporter(stream=stream, clock=lambda: 1.0)
            reporter.start("Resolve source", remaining=("Download source",))
            reporter.complete("Resolve source", remaining=())
            reporter.close()
        text = stream.getvalue()
        self.assertRegex(text, r"\x1b\[\d+F")
        self.assertNotRegex(text, r"\x1b\[[0-9;]*m")

    def test_forced_color_paints_a_pipe_and_skips_the_cursor(self):
        cases = (
            {"CHAOS_ENGINE_COLOR": "always"},
            {"FORCE_COLOR": "1"},
            {"FORCE_COLOR": "1", "CHAOS_ENGINE_COLOR": "always"},
        )
        for extra in cases:
            stream = io.StringIO()
            env = {"TERM": "xterm-256color", "COLUMNS": "80", "PATH": "/usr/bin", "HOME": "/tmp"}
            env.update(extra)
            with self.subTest(extra=extra), unittest.mock.patch.dict(os.environ, env, clear=True), \
                    unittest.mock.patch.object(BOOTSTRAP.threading.Thread, "start", lambda self: None):
                reporter = BOOTSTRAP.InstallReporter(stream=stream, clock=lambda: 1.0)
                reporter.start("Resolve source", remaining=())
                reporter.complete("Resolve source", remaining=())
                text = stream.getvalue()
                self.assertTrue(reporter._color)
                self.assertFalse(reporter.cursor)
                self.assertRegex(text, r"\x1b\[[0-9;]*m")
                self.assertNotRegex(text, r"\x1b\[\d+F")
                self.assertNotIn("\x1b]8;;", text)

    def test_json_and_no_color_stay_plain_on_a_pipe(self):
        cases = (
            {"CHAOS_ENGINE_JSON": "1", "CHAOS_ENGINE_COLOR": "always", "FORCE_COLOR": "1"},
            {"NO_COLOR": "1", "FORCE_COLOR": "1", "CHAOS_ENGINE_COLOR": "always"},
            {"CHAOS_ENGINE_COLOR": "never", "FORCE_COLOR": "1"},
        )
        for extra in cases:
            stream = io.StringIO()
            env = {"TERM": "xterm-256color", "COLUMNS": "80", "PATH": "/usr/bin", "HOME": "/tmp"}
            env.update(extra)
            with self.subTest(extra=extra), unittest.mock.patch.dict(os.environ, env, clear=True), \
                    unittest.mock.patch.object(BOOTSTRAP.threading.Thread, "start", lambda self: None):
                reporter = BOOTSTRAP.InstallReporter(stream=stream, clock=lambda: 1.0)
                reporter.start("Resolve source", remaining=())
                reporter.complete("Resolve source", remaining=())
                text = stream.getvalue()
                self.assertFalse(reporter._color)
                self.assertFalse(reporter.cursor)
                self.assertNotRegex(text, r"\x1b\[[0-9;]*m")
                self.assertNotRegex(text, r"\x1b\[\d+F")


class Stage0ShellTests(unittest.TestCase):
    def _script(self, directory: Path) -> Path:
        target = directory / "install.sh"
        target.write_text((ROOT / "install.sh").read_text(encoding="utf-8"), encoding="utf-8")
        target.chmod(0o755)
        return target

    def _curl(self, directory: Path, body: str) -> dict[str, str]:
        binary = directory / "bin"
        binary.mkdir()
        curl = binary / "curl"
        curl.write_text(body, encoding="utf-8")
        curl.chmod(0o755)
        env = os.environ.copy()
        env["PATH"] = str(binary) + os.pathsep + env.get("PATH", "")
        return env

    def test_failed_download_prints_installing_and_download_once(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            script = self._script(root)
            env = self._curl(
                root,
                "#!/bin/sh\necho 'curl: (7) Failed to connect' >&2\nexit 7\n",
            )
            completed = subprocess.run(
                ["sh", str(script)],
                cwd=root,
                env=env,
                capture_output=True,
                text=True,
                timeout=30,
                check=False,
            )
        self.assertEqual(7, completed.returncode)
        self.assertEqual(1, completed.stderr.count("Installing ChaosEngine into"))
        self.assertEqual(1, completed.stderr.count("Download:"))
        self.assertIn("bootstrap.py", completed.stderr)

    def test_verbose_download_failure_does_not_print_the_preamble_twice(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            script = self._script(root)
            env = self._curl(
                root,
                "#!/bin/sh\necho 'curl: (7) Failed to connect' >&2\nexit 7\n",
            )
            completed = subprocess.run(
                ["sh", str(script), "--verbose"],
                cwd=root,
                env=env,
                capture_output=True,
                text=True,
                timeout=30,
                check=False,
            )
        self.assertEqual(7, completed.returncode)
        self.assertEqual(1, completed.stderr.count("Installing ChaosEngine into"))
        self.assertEqual(1, completed.stderr.count("Download:"))

    def test_quiet_success_omits_the_stage0_preamble(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            script = self._script(root)
            env = self._curl(
                root,
                "#!/bin/sh\n"
                "out=\n"
                "while [ $# -gt 0 ]; do\n"
                "  if [ \"$1\" = \"-o\" ]; then out=$2; shift 2; continue; fi\n"
                "  shift\n"
                "done\n"
                "printf '%s\\n' 'raise SystemExit(0)' > \"$out\"\n",
            )
            completed = subprocess.run(
                ["sh", str(script)],
                cwd=root,
                env=env,
                capture_output=True,
                text=True,
                timeout=30,
                check=False,
            )
        self.assertEqual(0, completed.returncode, completed.stderr)
        self.assertNotIn("Installing ChaosEngine into", completed.stderr)
        self.assertNotIn("Download:", completed.stderr)

    def test_uv_python_find_failure_prints_stage0_once(self):
        targets = {
            ("Linux", "x86_64"): "x86_64-unknown-linux-gnu",
            ("Linux", "aarch64"): "aarch64-unknown-linux-gnu",
            ("Linux", "arm64"): "aarch64-unknown-linux-gnu",
            ("Darwin", "x86_64"): "x86_64-apple-darwin",
            ("Darwin", "arm64"): "aarch64-apple-darwin",
        }
        target = targets.get((os.uname().sysname, os.uname().machine))
        if target is None:
            self.skipTest("this platform has no uv archive in install.sh")
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            payload = root / "payload" / f"uv-{target}"
            payload.mkdir(parents=True)
            uv = payload / "uv"
            uv.write_text(
                "#!/bin/sh\n"
                "if [ \"$2\" = install ]; then exit 0; fi\n"
                "echo find-failed >&2\n"
                "exit 4\n",
                encoding="utf-8",
            )
            uv.chmod(0o755)
            archive = root / "uv.tar.gz"
            subprocess.run(
                ["tar", "-czf", str(archive), "-C", str(root / "payload"), f"uv-{target}"],
                check=True,
            )
            digest = hashlib.sha256(archive.read_bytes()).hexdigest()
            needle = f"uv_target={target}; uv_sha="
            script_text = (ROOT / "install.sh").read_text(encoding="utf-8")
            self.assertIn(needle, script_text)
            rewritten = []
            for line in script_text.splitlines(keepends=True):
                if needle in line:
                    line = line.split("uv_sha=", 1)[0] + f"uv_sha={digest} ;;\n"
                rewritten.append(line)
            script = self._script(root)
            script.write_text("".join(rewritten), encoding="utf-8")
            bindir = root / "bin"
            bindir.mkdir()
            curl = bindir / "curl"
            curl.write_text(
                "#!/bin/sh\n"
                "out=\n"
                "while [ $# -gt 0 ]; do\n"
                "  if [ \"$1\" = -o ]; then out=$2; shift 2; continue; fi\n"
                "  shift\n"
                "done\n"
                f"cp {archive} \"$out\"\n",
                encoding="utf-8",
            )
            curl.chmod(0o755)
            for name in ("python3", "python", "py"):
                stub = bindir / name
                stub.write_text("#!/bin/sh\nexit 1\n", encoding="utf-8")
                stub.chmod(0o755)
            env = os.environ.copy()
            env["PATH"] = str(bindir) + os.pathsep + env.get("PATH", "")
            completed = subprocess.run(
                ["sh", str(script)],
                cwd=root,
                env=env,
                capture_output=True,
                text=True,
                timeout=30,
                check=False,
            )
        self.assertEqual(4, completed.returncode, completed.stderr)
        self.assertEqual(1, completed.stderr.count("Installing ChaosEngine into"))
        self.assertEqual(1, completed.stderr.count("Download:"))

    def test_no_python_tool_failure_prints_stage0_once(self):
        """tar, mkdir, and ln must not die under set -e before the stage-0 lines."""
        targets = {
            ("Linux", "x86_64"): "x86_64-unknown-linux-gnu",
            ("Linux", "aarch64"): "aarch64-unknown-linux-gnu",
            ("Linux", "arm64"): "aarch64-unknown-linux-gnu",
            ("Darwin", "x86_64"): "x86_64-apple-darwin",
            ("Darwin", "arm64"): "aarch64-apple-darwin",
        }
        target = targets.get((os.uname().sysname, os.uname().machine))
        if target is None:
            self.skipTest("this platform has no uv archive in install.sh")
        cases = (
            ("tar", "#!/bin/sh\necho 'tar:' >&2\nexit 3\n", 3),
            ("mkdir", "#!/bin/sh\necho 'mkdir:' >&2\nexit 5\n", 5),
            ("ln", "#!/bin/sh\necho 'ln:' >&2\nexit 6\n", 6),
        )
        uv_body = (
            "#!/bin/sh\n"
            "if [ \"$2\" = install ]; then exit 0; fi\n"
            "if [ \"$2\" = find ]; then printf '%s\\n' /opt/ce-python; exit 0; fi\n"
            "echo unexpected >&2\nexit 9\n"
        )
        for tool, body, status in cases:
            with self.subTest(tool=tool):
                with tempfile.TemporaryDirectory() as temporary:
                    root = Path(temporary)
                    payload = root / "payload" / f"uv-{target}"
                    payload.mkdir(parents=True)
                    uv = payload / "uv"
                    uv.write_text(uv_body, encoding="utf-8")
                    uv.chmod(0o755)
                    archive = root / "uv.tar.gz"
                    subprocess.run(
                        ["tar", "-czf", str(archive), "-C", str(root / "payload"), f"uv-{target}"],
                        check=True,
                    )
                    digest = hashlib.sha256(archive.read_bytes()).hexdigest()
                    needle = f"uv_target={target}; uv_sha="
                    script_text = (ROOT / "install.sh").read_text(encoding="utf-8")
                    self.assertIn(needle, script_text)
                    rewritten = []
                    for line in script_text.splitlines(keepends=True):
                        if needle in line:
                            line = line.split("uv_sha=", 1)[0] + f"uv_sha={digest} ;;\n"
                        rewritten.append(line)
                    script = self._script(root)
                    script.write_text("".join(rewritten), encoding="utf-8")
                    bindir = root / "bin"
                    bindir.mkdir()
                    curl = bindir / "curl"
                    curl.write_text(
                        "#!/bin/sh\n"
                        "out=\n"
                        "while [ $# -gt 0 ]; do\n"
                        "  if [ \"$1\" = -o ]; then out=$2; shift 2; continue; fi\n"
                        "  shift\n"
                        "done\n"
                        f"cp {archive} \"$out\"\n",
                        encoding="utf-8",
                    )
                    curl.chmod(0o755)
                    stub = bindir / tool
                    stub.write_text(body, encoding="utf-8")
                    stub.chmod(0o755)
                    for name in ("python3", "python", "py"):
                        py = bindir / name
                        py.write_text("#!/bin/sh\nexit 1\n", encoding="utf-8")
                        py.chmod(0o755)
                    env = os.environ.copy()
                    env["PATH"] = str(bindir) + os.pathsep + env.get("PATH", "")
                    env["HOME"] = str(root / "home")
                    env.pop("XDG_DATA_HOME", None)
                    completed = subprocess.run(
                        ["sh", str(script)],
                        cwd=root,
                        env=env,
                        capture_output=True,
                        text=True,
                        timeout=30,
                        check=False,
                    )
                self.assertEqual(status, completed.returncode, completed.stderr)
                self.assertEqual(1, completed.stderr.count("Installing ChaosEngine into"))
                self.assertEqual(1, completed.stderr.count("Download:"))


class MavenCaptureTests(unittest.TestCase):
    def test_package_stdout_stays_off_the_parent_stdout(self):
        pack = load("ce_java_pack_131", ROOT / "packs" / "java" / "installer.py")
        stdout = io.StringIO()
        stderr = io.StringIO()
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            pack._run_captured_build(
                subprocess.run,
                [
                    sys.executable,
                    "-c",
                    "import sys; sys.stdout.write('[INFO] BUILD SUCCESS\\n'); sys.stderr.write('mvn-err\\n')",
                ],
                check=True,
                timeout=30,
            )
        self.assertEqual("", stdout.getvalue())
        self.assertIn("[INFO] BUILD SUCCESS", stderr.getvalue())
        self.assertIn("mvn-err", stderr.getvalue())

    def test_package_failure_keeps_stdout_on_the_exception(self):
        pack = load("ce_java_pack_131", ROOT / "packs" / "java" / "installer.py")
        with self.assertRaises(subprocess.CalledProcessError) as caught:
            pack._run_captured_build(
                subprocess.run,
                [
                    sys.executable,
                    "-c",
                    "import sys; sys.stdout.write('[INFO] FAIL\\n'); sys.exit(3)",
                ],
                check=True,
                timeout=30,
            )
        self.assertIn("[INFO] FAIL", caught.exception.stdout or "")


class SubprocessHelperTests(unittest.TestCase):
    def test_run_captured_does_not_inherit_stderr(self):
        leaked = io.StringIO()
        with unittest.mock.patch.object(UI.sys, "stderr", leaked):
            done = UI.run_captured([os.environ.get("SHELL", "sh"), "-c", "echo tool-name >&2"], timeout=10)
        self.assertEqual("", leaked.getvalue())
        self.assertIn("tool-name", done.trace[0]["stderr"])
        self.assertEqual(0, done.returncode)


if __name__ == "__main__":
    unittest.main()
