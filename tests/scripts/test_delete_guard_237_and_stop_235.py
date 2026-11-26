"""#237 benign mv and computed heads, and #235 Stop background-task report."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import textwrap
import time
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
HOOK = ROOT / "hooks" / "guard.py"


def _git(repo: Path, *args: str) -> None:
    subprocess.run(  # nosec B603
        [
            "git", "-C", str(repo),
            "-c", "user.name=t",
            "-c", "user.email=t@example.invalid",
            "-c", "commit.gpgsign=false",
            *args,
        ],
        check=True,
        capture_output=True,
        text=True,
    )


def _init_repo(repo: Path) -> None:
    repo.mkdir(parents=True)
    _git(repo, "init", "-q", "-b", "main")
    (repo / "keep.txt").write_text("keep", encoding="utf-8")
    _git(repo, "add", "keep.txt")
    _git(repo, "commit", "-qm", "init")


class BenignMvAndComputedHeadTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.repo = Path(self.temp.name) / "repo"
        _init_repo(self.repo)
        spec_root = ROOT
        import importlib.util

        spec = importlib.util.spec_from_file_location("ce_delete_guard_237", spec_root / "runtime" / "delete_guard.py")
        self.guard = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.guard)
        self.allow = mock.patch.object(self.guard, "DEFAULT_ALLOW", ())
        self.allow.start()

    def tearDown(self):
        self.allow.stop()
        self.temp.cleanup()

    def reason(self, command: str) -> str:
        return self.guard.block_reason(command, self.repo, self.repo)

    def test_in_repo_mv_of_untracked_tree_is_allowed(self):
        tree = self.repo / "allure-results"
        tree.mkdir()
        for index in range(44):
            (tree / f"file-{index}.txt").write_text("x", encoding="utf-8")
        reason = self.reason('mv allure-results "target/allure-prev-x"')
        self.assertEqual("", reason)

    def test_mv_outside_repo_or_onto_existing_file_is_refused(self):
        (self.repo / "a").write_text("a", encoding="utf-8")
        existing = self.repo / "existing_untracked_file"
        existing.write_text("old", encoding="utf-8")
        outside = self.reason('mv a "/tmp/outside-repo"')
        self.assertIn("untracked", outside)
        self.assertIn("matched `", outside)
        overwrite = self.reason("mv a existing_untracked_file")
        self.assertIn("untracked", overwrite)
        self.assertIn("matched `", overwrite)

    def test_computed_head_without_delete_verb_is_allowed(self):
        command = textwrap.dedent(
            """\
            cat <<'EOF'
            suite
            EOF
            sed -e 's/a/b/' pom.xml
            mvn -q test
            nohup bash -c 'echo hi' &
            "$MVN_BIN" test
            """
        )
        self.assertEqual("", self.reason(command))

    def test_rm_and_variable_rm_stay_refused_and_name_the_span(self):
        (self.repo / "dir").mkdir()
        (self.repo / "dir" / "only.txt").write_text("x", encoding="utf-8")
        (self.repo / "file").write_text("x", encoding="utf-8")
        removed = self.reason("rm -rf dir")
        self.assertIn("untracked", removed)
        self.assertIn("matched `", removed)
        self.assertIn("rm -rf dir", removed)
        variable = self.reason("CMD=rm; $CMD file")
        self.assertIn("computed command head", variable)
        self.assertIn("matched `", variable)
        self.assertIn("$CMD", variable)


class StopBackgroundJobTest(unittest.TestCase):
    def _run(self, cwd: Path, env: dict[str, str]) -> subprocess.CompletedProcess[str]:
        event = {"hook_event_name": "Stop", "session_id": "wave1-235", "cwd": str(cwd)}
        return subprocess.run(  # nosec B603
            [sys.executable, str(HOOK)],
            input=json.dumps(event),
            capture_output=True,
            text=True,
            check=False,
            env=env,
            cwd=str(cwd),
        )

    def _env(self, temporary: str) -> dict[str, str]:
        env = {
            key: value
            for key, value in os.environ.items()
            if key != "CHAOS_ENGINE_JOBS_DIR"
        }
        env.update({
            "TMPDIR": temporary,
            "TEMP": temporary,
            "TMP": temporary,
            "CHAOS_ENGINE_STORE_REFRESH": "0",
            "PYTHONDONTWRITEBYTECODE": "1",
        })
        return env

    def _lease(self, cwd: Path, name: str, state: str) -> None:
        directory = cwd / ".chaos-engine-state" / "jobs" / name
        directory.mkdir(parents=True)
        payload = {
            "state": state,
            "pid": os.getpid(),
            "command": "appium",
            "heartbeat_at": time.time(),
            "stale_s": 3600,
        }
        (directory / "lease.json").write_text(json.dumps(payload), encoding="utf-8")

    def test_stop_reports_a_live_job(self):
        with tempfile.TemporaryDirectory() as temporary:
            cwd = Path(temporary)
            self._lease(cwd, "emulator", "live")
            result = self._run(cwd, self._env(temporary))
            self.assertIn("emulator", result.stdout)
            self.assertIn(str(os.getpid()), result.stdout)
            self.assertIn("tool.py job stop emulator", result.stdout)

    def test_stop_is_quiet_when_jobs_are_done_or_absent(self):
        with tempfile.TemporaryDirectory() as temporary:
            cwd = Path(temporary)
            self._lease(cwd, "finished", "done")
            self._lease(cwd, "halted", "stopped")
            result = self._run(cwd, self._env(temporary))
            self.assertNotIn("Background tasks still running", result.stdout)
            self.assertNotIn("tool.py job stop", result.stdout)
        with tempfile.TemporaryDirectory() as temporary:
            cwd = Path(temporary)
            result = self._run(cwd, self._env(temporary))
            self.assertNotIn("Background tasks still running", result.stdout)


class WindowsMobileDocTest(unittest.TestCase):
    def test_windows_mobile_start_doc(self):
        path = ROOT / "references" / "windows-mobile-start.md"
        self.assertTrue(path.is_file())
        text = path.read_text(encoding="utf-8")
        self.assertIn("description:", text)
        self.assertIn("adb devices", text)
        self.assertIn("max-time", text)
        self.assertIn("MSYS2_ARG_CONV_EXCL=\"--base-path\"", text)
        self.assertIn("never", text.casefold())
        self.assertIn("unsupported OS", text)
        self.assertIn("getent", text)
        catalog = (ROOT / "references" / "level-1-catalog.md").read_text(encoding="utf-8")
        self.assertIn("windows-mobile-start.md", catalog)
        durable = (ROOT / "references" / "durable-jobs.md").read_text(encoding="utf-8")
        self.assertIn("bounded timeout", durable)
        self.assertIn("windows-mobile-start.md", durable)


if __name__ == "__main__":
    unittest.main()
