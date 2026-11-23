"""#183: Durable jobs idle-timeout stall detection, watch-log activity, and resume recovery."""

from __future__ import annotations

import importlib.util
import io
import json
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def load_jobs():
    spec = importlib.util.spec_from_file_location("ce_runtime_jobs_183", ROOT / "runtime" / "jobs.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class DurableJobsIdleStallTest(unittest.TestCase):
    def setUp(self):
        self.jobs = load_jobs()

    def _run(self, root: Path, *args: str) -> tuple[int, str, str]:
        stdout, stderr = io.StringIO(), io.StringIO()
        with redirect_stdout(stdout), redirect_stderr(stderr):
            code = self.jobs.main(["--root", str(root), *args])
        return code, stdout.getvalue(), stderr.getvalue()

    def test_wedged_silent_child_transitions_to_stalled_and_terminates_group(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "jobs"
            script = (
                "import subprocess, sys, time\n"
                "print('booting wedged worker', flush=True)\n"
                "sub = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)'])\n"
                "print(f'spawned_sub={sub.pid}', flush=True)\n"
                "time.sleep(60)\n"
            )
            code, out, err = self._run(
                root,
                "start",
                "wedged",
                "--idle-timeout",
                "0.4",
                "--heartbeat",
                "0.1",
                "--",
                sys.executable,
                "-c",
                script,
            )
            self.assertEqual(0, code, err)
            self.assertIn("started", out)

            wait_code, wait_out, _ = self._run(root, "wait", "wedged", "--timeout", "10")
            self.assertEqual(3, wait_code, wait_out)
            self.assertIn("stalled", wait_out)
            self.assertIn("no output or checkpoint for 0.4s", wait_out)

            status_code, status_json, _ = self._run(root, "status", "wedged", "--json")
            self.assertEqual(3, status_code)
            report = json.loads(status_json)
            self.assertEqual("stalled", report["state"])
            self.assertEqual("no output or checkpoint for 0.4s", report["stall_reason"])
            self.assertIsInstance(report["stalled_tail"], list)
            self.assertTrue(any("booting wedged worker" in line for line in report["stalled_tail"]))
            self.assertIsInstance(report["stalled_tree"], list)
            self.assertGreaterEqual(len(report["stalled_tree"]), 1)
            self.assertIn("pid", report["stalled_tree"][0])
            self.assertFalse(self.jobs.pid_alive(report["child_pid"]))
            self.assertEqual([], self.jobs.run_members(report["run_id"]))

    def test_periodic_output_watch_log_or_checkpoint_resets_idle_timer(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            root = base / "jobs"
            watched = base / "worker.log"

            # 1) Periodic writes to --watch-log keep a silent-stdout child alive past idle_timeout.
            watch_script = (
                "import pathlib, sys, time\n"
                f"p = pathlib.Path({str(watched)!r})\n"
                "for i in range(6):\n"
                "    time.sleep(0.15)\n"
                "    p.write_text(f'tick {i}\\n', encoding='utf-8')\n"
            )
            code, _, err = self._run(
                root,
                "start",
                "watched-job",
                "--idle-timeout",
                "0.5",
                "--heartbeat",
                "0.1",
                "--watch-log",
                str(watched),
                "--",
                sys.executable,
                "-c",
                watch_script,
            )
            self.assertEqual(0, code, err)
            wait_code, wait_out, _ = self._run(root, "wait", "watched-job", "--timeout", "10")
            self.assertEqual(0, wait_code, wait_out)
            status_code, status_json, _ = self._run(root, "status", "watched-job", "--json")
            self.assertEqual(0, status_code)
            self.assertEqual("done", json.loads(status_json)["state"])

            # 2) Periodic job checkpoints keep a silent-stdout child alive past idle_timeout.
            ckpt_script = (
                "import subprocess, sys, time\n"
                f"jobs_py = {str(ROOT / 'runtime' / 'jobs.py')!r}\n"
                f"root_dir = {str(root)!r}\n"
                "for i in range(6):\n"
                "    time.sleep(0.15)\n"
                "    subprocess.run([sys.executable, jobs_py, '--root', root_dir, 'checkpoint', 'ckpt-job', f'step-{i}'], check=True)\n"
            )
            code, _, err = self._run(
                root,
                "start",
                "ckpt-job",
                "--idle-timeout",
                "0.5",
                "--heartbeat",
                "0.1",
                "--",
                sys.executable,
                "-c",
                ckpt_script,
            )
            self.assertEqual(0, code, err)
            wait_code, wait_out, _ = self._run(root, "wait", "ckpt-job", "--timeout", "10")
            self.assertEqual(0, wait_code, wait_out)
            status_code, status_json, _ = self._run(root, "status", "ckpt-job", "--json")
            self.assertEqual(0, status_code)
            self.assertEqual("done", json.loads(status_json)["state"])

    def test_resume_recovers_stalled_job_and_stops_at_max_runs(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            root = base / "jobs"
            flag = base / "unwedge.flag"
            watched = base / "extra.log"
            script = (
                "import pathlib, time\n"
                f"if not pathlib.Path({str(flag)!r}).exists():\n"
                "    time.sleep(60)\n"
                "print('recovered and finished', flush=True)\n"
            )
            code, _, err = self._run(
                root,
                "start",
                "recoverable",
                "--idle-timeout",
                "0.4",
                "--heartbeat",
                "0.1",
                "--max-runs",
                "2",
                "--watch-log",
                str(watched),
                "--",
                sys.executable,
                "-c",
                script,
            )
            self.assertEqual(0, code, err)

            # Run 1 stalls.
            wait_code, _, _ = self._run(root, "wait", "recoverable", "--timeout", "10")
            self.assertEqual(3, wait_code)

            # Resume starts run 2 and preserves idle_timeout_s and watch_logs.
            res_code, res_out, _ = self._run(root, "resume", "recoverable")
            self.assertEqual(0, res_code, res_out)
            self.assertIn("took over stalled run", res_out)

            # Run 2 also stalls because flag is still absent.
            wait_code, _, _ = self._run(root, "wait", "recoverable", "--timeout", "10")
            self.assertEqual(3, wait_code)
            _, status_json, _ = self._run(root, "status", "recoverable", "--json")
            report = json.loads(status_json)
            self.assertEqual("stalled", report["state"])
            self.assertEqual(2, report["runs"])
            self.assertEqual(0.4, report["idle_timeout_s"])
            self.assertEqual([str(watched)], report["watch_logs"])

            # Run 3 is refused because runs (2) >= max_runs (2).
            refuse_code, refuse_out, _ = self._run(root, "resume", "recoverable")
            self.assertEqual(4, refuse_code)
            self.assertIn("needs a human", refuse_out)

            # With --force and flag present, resume recovers the stalled job to done.
            flag.write_text("ok\n", encoding="utf-8")
            force_code, force_out, _ = self._run(root, "resume", "recoverable", "--force")
            self.assertEqual(0, force_code, force_out)
            wait_code, _, _ = self._run(root, "wait", "recoverable", "--timeout", "10")
            self.assertEqual(0, wait_code)
            _, status_json, _ = self._run(root, "status", "recoverable", "--json")
            self.assertEqual("done", json.loads(status_json)["state"])

    def test_non_positive_idle_timeout_fails_closed(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "jobs"
            for bad in ("0", "-1", "-0.5"):
                code, _out, err = self._run(
                    root,
                    "start",
                    "invalid-timeout",
                    "--idle-timeout",
                    bad,
                    "--",
                    sys.executable,
                    "-c",
                    "pass",
                )
                self.assertEqual(1, code, bad)
                self.assertIn("--idle-timeout must be positive", err)


if __name__ == "__main__":
    unittest.main()
