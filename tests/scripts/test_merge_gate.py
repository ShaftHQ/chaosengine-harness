"""gh pr merge waits for successful checks and resolved review threads."""

from __future__ import annotations

import importlib.util
import io
import os
import sys
import tempfile
import unittest
import unittest.mock
from contextlib import redirect_stdout
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def load():
    spec = importlib.util.spec_from_file_location("ce_merge_gate", ROOT / "hooks" / "guard.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def ready(**overrides):
    snapshot = {
        "checks": [
            {"name": "installer", "status": "COMPLETED", "conclusion": "SUCCESS"},
            {
                "name": "Offline structure and syntax checks",
                "status": "COMPLETED",
                "conclusion": "SUCCESS",
            },
        ],
        "unresolved": 0,
        "hasNextPage": False,
        "mergeStateStatus": "CLEAN",
    }
    snapshot.update(overrides)
    return snapshot


class MergeGateTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.guard = load()

    def reason(self, command, snapshot):
        return self.guard.merge_before_ready_reason(command, probe=lambda _target: snapshot)

    def test_in_progress_check_has_not_finished(self):
        snapshot = ready(checks=[{"name": "installer", "status": "IN_PROGRESS", "conclusion": ""}])
        self.assertIn("installer has not finished", self.reason("gh pr merge 76 --merge", snapshot))

    def test_failed_check_is_not_successful(self):
        snapshot = ready(checks=[{"name": "installer", "status": "COMPLETED", "conclusion": "FAILURE"}])
        self.assertIn("installer is not successful", self.reason("gh pr merge 76 --merge", snapshot))

    def test_empty_rollup_has_not_finished(self):
        self.assertIn(
            "CI checks have not finished",
            self.reason("gh pr merge 76 --merge", ready(checks=[])),
        )

    def test_success_and_no_open_threads_allows_merge(self):
        self.assertEqual("", self.reason("gh pr merge 76 --merge", ready()))

    def test_unresolved_thread_blocks(self):
        self.assertIn(
            "review comments are still open",
            self.reason("gh pr merge 76 --merge", ready(unresolved=1)),
        )

    def test_auto_does_not_bypass_a_pending_check(self):
        snapshot = ready(checks=[{"name": "installer", "status": "IN_PROGRESS", "conclusion": ""}])
        self.assertIn("has not finished", self.reason("gh pr merge 76 --merge --auto", snapshot))
        self.assertIn("has not finished", self.reason("gh pr merge --auto --merge 76", snapshot))

    def test_auto_is_allowed_once_the_head_is_ready(self):
        self.assertEqual("", self.reason("gh pr merge 76 --auto --merge", ready()))

    def test_non_merge_command_does_not_call_the_probe(self):
        def boom(_target):
            raise AssertionError("probe")

        self.assertEqual("", self.guard.merge_before_ready_reason("gh pr view 76", probe=boom))
        self.assertEqual("", self.guard.merge_before_ready_reason("echo gh pr merge 76", probe=boom))

    def test_draft_dirty_and_blocked_deny(self):
        for state in ("DRAFT", "DIRTY", "BLOCKED"):
            with self.subTest(state=state):
                self.assertIn(state, self.reason("gh pr merge 76 --merge", ready(mergeStateStatus=state)))

    def test_behind_alone_does_not_deny(self):
        self.assertEqual("", self.reason("gh pr merge 76 --merge", ready(mergeStateStatus="BEHIND")))

    def test_skipped_and_neutral_are_not_success(self):
        for conclusion in ("SKIPPED", "NEUTRAL"):
            with self.subTest(conclusion=conclusion):
                snapshot = ready(checks=[{"name": "installer", "status": "COMPLETED", "conclusion": conclusion}])
                self.assertIn("is not successful", self.reason("gh pr merge 76 --merge", snapshot))

    def test_status_context_success_allows_and_pending_denies(self):
        self.assertEqual(
            "",
            self.reason("gh pr merge 76 --merge", ready(checks=[{"context": "ci", "state": "SUCCESS"}])),
        )
        self.assertIn(
            "has not finished",
            self.reason("gh pr merge 76 --merge", ready(checks=[{"context": "ci", "state": "PENDING"}])),
        )

    def test_probe_exception_fails_closed(self):
        def boom(_target):
            raise RuntimeError("nope")

        reason = self.guard.merge_before_ready_reason("gh pr merge 76 --merge", probe=boom)
        self.assertIn("could not be read", reason)

    def test_missing_gh_fails_closed(self):
        self.assertIn("gh is missing", self.reason("gh pr merge 76 --merge", {"error": "gh is missing."}))

    def test_unread_thread_page_fails_closed(self):
        self.assertIn("did not fit", self.reason("gh pr merge 76 --merge", ready(hasNextPage=True)))

    def test_bool_unresolved_fails_closed(self):
        self.assertIn("could not be read", self.reason("gh pr merge 76 --merge", ready(unresolved=True)))

    def test_compound_merge_is_still_gated(self):
        self.assertIn(
            "CI checks have not finished",
            self.reason("true && gh pr merge 76 --merge", ready(checks=[])),
        )

    def test_piped_merge_cannot_skip_the_gate(self):
        reason = self.guard.merge_before_ready_reason(
            "gh pr checks 76 | gh pr merge 76 --merge",
            probe=lambda _target: ready(),
        )
        self.assertIn("could not be read", reason)

    def test_repo_flag_keeps_the_pull_request_number(self):
        seen = []

        def probe(target):
            seen.append(target)
            return ready()

        self.assertEqual(
            "",
            self.guard.merge_before_ready_reason(
                "gh pr merge --repo ShaftHQ/chaosengine-harness 76 --merge",
                probe=probe,
            ),
        )
        self.assertEqual(["76"], seen)

    def test_attached_repo_flag_keeps_the_pull_request_number(self):
        seen = []

        def probe(target):
            seen.append(target)
            return ready()

        self.assertEqual(
            "",
            self.guard.merge_before_ready_reason(
                "gh pr merge -R=ShaftHQ/chaosengine-harness 12 --merge",
                probe=probe,
            ),
        )
        self.assertEqual(["12"], seen)

    def test_merge_without_a_number_still_reads_the_current_pull_request(self):
        seen = []

        def probe(target):
            seen.append(target)
            return ready()

        self.assertEqual("", self.guard.merge_before_ready_reason("gh pr merge --merge", probe=probe))
        self.assertEqual([""], seen)

    def test_value_flag_without_a_value_fails_closed(self):
        reason = self.guard.merge_before_ready_reason("gh pr merge --repo", probe=lambda _target: ready())
        self.assertIn("could not be read", reason)

    def test_unparsed_merge_fails_closed(self):
        reason = self.guard.merge_before_ready_reason(
            'gh pr merge 76 --body "unterminated',
            probe=lambda _target: ready(),
        )
        self.assertIn("could not be read", reason)

    def test_removing_the_success_check_would_fail_this_test(self):
        """A head whose only check is still running must not merge."""
        snapshot = ready(checks=[{"name": "installer", "status": "IN_PROGRESS", "conclusion": "SUCCESS"}])
        self.assertIn("has not finished", self.reason("gh pr merge 86 --merge --auto", snapshot))

    def test_guard_merge_instruction_uses_squash_and_the_required_set(self):
        text = (ROOT / "hooks" / "guard.py").read_text(encoding="utf-8")
        self.assertNotIn("every CI check", text)
        self.assertNotIn("gh pr merge --merge only", text)
        self.assertNotIn("Never squash", text)
        self.assertIn("gh pr merge --squash", text)
        self.assertIn("outside the required set does not block", text)
        self.assertIn("when no check is marked required", text)
        self.assertIn("An unmarked skip blocks", text)
        self.assertIn("An empty check list is not success", text)

    def test_standard_text_keeps_sequential_reviews_and_forbids_early_merge(self):
        cycle = (ROOT / "references" / "delivery-cycle.md").read_text(encoding="utf-8")
        skill = (ROOT / "skills" / "chaos-engine" / "SKILL.md").read_text(encoding="utf-8")
        planning = (ROOT / "references" / "work-github-planning.md").read_text(encoding="utf-8")
        self.assertIn("Do not run the two reviews in parallel", cycle)
        self.assertIn("Adversarial review 1", cycle)
        self.assertIn("adversarial review 2", cycle)
        self.assertIn("whichever of review 1 and CI returns first", cycle)
        self.assertNotIn("Reviews start only on a green head", cycle)
        self.assertNotIn("Review only after required checks are green", cycle)
        self.assertIn("does not start a third", cycle.casefold())
        self.assertIn("A pending check is not success", cycle)
        self.assertIn("review 1 with the self-accept push", skill)
        self.assertIn("Do not start both reviewers in one step", skill)
        self.assertIn("A pending check is not success", skill)
        self.assertIn("gh pr merge --squash --auto", planning)
        self.assertIn("Do not run `gh pr merge --squash --auto`", planning)
        self.assertNotIn("gh pr merge --merge", planning)
        self.assertNotIn("No squash", planning)
        self.assertNotIn("Merge with `gh pr merge --merge --auto` only", planning)

    def test_pre_tool_use_refuses_a_pending_merge(self):
        seen = []

        def probe(target):
            seen.append(target)
            return ready(checks=[{"name": "installer", "status": "IN_PROGRESS", "conclusion": ""}])

        self.guard.live_merge_probe = probe
        _receipt, _mutation, reason = self.guard._command_guard_state(
            {
                "hook_event_name": "PreToolUse",
                "cwd": str(ROOT),
                "session_id": "merge-gate-unit",
                "tool_name": "Bash",
            },
            "PreToolUse",
            ("gh pr merge 76 --auto --merge",),
            "Bash",
            {"command": "gh pr merge 76 --auto --merge"},
            "",
            "",
            "merge-gate-unit",
        )
        self.assertEqual(["76"], seen)
        self.assertIn("installer has not finished", reason)

    def test_quoted_body_separators_still_gate_the_merge(self):
        pending = ready(checks=[{"name": "installer", "status": "IN_PROGRESS", "conclusion": ""}])
        commands = (
            'gh pr merge 76 --merge --body "a && b"',
            "gh pr merge 76 --merge --body \"line1\nline2\"",
            "gh pr merge 76 --merge --body 'a; b'",
        )
        for command in commands:
            seen = []

            def probe(target, seen=seen):
                seen.append(target)
                return pending

            reason = self.guard.merge_before_ready_reason(command, probe=probe)
            with self.subTest(command=command):
                self.assertEqual(["76"], seen)
                self.assertIn("installer has not finished", reason)

    def test_recorded_403_blocks_before_the_merge_probe(self):
        calls = []

        def probe(target):
            calls.append(target)
            return ready()

        self.guard.live_merge_probe = probe
        with tempfile.TemporaryDirectory() as temporary:
            environment = {**os.environ, "TMPDIR": temporary, "TEMP": temporary}
            session = "merge-gate-403"
            with unittest.mock.patch.dict(os.environ, environment):
                posted = self.guard._run_event(
                    {
                        "hook_event_name": "PostToolUse",
                        "cwd": temporary,
                        "tool_name": "Bash",
                        "tool_input": {"command": "gh pr merge 99 --auto --merge"},
                        "tool_response": {
                            "status": "error",
                            "exit_code": 1,
                            "stderr": (
                                "GraphQL: Resource not accessible by integration "
                                "(EnablePullRequestAutoMerge)\nHTTP 403\n"
                            ),
                        },
                        "session_id": session,
                    },
                    "grok",
                )
                self.assertEqual(0, posted)
                captured = io.StringIO()
                with redirect_stdout(captured):
                    blocked = self.guard._run_event(
                        {
                            "hook_event_name": "PreToolUse",
                            "cwd": temporary,
                            "tool_name": "Bash",
                            "tool_input": {"command": "gh pr merge 99 --auto --merge"},
                            "session_id": session,
                        },
                        "grok",
                    )
            text = captured.getvalue().casefold()
            self.assertNotEqual(0, blocked)
            self.assertIn("403", text)
            self.assertIn("permission", text)
            self.assertEqual([], calls)

    def test_newline_in_the_body_still_takes_the_permission_denial(self):
        multiline = 'gh pr merge 99 --merge --body "hello\nworld" --auto'
        auto_value = 'gh pr merge 99 --merge --body "hello\nworld" --auto=true'
        self.assertIsNotNone(self.guard._AUTO_MERGE_ARM.search("gh pr merge 99 --auto --merge"))
        self.assertIsNone(self.guard._AUTO_MERGE_ARM.search(multiline))
        self.assertTrue(self.guard._command_is_github_write_permission_mutation(multiline))
        self.assertTrue(self.guard._command_is_github_write_permission_mutation(auto_value))
        calls = []

        def probe(target):
            calls.append(target)
            return ready()

        self.guard.live_merge_probe = probe
        with tempfile.TemporaryDirectory() as temporary:
            environment = {**os.environ, "TMPDIR": temporary, "TEMP": temporary}
            session = "merge-gate-403-newline-body"
            with unittest.mock.patch.dict(os.environ, environment):
                posted = self.guard._run_event(
                    {
                        "hook_event_name": "PostToolUse",
                        "cwd": temporary,
                        "tool_name": "Bash",
                        "tool_input": {"command": "gh pr merge 99 --auto --merge"},
                        "tool_response": {
                            "status": "error",
                            "exit_code": 1,
                            "stderr": (
                                "GraphQL: Resource not accessible by integration "
                                "(EnablePullRequestAutoMerge)\nHTTP 403\n"
                            ),
                        },
                        "session_id": session,
                    },
                    "grok",
                )
                self.assertEqual(0, posted)
                captured = io.StringIO()
                with redirect_stdout(captured):
                    blocked = self.guard._run_event(
                        {
                            "hook_event_name": "PreToolUse",
                            "cwd": temporary,
                            "tool_name": "Bash",
                            "tool_input": {"command": multiline},
                            "session_id": session,
                        },
                        "grok",
                    )
            text = captured.getvalue().casefold()
            self.assertNotEqual(0, blocked)
            self.assertIn("403", text)
            self.assertEqual([], calls)

    def test_backslash_continuation_still_hits_the_probe(self):
        pending = ready(checks=[{"name": "installer", "status": "IN_PROGRESS", "conclusion": ""}])
        commands = (
            ("gh pr merge 99 --merge \\\n--auto", "99"),
            ('gh pr merge 76 --merge \\\n--body "long"', "76"),
            ("gh pr merge \\\n76 --merge", "76"),
        )
        for command, number in commands:
            seen = []

            def probe(target, seen=seen):
                seen.append(target)
                return pending

            reason = self.guard.merge_before_ready_reason(command, probe=probe)
            with self.subTest(command=command):
                self.assertEqual([number], seen)
                self.assertIn("installer has not finished", reason)
        self.assertEqual(
            ["gh pr merge 99 --merge --auto"],
            self.guard._merge_command_statements("gh pr merge 99 --merge \\\n--auto"),
        )
        self.assertEqual(
            ["echo \\\\", "gh pr merge 76 --merge"],
            self.guard._merge_command_statements("echo \\\\\ngh pr merge 76 --merge"),
        )
        self.assertEqual(
            ['gh pr merge 76 --merge --body "a\nb"'],
            self.guard._merge_command_statements('gh pr merge 76 --merge --body "a\nb"'),
        )


if __name__ == "__main__":
    unittest.main()
