"""Required-check merge gate, consumer Stop receipt, and zsh-safe hook commands."""

from __future__ import annotations

import importlib.util
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

import runtime.hosts as hosts  # noqa: E402


def load_guard():
    spec = importlib.util.spec_from_file_location(
        "ce_required_merge_gate", ROOT / "hooks" / "guard.py"
    )
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def ready(**overrides):
    snapshot = {
        "checks": [
            {"name": "installer", "status": "COMPLETED", "conclusion": "SUCCESS"},
        ],
        "unresolved": 0,
        "hasNextPage": False,
        "mergeStateStatus": "CLEAN",
    }
    snapshot.update(overrides)
    return snapshot


def _git(cwd: Path, *args: str) -> None:
    subprocess.run(
        ["git", "-c", "user.name=Hook Test", "-c", "user.email=hook-test@example.com", *args],
        cwd=cwd,
        check=True,
        capture_output=True,
        text=True,
    )


def _run(command: str, cwd: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["bash", "-c", command],
        cwd=cwd,
        capture_output=True,
        text=True,
        check=False,
    )


class RequiredCheckGateTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.guard = load_guard()

    def reason(self, snapshot):
        return self.guard.merge_before_ready_reason("gh pr merge 76 --merge", probe=lambda _target: snapshot)

    def test_unmarked_skip_still_blocks(self):
        snapshot = ready(checks=[{"name": "installer", "status": "COMPLETED", "conclusion": "SKIPPED"}])
        self.assertIn("is not successful", self.reason(snapshot))

    def test_non_required_skip_does_not_block_when_no_check_is_required(self):
        snapshot = ready(checks=[
            {"name": "installer", "status": "COMPLETED", "conclusion": "SUCCESS", "isRequired": False},
            {"name": "macos", "status": "COMPLETED", "conclusion": "SKIPPED", "isRequired": False},
            {"name": "codecov", "status": "COMPLETED", "conclusion": "NEUTRAL", "isRequired": False},
        ])
        self.assertEqual("", self.reason(snapshot))

    def test_skipped_required_check_is_not_success(self):
        snapshot = ready(checks=[
            {"name": "gate", "status": "COMPLETED", "conclusion": "SUCCESS", "isRequired": True},
            {"name": "macos", "status": "COMPLETED", "conclusion": "SKIPPED", "isRequired": True},
        ])
        self.assertIn("macos is not successful", self.reason(snapshot))

    def test_non_required_failure_still_blocks_when_nothing_is_required(self):
        snapshot = ready(checks=[
            {"name": "installer", "status": "COMPLETED", "conclusion": "FAILURE", "isRequired": False},
        ])
        self.assertIn("installer is not successful", self.reason(snapshot))

    def test_non_required_failure_does_not_block_when_a_required_check_passed(self):
        snapshot = ready(checks=[
            {"name": "gate", "status": "COMPLETED", "conclusion": "SUCCESS", "isRequired": True},
            {"name": "codecov", "status": "COMPLETED", "conclusion": "FAILURE", "isRequired": False},
        ])
        self.assertEqual("", self.reason(snapshot))

    def test_contexts_keep_a_boolean_required_flag(self):
        checks = self.guard.checks_from_rollup_contexts([
            {
                "__typename": "CheckRun",
                "name": "macos",
                "status": "COMPLETED",
                "conclusion": "SKIPPED",
                "isRequired": False,
            },
            {"__typename": "StatusContext", "context": "ci", "state": "SUCCESS", "isRequired": True},
            {"name": "plain", "status": "COMPLETED", "conclusion": "SUCCESS"},
        ])
        self.assertEqual(False, checks[0]["isRequired"])
        self.assertEqual("ci", checks[1]["context"])
        self.assertTrue(checks[1]["isRequired"])
        self.assertNotIn("isRequired", checks[2])

    def test_probe_uses_graphql_required_marks(self):
        def fake(args):
            if args[:2] == ["pr", "view"]:
                return {
                    "id": "PR_abc",
                    "url": "https://github.com/acme/widgets/pull/9",
                    "mergeStateStatus": "CLEAN",
                    "statusCheckRollup": [
                        {"name": "macos", "status": "COMPLETED", "conclusion": "SKIPPED"},
                    ],
                }, ""
            query = args[-1]
            if "reviewThreads" in query:
                return {
                    "data": {
                        "repository": {
                            "pullRequest": {
                                "reviewThreads": {
                                    "pageInfo": {"hasNextPage": False},
                                    "nodes": [],
                                }
                            }
                        }
                    }
                }, ""
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
                                                "nodes": [
                                                    {
                                                        "__typename": "CheckRun",
                                                        "name": "unit",
                                                        "status": "COMPLETED",
                                                        "conclusion": "SUCCESS",
                                                        "isRequired": False,
                                                    },
                                                    {
                                                        "__typename": "CheckRun",
                                                        "name": "macos",
                                                        "status": "COMPLETED",
                                                        "conclusion": "SKIPPED",
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
        snapshot = self.guard.live_merge_probe("9")
        self.assertEqual("", self.guard.merge_readiness_reason(snapshot))
        self.assertEqual(False, snapshot["checks"][1]["isRequired"])

    def test_probe_keeps_an_unmarked_skip_when_graphql_fails(self):
        def fake(args):
            if args[:2] == ["pr", "view"]:
                return {
                    "id": "PR_abc",
                    "url": "https://github.com/acme/widgets/pull/9",
                    "mergeStateStatus": "CLEAN",
                    "statusCheckRollup": [
                        {"name": "macos", "status": "COMPLETED", "conclusion": "SKIPPED"},
                    ],
                }, ""
            query = args[-1]
            if "reviewThreads" in query:
                return {
                    "data": {
                        "repository": {
                            "pullRequest": {
                                "reviewThreads": {
                                    "pageInfo": {"hasNextPage": False},
                                    "nodes": [],
                                }
                            }
                        }
                    }
                }, ""
            return None, "gh could not read the pull request."

        self.guard._gh_json = fake
        snapshot = self.guard.live_merge_probe("9")
        self.assertIn("is not successful", self.guard.merge_readiness_reason(snapshot))
        self.assertNotIn("isRequired", snapshot["checks"][0])

    def test_probe_errors_when_required_checks_do_not_fit_one_page(self):
        def fake(args):
            if args[:2] == ["pr", "view"]:
                return {
                    "id": "PR_abc",
                    "url": "https://github.com/acme/widgets/pull/9",
                    "mergeStateStatus": "CLEAN",
                    "statusCheckRollup": [
                        {"name": "unit", "status": "COMPLETED", "conclusion": "SUCCESS"},
                    ],
                }, ""
            query = args[-1]
            if "reviewThreads" in query:
                return {
                    "data": {
                        "repository": {
                            "pullRequest": {
                                "reviewThreads": {
                                    "pageInfo": {"hasNextPage": False},
                                    "nodes": [],
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
                                                "pageInfo": {"hasNextPage": True},
                                                "nodes": [],
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
        self.assertIn("did not fit", self.guard.merge_readiness_reason(snapshot))


class ConsumerStopTests(unittest.TestCase):
    def test_only_stop_carries_the_consumer_receipt(self):
        document = json.loads(hosts.lifecycle_hooks_document("grok"))
        stop = document["hooks"]["Stop"][0]["hooks"][0]["command"]
        pre = document["hooks"]["PreToolUse"][0]["hooks"][0]["command"]
        self.assertIn("no-harness-runtime", stop)
        self.assertNotIn("no-harness-runtime", pre)
        self.assertLessEqual(len(stop), hosts.HOOK_COMMAND_MAX_CHARS)
        for host, event in (("cursor", "stop"), ("antigravity", "Stop"), ("claude", "Stop")):
            command = hosts.chaos_guard_locator_command(windows=False, host=host, event=event)
            self.assertLessEqual(len(command), hosts.HOOK_COMMAND_MAX_CHARS, host)

    def test_consumer_stop_exits_0_and_pretool_still_exits_2(self):
        stop = json.loads(hosts.lifecycle_hooks_document("grok"))["hooks"]["Stop"][0]["hooks"][0]["command"]
        pre = json.loads(hosts.lifecycle_hooks_document("grok"))["hooks"]["PreToolUse"][0]["hooks"][0]["command"]
        with tempfile.TemporaryDirectory() as temporary:
            repo = Path(temporary)
            _git(repo, "init", "-q")
            _git(repo, "commit", "-q", "--allow-empty", "-m", "init")
            stopped = _run(stop, repo)
            blocked = _run(pre, repo)
        self.assertEqual(0, stopped.returncode, stopped.stderr)
        self.assertEqual("no-harness-runtime\n", stopped.stderr)
        self.assertNotIn("can't open file", stopped.stderr)
        self.assertEqual("", stopped.stdout)
        self.assertFalse((repo / ".chaos-engine-state").exists())
        self.assertEqual(2, blocked.returncode, blocked.stderr)
        self.assertIn("missing .chaos-engine/hooks/launch.py", blocked.stderr)
        self.assertNotIn("no-harness-runtime", blocked.stderr)

    def test_broken_harness_stop_still_exits_2(self):
        stop = hosts.chaos_guard_locator_command(windows=False, host="grok", event="Stop")
        with tempfile.TemporaryDirectory() as temporary:
            repo = Path(temporary)
            _git(repo, "init", "-q")
            _git(repo, "commit", "-q", "--allow-empty", "-m", "init")
            (repo / ".chaos-engine").mkdir()
            completed = _run(stop, repo)
        self.assertEqual(2, completed.returncode, completed.stderr)
        self.assertIn("missing .chaos-engine/hooks/launch.py", completed.stderr)
        self.assertNotIn("no-harness-runtime", completed.stderr)

    def test_generated_commands_pass_bash_n_and_zsh_n_when_zsh_exists(self):
        commands = [
            hosts.chaos_guard_locator_command(windows=False, host="codex", event="PreToolUse"),
            hosts.chaos_guard_locator_command(windows=False, host="codex", event="Stop"),
            json.loads(hosts.lifecycle_hooks_document("grok"))["hooks"]["Stop"][0]["hooks"][0]["command"],
        ]
        zsh = shutil.which("zsh")
        for command in commands:
            self.assertIn(": <<'#'", command)
            bash = subprocess.run(["bash", "-n", "-c", command], capture_output=True, text=True, check=False)
            self.assertEqual(0, bash.returncode, bash.stderr)
            if zsh:
                checked = subprocess.run([zsh, "-n", "-c", command], capture_output=True, text=True, check=False)
                self.assertEqual(0, checked.returncode, checked.stderr)


class DeliveryGuidanceTests(unittest.TestCase):
    def test_delivery_and_retrospective_text(self):
        cycle = (ROOT / "references" / "delivery-cycle.md").read_text(encoding="utf-8")
        reflection = (ROOT / "references" / "reflection-checkpoints.md").read_text(encoding="utf-8")
        lifecycle = (ROOT / "references" / "lifecycle-hooks.md").read_text(encoding="utf-8")
        skill = (ROOT / "skills" / "self-improve" / "SKILL.md").read_text(encoding="utf-8")
        retrospective = (
            "Write the learning retrospective only after the merge SHA exists "
            "and after subagents and monitors have exited. A non-required check "
            "must not start the note and must not be the only reason the note waits."
        )
        for text in (cycle, reflection):
            self.assertIn("GIT_COMMITTER_NAME", text)
            self.assertIn("Environment committer variables override `git -c user.*`", text)
            self.assertIn("`git rebase --onto <base> <base>`", text)
            self.assertIn("`git format-patch <rev>..HEAD`", text)
            self.assertIn("`git format-patch -N <rev>`", text)
        self.assertIn("`gh pr merge --squash`", cycle)
        self.assertNotIn("gh pr merge --merge", cycle)
        self.assertNotIn("Never squash", cycle)
        self.assertIn("A skipped required check is not success", cycle)
        self.assertIn("A skipped or neutral check outside the required set does not block", cycle)
        self.assertIn("An unmarked skip blocks", cycle)
        self.assertIn("An empty check list is not success", cycle)
        for text in (reflection, lifecycle, skill):
            self.assertIn(retrospective, text)
        self.assertIn("no-harness-runtime", lifecycle)
