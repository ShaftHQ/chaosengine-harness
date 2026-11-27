"""Required-check merge gate, consumer Stop receipt, and zsh-safe hook commands."""

from __future__ import annotations

import importlib.util
import json
import os
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


_RECORD_ARGV = (
    "import json, os, sys\n"
    "with open(os.environ['CE_TEST_ARGV'], 'w', encoding='utf-8') as handle:\n"
    "    json.dump(sys.argv[1:], handle)\n"
    'print("{}")\n'
)
_BLOCKING_JSON = (
    '{"decision": "block", "reason": "ChaosEngine launch.py requires host name (e.g. claude)"}'
)
_BLOCK_LAUNCHER = (
    "import sys\n"
    f"print({_BLOCKING_JSON!r})\n"
    "sys.exit(2)\n"
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


class UnixHookLauncherArgTests(unittest.TestCase):
    def _project(self, temporary: str, launcher: str) -> tuple[Path, Path]:
        project = Path(temporary) / "project with spaces"
        (project / ".chaos-engine" / "hooks").mkdir(parents=True)
        target = project / ".chaos-engine" / "hooks" / "launch.py"
        target.write_text(launcher, encoding="utf-8")
        return project, target

    def _run_shell(
        self, shell: str, command: str, cwd: Path, env: dict[str, str] | None = None,
    ) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [shell, "-c", command],
            cwd=cwd,
            env=env,
            capture_output=True,
            text=True,
            check=False,
        )

    def test_codex_stop_passes_separate_words_in_every_available_shell(self):
        command = hosts.chaos_guard_locator_command(windows=False, host="codex", event="Stop")
        shells = [shutil.which(name) for name in ("zsh", "bash", "sh")]
        self.assertIsNotNone(shells[1])
        self.assertIsNotNone(shells[2])
        for shell in shells:
            if shell is None:
                continue
            with self.subTest(shell=shell), tempfile.TemporaryDirectory(prefix="ce hook ") as temporary:
                project, _launcher = self._project(temporary, _RECORD_ARGV)
                argv_file = project / "argv.json"
                env = dict(os.environ, CE_TEST_ARGV=str(argv_file))
                result = self._run_shell(shell, command, project, env)
                self.assertEqual(0, result.returncode, result.stderr)
                self.assertEqual("{}\n", result.stdout)
                self.assertEqual(["codex", "Stop"], json.loads(argv_file.read_text(encoding="utf-8")))

    def test_unix_command_uses_literal_words_without_variable_splitting(self):
        for host, event, words in (
            ("codex", "Stop", "codex Stop"),
            ("grok", "PreToolUse", "grok PreToolUse"),
            ("claude", None, "claude"),
        ):
            with self.subTest(host=host, event=event):
                command = hosts.chaos_guard_locator_command(windows=False, host=host, event=event)
                unix, _, _powershell = command.partition(": <<'#'")
                self.assertNotIn("$a", unix)
                self.assertNotIn('a="', unix)
                self.assertIn(
                    f'exec python3 "$f" {words}||exec py -3 "$f" {words}', unix
                )
        antigravity = hosts.chaos_guard_locator_command(
            windows=False, host="antigravity", event="Stop"
        )
        self.assertNotIn("$a", antigravity)
        self.assertIn('exec "$p" "$f" antigravity Stop', antigravity)
        self.assertIn('exec "$p" -3 "$f" antigravity Stop', antigravity)

    def test_py_fallback_gets_three_and_launcher_words_separately(self):
        command = hosts.chaos_guard_locator_command(windows=False, host="codex", event="Stop")
        bash = shutil.which("bash")
        self.assertIsNotNone(bash)
        with tempfile.TemporaryDirectory(prefix="ce hook ") as temporary:
            project, launcher = self._project(temporary, _RECORD_ARGV)
            bin_dir = Path(temporary) / "bin"
            bin_dir.mkdir()
            py = bin_dir / "py"
            py.write_text(
                f"#!{sys.executable}\n"
                "import json, os, sys\n"
                "with open(os.environ['CE_TEST_PY_ARGV'], 'w', encoding='utf-8') as handle:\n"
                "    json.dump(sys.argv[1:], handle)\n"
                'print("{}")\n',
                encoding="utf-8",
            )
            py.chmod(0o755)
            argv_file = project / "argv.json"
            py_argv_file = project / "py-argv.json"
            env = {
                "CE_TEST_ARGV": str(argv_file),
                "CE_TEST_PY_ARGV": str(py_argv_file),
                "PATH": str(bin_dir),
            }
            result = self._run_shell(bash, command, project, env)
            self.assertEqual(0, result.returncode, result.stderr)
            self.assertEqual("{}\n", result.stdout)
            self.assertEqual(
                ["-3", str(launcher), "codex", "Stop"],
                json.loads(py_argv_file.read_text(encoding="utf-8")),
            )
            self.assertFalse(argv_file.exists())

    def test_host_only_launcher_gets_no_second_argument(self):
        command = hosts.chaos_guard_locator_command(windows=False, host="claude")
        bash = shutil.which("bash")
        self.assertIsNotNone(bash)
        with tempfile.TemporaryDirectory(prefix="ce hook ") as temporary:
            project, _launcher = self._project(temporary, _RECORD_ARGV)
            argv_file = project / "argv.json"
            env = dict(os.environ, CE_TEST_ARGV=str(argv_file))
            result = self._run_shell(bash, command, project, env)
            self.assertEqual(0, result.returncode, result.stderr)
            self.assertEqual(["claude"], json.loads(argv_file.read_text(encoding="utf-8")))

    def test_launcher_exit_2_propagates_without_py_fallback(self):
        command = hosts.chaos_guard_locator_command(windows=False, host="codex", event="Stop")
        bash = shutil.which("bash")
        self.assertIsNotNone(bash)
        with tempfile.TemporaryDirectory(prefix="ce hook ") as temporary:
            project, _launcher = self._project(temporary, _BLOCK_LAUNCHER)
            bin_dir = Path(temporary) / "bin"
            bin_dir.mkdir()
            marker = bin_dir / "py-ran"
            py = bin_dir / "py"
            py.write_text(
                f"#!{sys.executable}\n"
                "import os, pathlib, sys\n"
                "pathlib.Path(os.environ['CE_TEST_PY_MARKER']).write_text('ran')\n"
                'print("{}")\n',
                encoding="utf-8",
            )
            py.chmod(0o755)
            env = dict(
                os.environ,
                CE_TEST_PY_MARKER=str(marker),
                PATH=f"{bin_dir}{os.pathsep}{os.environ['PATH']}",
            )
            result = self._run_shell(bash, command, project, env)
            self.assertEqual(2, result.returncode, result.stderr)
            self.assertEqual(_BLOCKING_JSON + "\n", result.stdout)
            self.assertFalse(marker.exists())

    def test_unsafe_launch_arguments_fail_closed(self):
        with self.assertRaises(ValueError):
            hosts.chaos_guard_locator_command(windows=False, host="codex; stop")
        with self.assertRaises(ValueError):
            hosts.chaos_guard_locator_command(windows=False, host="codex", event="Stop extra")


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
