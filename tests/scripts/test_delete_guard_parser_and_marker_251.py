"""#251: close four delete-guard shell parser gaps and align the assert-justified marker."""

from __future__ import annotations

import importlib.util
import os
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
import unittest.mock
from pathlib import Path

GIT = shutil.which("git") or "git"
ROOT = Path(__file__).resolve().parents[2]


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


GUARD = _load("chaos_engine_delete_guard_251", ROOT / "runtime" / "delete_guard.py")
GATE = _load("chaos_engine_test_quality_gate_251", ROOT / "rules" / "test_quality_gate.py")
HOOK = _load("chaos_engine_guard_251", ROOT / "hooks" / "guard.py")
BOUNDARY = _load("chaos_engine_operation_boundary_262", ROOT / "rules" / "operation_boundary.py")


def _git(cwd: Path, *argv: str) -> None:
    subprocess.run(  # nosec B603 - fixed git argv, temp fixture paths.
        [
            GIT,
            "-C",
            str(cwd),
            "-c",
            "user.name=t",
            "-c",
            "user.email=t@example.invalid",
            "-c",
            "commit.gpgsign=false",
            *argv,
        ],
        check=True,
        capture_output=True,
    )


class DeleteGuardParser251Test(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.base = Path(self.temp.name).resolve()
        home = self.base / "home"
        home.mkdir()
        self.patches = [
            unittest.mock.patch.object(GUARD, "DEFAULT_ALLOW", ()),
            unittest.mock.patch.dict(
                os.environ,
                {"HOME": str(home), "XDG_STATE_HOME": str(home / "state")},
            ),
        ]
        for patch in self.patches:
            patch.start()
        self.repo = self.base / "work"
        self.repo.mkdir()
        _git(self.repo, "init", "-q", "-b", "main")
        (self.repo / "keep.txt").write_text("x", encoding="utf-8")
        _git(self.repo, "add", ".")
        _git(self.repo, "commit", "-qm", "init")
        (self.repo / "precious.txt").write_text("only copy", encoding="utf-8")

    def tearDown(self) -> None:
        for patch in reversed(self.patches):
            patch.stop()
        self.temp.cleanup()

    def reason(self, command: str) -> str:
        return GUARD.block_reason(command, self.repo, self.repo)

    def assert_refuses(self, command: str) -> None:
        reason = self.reason(command)
        self.assertIn("untracked", reason, command)
        self.assertIn("precious.txt", reason, command)

    def test_unspaced_subshell_inside_command_substitution_is_refused(self) -> None:
        for command in (
            'echo "$((true); rm -rf precious.txt)"',
            'echo "$((cat <<\'EOF\'\nhi\nEOF\n); rm -rf precious.txt)"',
        ):
            with self.subTest(command=command):
                self.assert_refuses(command)

    def test_genuine_arithmetic_expansion_stays_allowed(self) -> None:
        for command in (
            "echo $((1 + 2))",
            "echo $(( (1 + 2) * 3 ))",
            "echo $((2 * 3 + 4))",
        ):
            with self.subTest(command=command):
                self.assertEqual("", self.reason(command))

    def test_heredoc_delimiter_backslash_newline_is_refused(self) -> None:
        command = "cat <<EO\\\nF\n$(rm -rf precious.txt)\nEOF\n"
        self.assert_refuses(command)

    def test_heredoc_delimiter_crlf_continuation_is_unquoted(self) -> None:
        delimiter, quoted, _pos = GUARD._read_heredoc_delimiter("<<EO\\\r\nF\nbody", 2)
        self.assertEqual("EOF", delimiter)
        self.assertFalse(quoted)

    def test_heredoc_delimiter_escaped_non_newline_stays_quoted(self) -> None:
        delimiter, quoted, _pos = GUARD._read_heredoc_delimiter("<<E\\OF\nbody", 2)
        self.assertEqual("EOF", delimiter)
        self.assertTrue(quoted)

    def test_case_pattern_inside_command_substitution_is_refused(self) -> None:
        self.assert_refuses('echo "$(case x in x) rm -rf precious.txt;; esac)"')

    def test_benign_case_command_substitution_stays_allowed(self) -> None:
        self.assertEqual("", self.reason('echo "$(case x in x) echo hi;; esac)"'))

    def test_esac_word_inside_echo_cannot_close_case_pattern(self) -> None:
        self.assert_refuses('echo "$(case y in x) echo esac;; y) rm -rf precious.txt;; esac)"')

    def test_bare_case_word_is_not_a_case_keyword(self) -> None:
        self.assertEqual("", self.reason('echo "$(echo case)" && echo hi'))

    def test_reserved_word_and_pattern_alternation_bypasses_are_refused(self) -> None:
        for command in (
            'echo "$(if case x in x) rm -rf precious.txt;; esac; then :; fi)"',
            'echo "$(while case x in x) rm -rf precious.txt; false;; esac; do :; done)"',
            'echo "$(until case x in x) rm -rf precious.txt;; esac; do :; done)"',
            'echo "$(time case x in x) rm -rf precious.txt;; esac)"',
            'echo "$(case esac in a|esac) rm -rf precious.txt;; esac)"',
            'echo "$(case y in x) esac=1;; y) rm -rf precious.txt;; esac)"',
            'echo "$(case "esac=1" in x) true;; esac=1) rm -rf precious.txt;; esac)"',
            'echo "$(case y in x) true; esac-foo;; y) rm -rf precious.txt;; esac)"',
        ):
            with self.subTest(command=command):
                self.assert_refuses(command)

    def test_benign_case_word_inside_echo_with_tracked_rm_stays_allowed(self) -> None:
        bare = self.base / "origin.git"
        subprocess.run(  # nosec B603 - fixed git argv, temp fixture path.
            [GIT, "init", "--bare", "-q", str(bare)], check=True, capture_output=True
        )
        _git(self.repo, "remote", "add", "origin", str(bare))
        _git(self.repo, "push", "-q", "-u", "origin", "main")
        self.assertEqual("", self.reason('echo "$(echo case)" && rm keep.txt'))

    def test_posix_optional_leading_paren_in_case_pattern_is_refused(self) -> None:
        for command in (
            'echo "$(case x in (a|b) rm -rf precious.txt;; esac)"',
            'echo "$(case x in (a|b) echo esac;; y) rm -rf precious.txt;; esac)"',
        ):
            with self.subTest(command=command):
                self.assert_refuses(command)

    def test_time_and_coproc_prefixes_before_case_are_refused(self) -> None:
        for command in (
            'echo "$(time -p case x in x) rm -rf precious.txt;; esac)"',
            'echo "$(time -- case x in x) rm -rf precious.txt;; esac)"',
            'echo "$(! time -p case x in x) rm -rf precious.txt;; esac)"',
            'echo "$(coproc case x in x) rm -rf precious.txt;; esac; wait)"',
            'echo "$(coproc mycp case x in x) rm -rf precious.txt;; esac; wait)"',
        ):
            with self.subTest(command=command):
                self.assert_refuses(command)

    def test_optional_leading_paren_before_esac_pattern_is_refused(self) -> None:
        for command in (
            'echo "$(case esac in a) true;; (esac) rm -rf precious.txt;; esac)"',
            'echo "$(case esac in\n(esac) rm -rf precious.txt;; esac)"',
        ):
            with self.subTest(command=command):
                self.assert_refuses(command)

    def test_closing_command_substitution_does_not_start_a_command(self) -> None:
        for command in (
            'echo "$(case y in x) echo $(:) esac;; y) rm -rf precious.txt;; esac)"',
            'echo "$(case y in x) echo $((0)) esac;; y) rm -rf precious.txt;; esac)"',
            'echo "$(case y in x) (:) && echo $(true) esac;; y) rm -rf precious.txt;; esac)"',
        ):
            with self.subTest(command=command):
                self.assert_refuses(command)

    def test_line_continuation_inside_reserved_words_is_refused(self) -> None:
        for command in (
            'echo "$(ca\\\nse x in x) rm -rf precious.txt;; esac)"',
            'echo "$(ca\\\nse x in x) rm -rf precious.txt;; es\\\nac)"',
        ):
            with self.subTest(command=command):
                self.assert_refuses(command)

    def test_time_and_coproc_continuations_before_case_are_refused(self) -> None:
        for command in (
            'echo "$(coproc ca\\\nse x in x) rm -rf precious.txt;; esac; wait)"',
            'echo "$(coproc my\\\ncp case x in x) rm -rf precious.txt;; esac; wait)"',
            'echo "$(time -\\\np case x in x) rm -rf precious.txt;; esac)"',
            'echo "$(time -\\\n- case x in x) rm -rf precious.txt;; esac)"',
            'echo "$(time -p\\\n case x in x) rm -rf precious.txt;; esac)"',
            'echo "$(time -\\\np ! case x in x) rm -rf precious.txt;; esac)"',
            'echo "$(coproc ca\\\r\nse x in x) rm -rf precious.txt;; esac; wait)"',
            'echo "$(time -\\\r\np case x in x) rm -rf precious.txt;; esac)"',
        ):
            with self.subTest(command=command):
                self.assert_refuses(command)

    def test_quoted_and_escaped_coproc_names_before_case_are_refused(self) -> None:
        for command in (
            'echo "$(coproc \'mycp\' case x in x) rm -rf precious.txt;; esac; wait)"',
            'echo "$(coproc "mycp" case x in x) rm -rf precious.txt;; esac; wait)"',
            'echo "$(coproc $\'mycp\' case x in x) rm -rf precious.txt;; esac; wait)"',
            'echo "$(coproc my\\cp case x in x) rm -rf precious.txt;; esac; wait)"',
        ):
            with self.subTest(command=command):
                self.assert_refuses(command)

    def test_prefix_redirection_before_case_is_refused(self) -> None:
        for command in (
            'echo "$(time -p >/dev/null case x in x) rm -rf precious.txt;; esac)"',
            'echo "$(coproc mycp >/dev/null case x in x) rm -rf precious.txt;; esac; wait)"',
        ):
            with self.subTest(command=command):
                self.assert_refuses(command)

    def test_unclosed_redirect_inside_substitution_raises_value_error(self) -> None:
        command = 'echo "$(>'
        with self.assertRaises(ValueError):
            GUARD._scan_balanced_paren(command, command.index("(") + 1)

    def test_scan_balanced_paren_prefix_scan_is_linear(self) -> None:
        text = "(" + ">/dev/null " * 4000 + "case x in x) echo ok;; esac)"
        started = time.monotonic()
        end = GUARD._scan_balanced_paren(text, 0)
        elapsed = time.monotonic() - started
        self.assertEqual(len(text), end)
        self.assertLess(elapsed, 5.0)

    def test_array_literal_substitutions_are_refused(self) -> None:
        for command in (
            "foo=( $(rm -rf precious.txt) )",
            "foo=( <(rm -rf precious.txt) )",
            "foo=( `rm -rf precious.txt` )",
            'foo=( "$(rm -rf precious.txt)" )',
        ):
            with self.subTest(command=command):
                self.assert_refuses(command)

    def test_quoted_array_literal_substitutions_stay_allowed(self) -> None:
        for command in (
            "foo=( '$(rm -rf precious.txt)' )",
            "foo=( '<(rm -rf precious.txt)' )",
            "foo=( '`rm -rf precious.txt`' )",
        ):
            with self.subTest(command=command):
                self.assertEqual("", self.reason(command))

    def test_unquoted_heredoc_process_substitution_is_data(self) -> None:
        self.assertEqual("", self.reason("cat <<EOF\n<(rm -rf precious.txt)\nEOF\n"))

    def test_array_cmd_subs_helper_skips_quotes_and_comments(self) -> None:
        subs = GUARD._scan_array_cmd_subs(
            "# $(rm -rf comment.txt)\n"
            "'$(rm -rf single.txt)' '<(rm -rf single2.txt)' '`rm -rf single3.txt`' "
            "$'$(rm -rf ansi.txt)' "
            "<(rm -rf run.txt) $(rm -rf sub.txt)"
        )
        self.assertEqual(["rm -rf run.txt", "rm -rf sub.txt"], subs)

    def test_plain_array_literal_stays_allowed(self) -> None:
        self.assertEqual("", self.reason("foo=(a b c)"))


class OperationBoundary262Test(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)

    def tearDown(self) -> None:
        self.temp.cleanup()

    def block(self, command: str) -> str | None:
        return BOUNDARY.force_push_block(self.root, command)

    def test_shell_statements_splits_unquoted_newlines(self) -> None:
        self.assertEqual(
            ["git push origin main", "gh workflow run ci -f key=val"],
            BOUNDARY._shell_statements(
                "git push origin main\ngh workflow run ci -f key=val"
            ),
        )
        self.assertEqual(
            ["echo a", "echo b"], BOUNDARY._shell_statements("echo a\r\necho b")
        )

    def test_shell_statements_keeps_continuations_quotes_and_heredocs(self) -> None:
        for command in (
            "echo a \\\nb",
            'echo "a\nb"',
            "echo $(printf 'a\nb')",
            "cat <<EOF\nbody\nEOF\n",
        ):
            with self.subTest(command=command):
                statements = BOUNDARY._shell_statements(command)
                self.assertEqual(1, len(statements), statements)

    def test_newline_separated_push_and_gh_workflow_flag_is_allowed(self) -> None:
        self.assertIsNone(
            self.block("git push origin main\ngh workflow run ci -f key=val")
        )

    def test_quoted_non_git_payloads_are_allowed(self) -> None:
        for command in (
            'gh issue create --body "git push -f -f here"',
            'python3 -c "print(\'git push -f\')"',
            'echo "git push --force here"',
            "echo git push -f here | cat",
        ):
            with self.subTest(command=command):
                self.assertIsNone(self.block(command))

    def test_true_force_pushes_are_refused(self) -> None:
        for command in (
            "git push origin main -f",
            "git push --force origin main",
            "git push --force-with-lease origin main",
            "git push origin +main",
            'bash -c "git push -f origin main"',
            "/bin/bash -c 'git push -f origin main'",
            'bash -c "echo x; git push -f origin main"',
            'eval "git push -f origin main"',
            "git -C /tmp push -f origin main",
            "/usr/bin/git push -f origin main",
            "sudo -u user git push -f origin main",
            'echo "$(git push -f origin main)"',
        ):
            with self.subTest(command=command):
                self.assertEqual("force-push-without-approval", self.block(command))

    def test_review_force_push_bypasses_are_refused(self) -> None:
        for command in (
            ">/dev/null git push -f origin main",
            "2>/dev/null git push -f origin main",
            "if true; then git push -f origin main; fi",
            "{ git push -f origin main; }",
            "env -i git push -f origin main",
            "sudo -S git push -f origin main",
            "sudo -i git push -f origin main",
            "sudo -g wheel git push -f origin main",
            "bash -cl 'git push -f origin main'",
            "bash -c $'git push -f origin main'",
            'bash -c $"git push -f origin main"',
            "eval -- git push -f origin main",
            "bash <<EOF\ngit push -f origin main\nEOF\n",
            "sh <<EOF\ngit push -f origin main\nEOF\n",
            "dash <<'EOF'\ngit push -f origin main\nEOF\n",
            "ksh <<EOF\ngit push -f origin main\nEOF\n",
            "zsh <<EOF\ngit push -f origin main\nEOF\n",
            "nice git push -f origin main",
            "setsid git push -f origin main",
            "stdbuf -oL git push -f origin main",
            "ionice -c2 git push -f origin main",
            "doas git push -f origin main",
            "flock git push -f origin main",
            "flock /tmp/lock git push -f origin main",
            "xargs git push -f origin main",
            "xargs -I {} git push -f origin main",
            "stdbuf -o L git push -f origin main",
            "nice -n 5 git push -f origin main",
        ):
            with self.subTest(command=command):
                self.assertEqual("force-push-without-approval", self.block(command))

    def test_wrapper_option_values_are_refused(self) -> None:
        for command in (
            "ionice --class 2 git push -f origin main",
            "ionice --classdata 4 git push -f origin main",
            "ionice -c 2 git push -f origin main",
            "sudo -D /tmp git push -f origin main",
            "sudo --close-from 3 git push -f origin main",
            "sudo -h localhost git push -f origin main",
            "sudo --host localhost git push -f origin main",
            "sudo -p prompt git push -f origin main",
            "sudo --prompt prompt git push -f origin main",
            "sudo -R / git push -f origin main",
            "sudo --chroot / git push -f origin main",
            "sudo -r unconfined_r git push -f origin main",
            "sudo --role unconfined_r git push -f origin main",
            "sudo -t unconfined_t git push -f origin main",
            "sudo --type unconfined_t git push -f origin main",
            "sudo -T 5 git push -f origin main",
            "sudo --command-timeout 5 git push -f origin main",
            "sudo -U other git push -f origin main",
            "sudo --other-user other git push -f origin main",
            "xargs --max-args 1 git push -f origin main",
            "xargs --max-lines 1 git push -f origin main",
            "xargs --arg-file /tmp/list git push -f origin main",
            "xargs --delimiter , git push -f origin main",
            "xargs --max-procs 1 git push -f origin main",
            "xargs --max-chars 1000 git push -f origin main",
            "xargs --process-slot-var SLOT git push -f origin main",
            "flock -E 1 /tmp/lock git push -f origin main",
            "flock --conflict-exit-code 1 /tmp/lock git push -f origin main",
            "flock -c 'git push -f origin main'",
            "flock --command 'git push -f origin main'",
            "flock --command='git push -f origin main'",
            "env -S 'git push -f origin main'",
            "env --split-string 'git push -f origin main'",
            "env --split-string='git push -f origin main'",
            "env --unset NAME git push -f origin main",
        ):
            with self.subTest(command=command):
                self.assertEqual("force-push-without-approval", self.block(command))

    def test_wrapper_option_values_do_not_hide_a_plain_command(self) -> None:
        for command in (
            "sudo -D /tmp echo ok",
            "flock -c 'echo ok'",
            "env -S 'echo ok'",
            "env --unset NAME echo ok",
        ):
            with self.subTest(command=command):
                self.assertIsNone(self.block(command))

    def test_heredoc_data_is_not_a_force_push(self) -> None:
        for command in (
            "cat <<EOF\ngit push -f origin main\nEOF\n",
            "bash -c 'echo ok' <<EOF\ngit push -f origin main\nEOF\n",
        ):
            with self.subTest(command=command):
                self.assertIsNone(self.block(command))


class MarkerAlignment251Test(unittest.TestCase):
    def test_guard_hint_unblocks_quality_gate_both_markers(self) -> None:
        source = (ROOT / "hooks" / "guard.py").read_text(encoding="utf-8")
        self.assertIn("`assert-justified: <reason>`", source)
        old = "def test_pays():\n    assertEqual(1, 1)\n"

        def codes(text: str, previous: str | None = None) -> set[str]:
            report = GATE.evaluate_content("tests/test_pays.py", text, previous)
            return {hit["code"] for hit in report["hits"]}

        weakened = "def test_pays():\n    assertTrue(True)\n"
        self.assertIn("assertion-weakening", codes(weakened, old))
        for marker in ("assert-justified:", "assertion-justified:"):
            with self.subTest(marker=marker):
                justified = f"def test_pays():\n    assertTrue(True)  # {marker} bool contract\n"
                self.assertNotIn("assertion-weakening", codes(justified, old))

        assertionless = "def test_pays():\n    run()\n"
        self.assertIn("assertion-weakening", codes(assertionless))
        for marker in ("assert-justified:", "assertion-justified:"):
            with self.subTest(marker=marker):
                justified = f"# {marker} process launch\ndef test_pays():\n    run()\n"
                self.assertNotIn("assertion-weakening", codes(justified))

    def test_change_has_token_is_linear_with_many_tokens(self) -> None:
        size = 3000
        lines = {i: f"line {i}" for i in range(1, size + 1)}
        added = [(i, lines[i]) for i in range(1, size + 1)]
        tokens = tuple(f"missing-{i}:" for i in range(120))
        started = time.monotonic()
        found = GATE._change_has_token(lines, added, tokens)
        elapsed = time.monotonic() - started
        self.assertFalse(found)
        self.assertLess(elapsed, 5.0)


if __name__ == "__main__":
    unittest.main()
