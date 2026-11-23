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


def _required_green():
    return {
        "name": "Offline structure and syntax checks",
        "status": "COMPLETED",
        "conclusion": "SUCCESS",
        "isRequired": True,
    }


class InstallerContractMergeGateTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.guard = load()

    def test_installer_contract_paths_are_the_installer_surface(self):
        self.assertEqual(
            (
                "install.py",
                "bootstrap.py",
                "runtime/dependencies.py",
                "install.sh",
                "install.ps1",
            ),
            self.guard._INSTALLER_CONTRACT_PATHS,
        )

    def test_failed_installer_cell_blocks_an_installer_diff(self):
        cell = {
            "name": "ubuntu-latest upgrade empty",
            "status": "COMPLETED",
            "conclusion": "FAILURE",
            "isRequired": False,
        }
        for files in (
            ["runtime/dependencies.py"],
            ["./runtime/dependencies.py"],
            ["runtime\\dependencies.py"],
        ):
            with self.subTest(files=files):
                snapshot = ready(
                    checks=[_required_green(), cell],
                    files=files,
                    mergeStateStatus="UNSTABLE",
                )
                reason = self.guard.merge_readiness_reason(snapshot)
                self.assertIn("installer-contract", reason)
                self.assertIn("ubuntu-latest upgrade empty", reason)
                self.assertNotIn("UNSTABLE", reason)

    def test_workflow_name_blocks_an_installer_diff(self):
        snapshot = ready(
            checks=[
                _required_green(),
                {
                    "name": "build",
                    "workflowName": "installer-contract",
                    "status": "COMPLETED",
                    "conclusion": "FAILURE",
                    "isRequired": False,
                },
            ],
            files=["install.py"],
        )
        reason = self.guard.merge_readiness_reason(snapshot)
        self.assertIn("installer-contract", reason)
        self.assertIn("build", reason)

    def test_pending_and_cancelled_installer_checks_block_installer_diffs(self):
        pending = {
            "name": "macos-latest upgrade empty",
            "status": "IN_PROGRESS",
            "conclusion": "",
            "isRequired": False,
        }
        cancelled = {
            "name": "windows-latest fresh empty",
            "workflowName": "Installer-Contract",
            "status": "COMPLETED",
            "conclusion": "CANCELLED",
            "isRequired": False,
        }
        cases = (
            (["install.py"], pending),
            (["bootstrap.py"], pending),
            (["install.sh"], cancelled),
            (["install.ps1"], cancelled),
            ([{"path": "./install.py"}], pending),
        )
        for files, check in cases:
            with self.subTest(files=files, check=check["conclusion"] or check["status"]):
                snapshot = ready(checks=[_required_green(), check], files=files)
                reason = self.guard.merge_readiness_reason(snapshot)
                self.assertIn("installer-contract", reason)
                self.assertIn(check["name"], reason)

    def test_same_failed_cell_allows_a_docs_only_diff(self):
        snapshot = ready(
            checks=[
                _required_green(),
                {
                    "name": "ubuntu-latest upgrade empty",
                    "workflowName": "installer-contract",
                    "status": "COMPLETED",
                    "conclusion": "FAILURE",
                    "isRequired": False,
                },
            ],
            files=["README.md"],
            mergeStateStatus="UNSTABLE",
        )
        self.assertEqual("", self.guard.merge_readiness_reason(snapshot))

    def test_skipped_installer_cell_on_a_docs_diff_stays_allowed(self):
        snapshot = ready(
            checks=[
                _required_green(),
                {
                    "name": "ubuntu-latest fresh empty",
                    "status": "COMPLETED",
                    "conclusion": "SKIPPED",
                    "isRequired": False,
                },
            ],
            files=["docs/layout.md"],
        )
        self.assertEqual("", self.guard.merge_readiness_reason(snapshot))

    def test_non_installer_failure_still_does_not_block_an_installer_diff(self):
        snapshot = ready(
            checks=[
                _required_green(),
                {
                    "name": "codecov",
                    "status": "COMPLETED",
                    "conclusion": "FAILURE",
                    "isRequired": False,
                },
            ],
            files=["install.py", "runtime/dependencies.py"],
        )
        self.assertEqual("", self.guard.merge_readiness_reason(snapshot))

    def test_empty_check_list_still_blocks(self):
        self.assertIn(
            "CI checks have not finished",
            self.guard.merge_readiness_reason(ready(checks=[], files=["install.py"])),
        )
        self.assertIn(
            "CI checks have not finished",
            self.guard.merge_readiness_reason(ready(checks=[])),
        )

    def test_rollup_preserves_workflow_name_and_probe_reads_files(self):
        checks = self.guard.checks_from_rollup_contexts([
            {
                "__typename": "CheckRun",
                "name": "ubuntu-latest upgrade empty",
                "status": "COMPLETED",
                "conclusion": "FAILURE",
                "isRequired": False,
                "checkSuite": {"workflowRun": {"workflow": {"name": "installer-contract"}}},
            },
            {
                "__typename": "CheckRun",
                "name": "build",
                "status": "COMPLETED",
                "conclusion": "SUCCESS",
                "isRequired": True,
                "workflowName": "offline",
            },
            {"__typename": "StatusContext", "context": "ci", "state": "SUCCESS", "isRequired": True},
        ])
        self.assertEqual("installer-contract", checks[0]["workflowName"])
        self.assertEqual("offline", checks[1]["workflowName"])
        self.assertNotIn("workflowName", checks[2])

        seen = []

        def fake(args):
            seen.append(list(args))
            if args[:2] == ["pr", "view"]:
                self.assertIn("files", args[args.index("--json") + 1])
                return {
                    "id": "PR_abc",
                    "url": "https://github.com/acme/widgets/pull/9",
                    "mergeStateStatus": "UNSTABLE",
                    "statusCheckRollup": [],
                    "files": [{"path": "runtime/dependencies.py", "additions": 1, "deletions": 0}],
                }, ""
            query = args[-1]
            if "reviewThreads" in query:
                self.assertIn("files(first: 100)", query)
                return {
                    "data": {
                        "repository": {
                            "pullRequest": {
                                "files": {"nodes": [{"path": "ignored-by-view.py"}]},
                                "reviewThreads": {
                                    "pageInfo": {"hasNextPage": False},
                                    "nodes": [],
                                },
                            }
                        }
                    }
                }, ""
            self.assertIn("workflow { name }", query)
            self.assertIn("isRequired", query)
            return {
                "data": {
                    "repository": {
                        "pullRequest": {
                            "commits": {
                                "nodes": [{
                                    "commit": {
                                        "statusCheckRollup": {
                                            "contexts": {
                                                "pageInfo": {"hasNextPage": False},
                                                "nodes": [{
                                                    "__typename": "CheckRun",
                                                    "name": "ubuntu-latest upgrade empty",
                                                    "status": "COMPLETED",
                                                    "conclusion": "FAILURE",
                                                    "isRequired": False,
                                                    "checkSuite": {
                                                        "workflowRun": {
                                                            "workflow": {"name": "installer-contract"}
                                                        }
                                                    },
                                                }],
                                            }
                                        }
                                    }
                                }]
                            }
                        }
                    }
                }
            }, ""

        self.guard._gh_json = fake
        snapshot = self.guard.live_merge_probe("9")
        self.assertIn("runtime/dependencies.py", snapshot["files"])
        self.assertEqual("installer-contract", snapshot["checks"][0]["workflowName"])
        reason = self.guard.merge_readiness_reason(snapshot)
        self.assertIn("installer-contract", reason)
        self.assertIn("ubuntu-latest upgrade empty", reason)
        self.assertTrue(seen)

    def test_skipped_installer_cell_on_installer_diff_stays_allowed(self):
        snapshot = ready(
            checks=[
                _required_green(),
                {
                    "name": "ubuntu-latest fresh empty",
                    "workflowName": "installer-contract",
                    "status": "COMPLETED",
                    "conclusion": "SKIPPED",
                    "isRequired": False,
                },
            ],
            files=["install.py"],
        )
        self.assertEqual("", self.guard.merge_readiness_reason(snapshot))

    def test_incomplete_file_list_fails_closed_on_red_installer_contract(self):
        failed = {
            "name": "ubuntu-latest upgrade empty",
            "workflowName": "installer-contract",
            "status": "COMPLETED",
            "conclusion": "FAILURE",
            "isRequired": False,
        }
        snapshot = ready(
            checks=[_required_green(), failed],
            files=["README.md"],
            filesComplete=False,
        )
        reason = self.guard.merge_readiness_reason(snapshot)
        self.assertIn("installer-contract", reason)
        self.assertIn("ubuntu-latest upgrade empty", reason)

    def test_live_probe_paginates_pr_files_beyond_100_and_blocks(self):
        def fake(args):
            if args[:2] == ["pr", "view"]:
                return {
                    "id": "PR_big",
                    "url": "https://github.com/acme/widgets/pull/201",
                    "mergeStateStatus": "UNSTABLE",
                    "statusCheckRollup": [],
                    "files": [{"path": f"docs/file-{i}.md"} for i in range(100)],
                }, ""
            query = args[-1]
            if "reviewThreads" in query:
                return {
                    "data": {
                        "repository": {
                            "pullRequest": {
                                "files": {
                                    "pageInfo": {"hasNextPage": True, "endCursor": "CUR100"},
                                    "nodes": [{"path": f"docs/file-{i}.md"} for i in range(100)],
                                },
                                "reviewThreads": {
                                    "pageInfo": {"hasNextPage": False},
                                    "nodes": [],
                                },
                            }
                        }
                    }
                }, ""
            if 'after: "CUR100"' in query:
                return {
                    "data": {
                        "repository": {
                            "pullRequest": {
                                "files": {
                                    "pageInfo": {"hasNextPage": False, "endCursor": "CUR143"},
                                    "nodes": [{"path": "runtime/dependencies.py"}],
                                }
                            }
                        }
                    }
                }, ""
            return {
                "data": {
                    "repository": {
                        "pullRequest": {
                            "commits": {
                                "nodes": [{
                                    "commit": {
                                        "statusCheckRollup": {
                                            "contexts": {
                                                "pageInfo": {"hasNextPage": False},
                                                "nodes": [
                                                    {
                                                        "__typename": "CheckRun",
                                                        "name": "Offline structure and syntax checks",
                                                        "status": "COMPLETED",
                                                        "conclusion": "SUCCESS",
                                                        "isRequired": True,
                                                    },
                                                    {
                                                        "__typename": "CheckRun",
                                                        "name": "windows-latest fresh shaft-dev",
                                                        "status": "COMPLETED",
                                                        "conclusion": "FAILURE",
                                                        "isRequired": False,
                                                        "checkSuite": {
                                                            "workflowRun": {
                                                                "workflow": {"name": "installer-contract"}
                                                            }
                                                        },
                                                    },
                                                ],
                                            }
                                        }
                                    }
                                }]
                            }
                        }
                    }
                }
            }, ""

        self.guard._gh_json = fake
        snapshot = self.guard.live_merge_probe("201")
        self.assertTrue(snapshot["filesComplete"])
        self.assertIn("runtime/dependencies.py", snapshot["files"])
        reason = self.guard.merge_readiness_reason(snapshot)
        self.assertIn("installer-contract", reason)
        self.assertIn("windows-latest fresh shaft-dev", reason)

    def test_live_probe_pagination_error_marks_files_incomplete_and_fails_closed(self):
        def fake(args):
            if args[:2] == ["pr", "view"]:
                return {
                    "id": "PR_trunc",
                    "url": "https://github.com/acme/widgets/pull/202",
                    "mergeStateStatus": "UNSTABLE",
                    "statusCheckRollup": [],
                    "files": [{"path": f"docs/file-{i}.md"} for i in range(100)],
                }, ""
            query = args[-1]
            if "reviewThreads" in query:
                return {
                    "data": {
                        "repository": {
                            "pullRequest": {
                                "files": {
                                    "pageInfo": {"hasNextPage": True, "endCursor": "CUR100"},
                                    "nodes": [{"path": f"docs/file-{i}.md"} for i in range(100)],
                                },
                                "reviewThreads": {
                                    "pageInfo": {"hasNextPage": False},
                                    "nodes": [],
                                },
                            }
                        }
                    }
                }, ""
            if 'after: "CUR100"' in query:
                return None, "gh timed out."
            return {
                "data": {
                    "repository": {
                        "pullRequest": {
                            "commits": {
                                "nodes": [{
                                    "commit": {
                                        "statusCheckRollup": {
                                            "contexts": {
                                                "pageInfo": {"hasNextPage": False},
                                                "nodes": [
                                                    {
                                                        "__typename": "CheckRun",
                                                        "name": "Offline structure and syntax checks",
                                                        "status": "COMPLETED",
                                                        "conclusion": "SUCCESS",
                                                        "isRequired": True,
                                                    },
                                                    {
                                                        "__typename": "CheckRun",
                                                        "name": "ubuntu-latest upgrade empty",
                                                        "status": "COMPLETED",
                                                        "conclusion": "FAILURE",
                                                        "isRequired": False,
                                                    },
                                                ],
                                            }
                                        }
                                    }
                                }]
                            }
                        }
                    }
                }
            }, ""

        self.guard._gh_json = fake
        snapshot = self.guard.live_merge_probe("202")
        self.assertFalse(snapshot["filesComplete"])
        reason = self.guard.merge_readiness_reason(snapshot)
        self.assertIn("installer-contract", reason)
        self.assertIn("ubuntu-latest upgrade empty", reason)

    def test_live_probe_page2_missing_or_null_has_next_page_fails_closed(self):
        for page2_info in ({}, {"hasNextPage": None}):
            with self.subTest(page2_info=page2_info):
                def fake(args, page2_info=page2_info):
                    if args[:2] == ["pr", "view"]:
                        return {
                            "id": "PR_p2",
                            "url": "https://github.com/acme/widgets/pull/203",
                            "mergeStateStatus": "UNSTABLE",
                            "statusCheckRollup": [],
                            "files": [{"path": f"docs/file-{i}.md"} for i in range(100)],
                        }, ""
                    query = args[-1]
                    if "reviewThreads" in query:
                        return {
                            "data": {
                                "repository": {
                                    "pullRequest": {
                                        "files": {
                                            "pageInfo": {"hasNextPage": True, "endCursor": "CUR100"},
                                            "nodes": [{"path": f"docs/file-{i}.md"} for i in range(100)],
                                        },
                                        "reviewThreads": {
                                            "pageInfo": {"hasNextPage": False},
                                            "nodes": [],
                                        },
                                    }
                                }
                            }
                        }, ""
                    if 'after: "CUR100"' in query:
                        return {
                            "data": {
                                "repository": {
                                    "pullRequest": {
                                        "files": {
                                            "pageInfo": page2_info,
                                            "nodes": [{"path": f"docs/page2-{i}.md"} for i in range(100)],
                                        }
                                    }
                                }
                            }
                        }, ""
                    return {
                        "data": {
                            "repository": {
                                "pullRequest": {
                                    "commits": {
                                        "nodes": [{
                                            "commit": {
                                                "statusCheckRollup": {
                                                    "contexts": {
                                                        "pageInfo": {"hasNextPage": False},
                                                        "nodes": [
                                                            {
                                                                "__typename": "CheckRun",
                                                                "name": "Offline structure and syntax checks",
                                                                "status": "COMPLETED",
                                                                "conclusion": "SUCCESS",
                                                                "isRequired": True,
                                                            },
                                                            {
                                                                "__typename": "CheckRun",
                                                                "name": "ubuntu-latest upgrade empty",
                                                                "status": "COMPLETED",
                                                                "conclusion": "FAILURE",
                                                                "isRequired": False,
                                                            },
                                                        ],
                                                    }
                                                }
                                            }
                                        }]
                                    }
                                }
                            }
                        }
                    }, ""

                self.guard._gh_json = fake
                snapshot = self.guard.live_merge_probe("203")
                self.assertFalse(snapshot["filesComplete"])
                reason = self.guard.merge_readiness_reason(snapshot)
                self.assertIn("installer-contract", reason)
                self.assertIn("ubuntu-latest upgrade empty", reason)

    def test_live_probe_empty_graphql_with_100_view_files_fails_closed(self):
        def fake(args):
            if args[:2] == ["pr", "view"]:
                return {
                    "id": "PR_v100",
                    "url": "https://github.com/acme/widgets/pull/204",
                    "mergeStateStatus": "UNSTABLE",
                    "statusCheckRollup": [],
                    "files": [{"path": f"docs/file-{i}.md"} for i in range(100)],
                }, ""
            query = args[-1]
            if "reviewThreads" in query:
                return {
                    "data": {
                        "repository": {
                            "pullRequest": {
                                "files": {
                                    "pageInfo": {"hasNextPage": False},
                                    "nodes": [],
                                },
                                "reviewThreads": {
                                    "pageInfo": {"hasNextPage": False},
                                    "nodes": [],
                                },
                            }
                        }
                    }
                }, ""
            return {
                "data": {
                    "repository": {
                        "pullRequest": {
                            "commits": {
                                "nodes": [{
                                    "commit": {
                                        "statusCheckRollup": {
                                            "contexts": {
                                                "pageInfo": {"hasNextPage": False},
                                                "nodes": [
                                                    {
                                                        "__typename": "CheckRun",
                                                        "name": "Offline structure and syntax checks",
                                                        "status": "COMPLETED",
                                                        "conclusion": "SUCCESS",
                                                        "isRequired": True,
                                                    },
                                                    {
                                                        "__typename": "CheckRun",
                                                        "name": "ubuntu-latest upgrade empty",
                                                        "status": "COMPLETED",
                                                        "conclusion": "FAILURE",
                                                        "isRequired": False,
                                                    },
                                                ],
                                            }
                                        }
                                    }
                                }]
                            }
                        }
                    }
                }
            }, ""

        self.guard._gh_json = fake
        snapshot = self.guard.live_merge_probe("204")
        self.assertFalse(snapshot["filesComplete"])
        reason = self.guard.merge_readiness_reason(snapshot)
        self.assertIn("installer-contract", reason)
        self.assertIn("ubuntu-latest upgrade empty", reason)


if __name__ == "__main__":
    unittest.main()
