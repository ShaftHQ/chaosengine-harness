"""Session scratch folder and the one-hour session-end retrospective."""

from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
HOOK = ROOT / "hooks/guard.py"


def load_scratch():
    spec = importlib.util.spec_from_file_location(
        "session_scratch_under_test", ROOT / "hooks/session_scratch.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def isolated_env(temporary: str) -> dict[str, str]:
    protected = [
        item
        for item in os.environ.get("CHAOS_ENGINE_PROTECTED_CHECKOUTS", "").split(os.pathsep)
        if item
    ]
    protected.append(str(ROOT))
    return {
        **os.environ,
        "TMPDIR": temporary,
        "TEMP": temporary,
        "TMP": temporary,
        "CHAOS_ENGINE_PROTECTED_CHECKOUTS": os.pathsep.join(protected),
        "CHAOS_ENGINE_STORE_REFRESH": "0",
    }


class SessionScratchTest(unittest.TestCase):
    def test_root_and_subagent_share_one_folder(self):
        scratch = load_scratch()
        with tempfile.TemporaryDirectory() as temporary:
            project = Path(temporary)
            self.assertTrue(scratch.ensure(project, "same-session"))
            self.assertFalse(scratch.ensure(project, "same-session"))
            scratch.append_note(
                project, "same-session", agent="root", kind="thinking", text="choose the small fix"
            )
            scratch.open_agent(project, "same-session", "reviewer")
            scratch.append_note(
                project,
                "same-session",
                agent="reviewer",
                kind="enhancement",
                text="file the hook gap",
            )
            notes = scratch.load_notes(project, "same-session")
            self.assertEqual(
                ["thinking", "enhancement"],
                [note["kind"] for note in notes],
            )
            self.assertEqual(["reviewer"], scratch.open_agents(project, "same-session"))
            rule = (project / ".grok/rules/session-scratch.md").read_text(encoding="utf-8")
            self.assertIn(scratch.relative_folder("same-session"), rule)
            self.assertNotIn(str(project), rule)

    def test_notes_drop_secrets_and_home_paths(self):
        scratch = load_scratch()
        with tempfile.TemporaryDirectory() as temporary:
            project = Path(temporary)
            scratch.append_note(
                project,
                "redact",
                agent="root",
                kind="thinking",
                text="token=abc123 see /home/someone/secret",
            )
            text = scratch.load_notes(project, "redact")[0]["text"]
            self.assertNotIn("abc123", text)
            self.assertNotIn("/home/someone", text)
            self.assertIn("[redacted]", text)
            self.assertIn("[path]", text)

    def test_retrospective_runs_once_after_one_hour_and_files_one_issue(self):
        scratch = load_scratch()
        calls: list[list[str]] = []

        def run(args: list[str]) -> tuple[int, str]:
            calls.append(args)
            if "list" in args:
                return 0, "[]"
            return 0, "https://github.com/ShaftHQ/chaosengine-harness/issues/74\n"

        with tempfile.TemporaryDirectory() as temporary:
            project = Path(temporary)
            scratch.append_note(
                project, "long", agent="root", kind="enhancement", text="wait until session end"
            )
            scratch.append_note(
                project, "long", agent="root", kind="enhancement", text="wait until session end"
            )
            early = scratch.retrospective(project, "long", 60, run=run)
            self.assertIn(scratch.PREVENTION_QUESTION, early or "")
            self.assertIn("## Prevention", early or "")
            self.assertTrue((scratch.folder(project, "long") / "report.md").is_file())
            self.assertEqual([], calls)
            report = scratch.retrospective(project, "long", 3601, run=run)
            self.assertIn("wait until session end", report)
            self.assertIn(scratch.PREVENTION_QUESTION, report)
            self.assertIn("## Prevention", report)
            self.assertIn("https://github.com/ShaftHQ/chaosengine-harness/issues/74", report)
            self.assertIsNone(scratch.retrospective(project, "long", 99999, run=run))
        creates = [args for args in calls if "create" in args]
        self.assertEqual(1, len(creates))

    def test_timed_out_create_stays_pending_and_a_later_retrospective_files_it_once(self):
        scratch = load_scratch()
        text = "retry the unfiled enhancement"
        url = "https://github.com/ShaftHQ/chaosengine-harness/issues/82"
        creates: list[list[str]] = []
        create_result = {"code": 124, "stdout": ""}
        marker_during_gh: list[bool] = []

        def run(args: list[str]) -> tuple[int, str]:
            marker_during_gh.append(done.exists())
            if len(args) >= 3 and args[1] == "issue" and args[2] == "create":
                creates.append(args)
                return create_result["code"], create_result["stdout"]
            if len(args) >= 3 and args[1] == "issue" and args[2] == "list":
                return 0, "[]"
            return 0, ""

        with tempfile.TemporaryDirectory() as temporary:
            project = Path(temporary)
            done = scratch.folder(project, "retry") / "retro.done"
            scratch.append_note(project, "retry", agent="root", kind="enhancement", text=text)
            first = scratch.retrospective(project, "retry", 3601, run=run)
            self.assertIsNotNone(first)
            self.assertIn(text, first)
            self.assertIn("Not filed in this pass:", first)
            self.assertNotIn(url, first)
            self.assertTrue(marker_during_gh)
            self.assertFalse(any(marker_during_gh))
            self.assertFalse(done.exists())
            stored = scratch.load_notes(project, "retry")
            self.assertIn(text, [note["text"] for note in stored])
            create_result["code"] = 0
            create_result["stdout"] = url + "\n"
            second = scratch.retrospective(project, "retry", 7202, run=run)
            self.assertIsNotNone(
                second,
                "retro.done must not drop an unfiled note; done existed=%s" % done.exists(),
            )
            self.assertIn(url, second)
            self.assertNotIn("Not filed in this pass:", second)
            self.assertFalse(any(marker_during_gh))
            third = scratch.retrospective(project, "retry", 10803, run=run)
            self.assertIsNone(third)
            self.assertEqual(2, len(creates))
            self.assertTrue(done.is_file())

    def test_kill_leftover_marker_files_when_the_text_is_not_in_filed_txt(self):
        scratch = load_scratch()
        text = "filed after a kill left the marker"
        url = "https://github.com/ShaftHQ/chaosengine-harness/issues/84"
        creates: list[list[str]] = []

        def run(args: list[str]) -> tuple[int, str]:
            if len(args) >= 3 and args[1] == "issue" and args[2] == "create":
                creates.append(args)
                return 0, url + "\n"
            if len(args) >= 3 and args[1] == "issue" and args[2] == "list":
                return 0, "[]"
            return 0, ""

        with tempfile.TemporaryDirectory() as temporary:
            project = Path(temporary)
            scratch.append_note(project, "killed", agent="root", kind="enhancement", text=text)
            target = scratch.folder(project, "killed")
            (target / "retro.done").write_bytes(b"")
            self.assertFalse((target / "filed.txt").exists())
            report = scratch.retrospective(project, "killed", 3601, run=run)
            self.assertIsNotNone(report)
            self.assertIn(url, report)
            self.assertIn(text, report)
            self.assertEqual(1, len(creates))
            self.assertIn(text.casefold(), (target / "filed.txt").read_text(encoding="utf-8"))
            again = scratch.retrospective(project, "killed", 7202, run=run)
            self.assertIsNone(again)
            self.assertEqual(1, len(creates))

    def test_default_gh_runner_stops_inside_file_budget(self):
        scratch = load_scratch()
        self.assertLessEqual(scratch.FILE_BUDGET_SECONDS, 2.0)
        text = "do not let the host kill cut the write"
        url = "https://github.com/ShaftHQ/chaosengine-harness/issues/83"
        with tempfile.TemporaryDirectory() as temporary:
            project = Path(temporary)
            bin_dir = project / "bin"
            bin_dir.mkdir()
            gh = bin_dir / "gh"
            gh.write_text("#!/bin/sh\nsleep 30\nexit 0\n", encoding="utf-8")
            gh.chmod(0o755)
            scratch.append_note(project, "budget", agent="root", kind="enhancement", text=text)
            previous = os.environ.get("PATH", "")
            os.environ["PATH"] = f"{bin_dir}{os.pathsep}{previous}"
            try:
                started = time.monotonic()
                report = scratch.retrospective(project, "budget", scratch.ONE_HOUR_SECONDS + 1)
                elapsed = time.monotonic() - started
            finally:
                os.environ["PATH"] = previous
            self.assertIsNotNone(report)
            self.assertIn(text, report)
            self.assertLess(elapsed, 3.0)
            self.assertLess(elapsed, scratch.FILE_BUDGET_SECONDS + 0.9)

            def run(args: list[str]) -> tuple[int, str]:
                if len(args) >= 3 and args[1] == "issue" and args[2] == "list":
                    return 0, "[]"
                if len(args) >= 3 and args[1] == "issue" and args[2] == "create":
                    return 0, url + "\n"
                return 0, ""

            follow = scratch.retrospective(
                project, "budget", scratch.ONE_HOUR_SECONDS + 2, run=run
            )
            self.assertIsNotNone(follow)
            self.assertIn(url, follow)

    def test_distinct_notes_that_share_a_title_prefix_are_both_filed(self):
        scratch = load_scratch()
        prefix = "p" * 72
        calls: list[list[str]] = []

        def run(args: list[str]) -> tuple[int, str]:
            calls.append(args)
            if "list" in args:
                return 0, "[]"
            return 0, "https://github.com/ShaftHQ/chaosengine-harness/issues/80\n"

        with tempfile.TemporaryDirectory() as temporary:
            project = Path(temporary)
            scratch.append_note(
                project, "long", agent="root", kind="enhancement", text=prefix + " alpha"
            )
            scratch.append_note(
                project, "long", agent="root", kind="enhancement", text=prefix + " beta"
            )
            report = scratch.retrospective(project, "long", 3601, run=run)
        creates = [args for args in calls if "create" in args]
        self.assertEqual(2, len(creates))
        titles = [args[args.index("--title") + 1] for args in creates]
        self.assertNotEqual(titles[0], titles[1])
        self.assertIn("alpha", report or "")
        self.assertIn("beta", report or "")

    def test_short_session_asks_prevention_question_without_filing(self):
        scratch = load_scratch()
        calls: list[list[str]] = []

        def run(args: list[str]) -> tuple[int, str]:
            calls.append(args)
            return 0, "https://github.com/ShaftHQ/chaosengine-harness/issues/74\n"

        with tempfile.TemporaryDirectory() as temporary:
            project = Path(temporary)
            self.assertIsNone(scratch.retrospective(project, "", 10, run=run))
            self.assertIsNone(scratch.retrospective(project, "   ", None, run=run))
            scratch.append_note(
                project,
                "short-note",
                agent="root",
                kind="prevention",
                text="remember the hook gap",
            )
            noted = scratch.retrospective(project, "short-note", scratch.ONE_HOUR_SECONDS, run=run)
            self.assertIn(scratch.PREVENTION_QUESTION, noted or "")
            self.assertIn("## Prevention", noted or "")
            self.assertIn("remember the hook gap", noted or "")
            self.assertNotIn("tracked:", noted or "")
            written = (scratch.folder(project, "short-note") / "report.md").read_text(encoding="utf-8")
            self.assertEqual(noted, written)
            self.assertIsNone(
                scratch.retrospective(project, "short-note", scratch.ONE_HOUR_SECONDS, run=run)
            )
            for elapsed in (None, 0, 60):
                session = f"short-{elapsed}"
                report = scratch.retrospective(project, session, elapsed, run=run)
                self.assertIn(scratch.PREVENTION_QUESTION, report or "")
                self.assertIn("- unanswered", report or "")
                self.assertTrue((scratch.folder(project, session) / "report.md").is_file())
                self.assertIsNone(scratch.retrospective(project, session, elapsed, run=run))
        self.assertEqual([], calls)

    def test_long_session_files_prevention_note_and_asks_the_question(self):
        scratch = load_scratch()
        calls: list[list[str]] = []
        url = "https://github.com/ShaftHQ/chaosengine-harness/issues/91"

        def run(args: list[str]) -> tuple[int, str]:
            calls.append(args)
            if "list" in args:
                return 0, "[]"
            return 0, url + "\n"

        with tempfile.TemporaryDirectory() as temporary:
            project = Path(temporary)
            scratch.append_note(
                project, "hour", agent="root", kind="enhancement", text="keep the enhancement filing"
            )
            scratch.append_note(
                project,
                "hour",
                agent="root",
                kind="prevention",
                text="ask the prevention question every end",
            )
            report = scratch.retrospective(project, "hour", scratch.ONE_HOUR_SECONDS + 1, run=run)
            self.assertIn(scratch.PREVENTION_QUESTION, report or "")
            self.assertIn("## Prevention", report or "")
            self.assertIn("keep the enhancement filing", report or "")
            self.assertIn("ask the prevention question every end", report or "")
            self.assertIn(f"tracked: {url}", report or "")
            creates = [args for args in calls if "create" in args]
            self.assertEqual(2, len(creates))
            titles = [args[args.index("--title") + 1] for args in creates]
            self.assertTrue(any(title.startswith("Session enhancement:") for title in titles))
            self.assertTrue(any(title.startswith("Session prevention:") for title in titles))
            for args in creates:
                self.assertEqual(["gh", "issue", "create"], args[:3])
                self.assertIn("--body-file", args)
            self.assertIsNone(
                scratch.retrospective(project, "hour", scratch.ONE_HOUR_SECONDS + 2, run=run)
            )
            self.assertEqual(2, len([args for args in calls if "create" in args]))

    def test_followup_reads_latest_sealed_prevention_without_scanning(self):
        scratch = load_scratch()
        url = "https://github.com/ShaftHQ/chaosengine-harness/issues/93"

        def run(args: list[str]) -> tuple[int, str]:
            if "list" in args:
                return 0, "[]"
            return 0, url + "\n"

        with tempfile.TemporaryDirectory() as temporary:
            project = Path(temporary)
            other = scratch.folder(project, "other")
            other.mkdir(parents=True)
            (other / "report.md").write_text(
                "## Prevention\n- tracked: https://github.com/evil/hidden/issues/1\n",
                encoding="utf-8",
            )
            (other / "prevention.done").write_text("sealed\n", encoding="utf-8")
            short = scratch.retrospective(project, "quiet", None, run=run)
            self.assertIn("- unanswered", short or "")
            follow = scratch.prevention_followup(project)
            self.assertIn("## Prevention", follow)
            self.assertIn("- unanswered", follow)
            self.assertNotIn(scratch.PREVENTION_QUESTION, follow)
            self.assertNotIn("evil/hidden", follow)
            self.assertNotIn("# Session", follow)
            scratch.append_note(
                project, "local-only", agent="root", kind="prevention", text="not filed yet"
            )
            scratch.retrospective(project, "local-only", 60, run=run)
            self.assertEqual("", scratch.prevention_followup(project))
            scratch.append_note(
                project, "filed", agent="root", kind="prevention", text="file the harness gap"
            )
            scratch.append_note(
                project, "filed", agent="root", kind="enhancement", text="do not inject this enhancement"
            )
            long = scratch.retrospective(project, "filed", 3601, run=run)
            self.assertIn(scratch.PREVENTION_QUESTION, long or "")
            follow = scratch.prevention_followup(project)
            self.assertIn(f"- tracked: {url}", follow)
            self.assertNotIn("do not inject this enhancement", follow)
            self.assertNotIn("Elapsed seconds", follow)
            self.assertNotIn("evil/hidden", follow)

    def test_learning_session_reason_includes_the_prevention_question(self):
        spec = importlib.util.spec_from_file_location("ce_guard_prevention", HOOK)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        session = "learn-prevention-question"
        with tempfile.TemporaryDirectory() as temporary:
            previous = {key: os.environ.get(key) for key in ("TMPDIR", "TEMP", "TMP")}
            os.environ["TMPDIR"] = temporary
            os.environ["TEMP"] = temporary
            os.environ["TMP"] = temporary
            try:
                self.assertIsNone(
                    module.learning_session_reason(session, {"cwd": temporary, "hook_event_name": "Stop"})
                )
                module.reflection.record_activity(session, "delivery-complete")
                reason = module.learning_session_reason(
                    session, {"cwd": temporary, "hook_event_name": "Stop"}
                )
            finally:
                for key, value in previous.items():
                    if value is None:
                        os.environ.pop(key, None)
                    else:
                        os.environ[key] = value
        self.assertIsNotNone(reason)
        self.assertIn(module.session_scratch.PREVENTION_QUESTION, reason)
        self.assertIn("## Prevention", reason)
        self.assertIn("tracked: https://github.com/", reason)
        self.assertIn("nothing actionable", reason)

    def test_session_start_injects_unanswered_prevention_lines(self):
        scratch = load_scratch()
        with tempfile.TemporaryDirectory() as temporary:
            project = Path(temporary)
            scratch.retrospective(project, "ended", None, run=lambda args: (0, ""))
            result = subprocess.run(
                [sys.executable, str(HOOK)],
                input=json.dumps(
                    {"hook_event_name": "SessionStart", "session_id": "next-session", "cwd": str(project)}
                ),
                capture_output=True,
                text=True,
                check=False,
                env=isolated_env(temporary),
            )
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertIn("## Prevention", result.stdout)
        self.assertIn("- unanswered", result.stdout)
        self.assertNotIn("# Session prevention", result.stdout)
        self.assertNotIn("Elapsed seconds", result.stdout)

    def test_idle_stop_demands_the_hour_retrospective_and_session_end_files_once(self):
        with tempfile.TemporaryDirectory() as temporary:
            project = Path(temporary)
            env = isolated_env(temporary)
            started = subprocess.run(
                [
                    sys.executable,
                    "-c",
                    "import importlib.util, sys; "
                    "spec = importlib.util.spec_from_file_location('ce_reflection', sys.argv[1]); "
                    "module = importlib.util.module_from_spec(spec); "
                    "spec.loader.exec_module(module); "
                    "module.record_session_start('retro-end', '2020-01-01T00:00:00+00:00')",
                    str(ROOT / "hooks/reflection.py"),
                ],
                capture_output=True,
                text=True,
                check=False,
                env=env,
            )
            self.assertEqual(0, started.returncode, started.stderr)
            scratch = load_scratch()
            scratch.append_note(
                project, "retro-end", agent="root", kind="enhancement", text="share one report"
            )
            bin_dir = project / "bin"
            bin_dir.mkdir()
            log = project / "gh.log"
            gh = bin_dir / "gh"
            gh.write_text(
                "#!/bin/sh\n"
                "printf '%s\\n' \"$@\" >> \"$GH_LOG\"\n"
                "if [ \"$1\" = issue ] && [ \"$2\" = list ]; then echo '[]'; exit 0; fi\n"
                "if [ \"$1\" = issue ] && [ \"$2\" = create ]; then "
                "echo 'https://github.com/ShaftHQ/chaosengine-harness/issues/74'; exit 0; fi\n"
                "exit 0\n",
                encoding="utf-8",
            )
            gh.chmod(0o755)
            env = {**env, "PATH": f"{bin_dir}{os.pathsep}{env.get('PATH', '')}", "GH_LOG": str(log)}
            stop = subprocess.run(
                [sys.executable, str(HOOK)],
                input=json.dumps(
                    {
                        "hook_event_name": "Stop",
                        "session_id": "retro-end",
                        "cwd": str(project),
                        "last_assistant_message": "still working",
                    }
                ),
                capture_output=True,
                text=True,
                check=False,
                env=env,
            )
            self.assertEqual(2, stop.returncode, stop.stderr)
            self.assertIn("Terminal reflection required", stop.stdout)
            self.assertEqual("block", json.loads(stop.stdout).get("decision"))
            busy = subprocess.run(
                [sys.executable, str(HOOK)],
                input=json.dumps(
                    {
                        "hook_event_name": "Stop",
                        "session_id": "retro-end",
                        "cwd": str(project),
                        "last_assistant_message": "still working",
                        "backgroundTasks": [
                            {"id": "mon", "type": "monitor", "status": "running"}
                        ],
                    }
                ),
                capture_output=True,
                text=True,
                check=False,
                env=env,
            )
            self.assertNotIn("Terminal reflection required", busy.stdout)
            self.assertNotEqual("block", json.loads(busy.stdout or "{}").get("decision"))
            scratch.open_agent(project, "retro-end", "delegate")
            delegated = subprocess.run(
                [sys.executable, str(HOOK)],
                input=json.dumps(
                    {
                        "hook_event_name": "Stop",
                        "session_id": "retro-end",
                        "cwd": str(project),
                        "last_assistant_message": "still working",
                    }
                ),
                capture_output=True,
                text=True,
                check=False,
                env=env,
            )
            scratch.close_agent(project, "retro-end", "delegate")
            self.assertNotIn("Terminal reflection required", delegated.stdout)
            self.assertNotEqual("block", json.loads(delegated.stdout or "{}").get("decision"))
            closing = subprocess.run(
                [sys.executable, str(HOOK)],
                input=json.dumps(
                    {
                        "hook_event_name": "Stop",
                        "session_id": "retro-end",
                        "cwd": str(project),
                        "reason": "channel_closed",
                        "last_assistant_message": "still working",
                    }
                ),
                capture_output=True,
                text=True,
                check=False,
                env=env,
            )
            self.assertNotIn("Terminal reflection required", closing.stdout)
            self.assertNotEqual("block", json.loads(closing.stdout or "{}").get("decision"))
            first = subprocess.run(
                [sys.executable, str(HOOK)],
                input=json.dumps(
                    {"hook_event_name": "SessionEnd", "session_id": "retro-end", "cwd": str(project)}
                ),
                capture_output=True,
                text=True,
                check=False,
                env=env,
            )
            second = subprocess.run(
                [sys.executable, str(HOOK)],
                input=json.dumps(
                    {"hook_event_name": "SessionEnd", "session_id": "retro-end", "cwd": str(project)}
                ),
                capture_output=True,
                text=True,
                check=False,
                env=env,
            )
            self.assertEqual(0, first.returncode, first.stderr)
            self.assertIn("share one report", first.stdout)
            self.assertIn("https://github.com/ShaftHQ/chaosengine-harness/issues/74", first.stdout)
            self.assertNotIn("Session retrospective", second.stdout)
            self.assertEqual(1, log.read_text(encoding="utf-8").count("create"))
            short = subprocess.run(
                [sys.executable, str(HOOK)],
                input=json.dumps(
                    {
                        "hook_event_name": "SessionEnd",
                        "session_id": "retro-short",
                        "cwd": str(project / "short"),
                    }
                ),
                capture_output=True,
                text=True,
                check=False,
                env=env,
            )
            self.assertNotIn("Session retrospective", short.stdout)


if __name__ == "__main__":
    unittest.main()
