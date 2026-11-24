"""#208: delete guard allows quoted/heredoc data and computed cd without delete, while keeping real deletes blocked."""

from __future__ import annotations

import importlib.util
import os
import shutil
import subprocess  # nosec B404 - fixed git argv in temp fixtures.
import tempfile
import unittest
import unittest.mock
from pathlib import Path

GIT = shutil.which("git") or "git"
ROOT = Path(__file__).resolve().parents[2]


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


GUARD = _load("chaos_engine_delete_guard_208", ROOT / "runtime" / "delete_guard.py")


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


class DeleteGuardIssue208Test(unittest.TestCase):
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
        self.precious = self.repo / "precious.txt"
        self.precious.write_text("only copy", encoding="utf-8")

    def tearDown(self) -> None:
        for patch in reversed(self.patches):
            patch.stop()
        self.temp.cleanup()

    def reason(self, command: str, cwd: Path | None = None) -> str:
        return GUARD.block_reason(command, cwd or self.repo, self.repo)

    # --- False positives from #208 that MUST be allowed ---

    def test_issue_208_exact_combined_python_heredoc_and_computed_cd_subshell(self) -> None:
        for tail in (
            'T=$(mktemp -d); (cd "$T" && bash ./script.sh)',
            'T=$(mktemp -d); ( cd "$T" && bash ./script.sh )',
            'T=$(mktemp -d); cd "$T" && bash ./script.sh',
        ):
            cmd = (
                "python3 - <<'PY'\n"
                "open('script.sh','w').write(\"trap 'rm -f lock' EXIT\\n\")\n"
                "PY\n"
                + tail
            )
            with self.subTest(tail=tail):
                self.assertEqual("", self.reason(cmd))

    def test_multiline_gh_issue_create_body_with_delete_words_and_unmatched_apostrophe(self) -> None:
        cmd = (
            'gh issue create --title "Delete guard #208" --body "mentions rm -rf foo\n'
            "rmdir bar and mv a b\n"
            "and 'quoted' text\n"
            "with unmatched ' apostrophe\n"
            "trap 'rm -f lock' EXIT\n"
            'and shutil.rmtree(\'bar\')"'
        )
        self.assertEqual("", self.reason(cmd))

    def test_multiline_single_quoted_body_with_unmatched_double_quote(self) -> None:
        cmd = (
            "gh issue create --title 'Fix' --body 'mentions rm -rf foo\n"
            "rmdir bar\n"
            "mv a b\n"
            'and "unmatched double quote\n'
            "and Path(\"precious.txt\").unlink()'"
        )
        self.assertEqual("", self.reason(cmd))

    def test_non_shell_heredocs_treat_body_as_data(self) -> None:
        for cmd in (
            "cat <<'EOF' > notes.txt\nrm -rf precious.txt\n'unmatched\nEOF",
            'cat <<"EOF" > notes.txt\nrm -rf precious.txt\nEOF',
            "cat <<-EOF > notes.txt\n\trm -rf precious.txt\n\tEOF",
            "cat <<-'EOF' > notes.txt\n\trm -rf precious.txt\n\tEOF",
            "tee script.sh <<'EOF' && chmod +x script.sh\nrm -rf precious.txt\nEOF",
            "gh issue create --title 't' --body-file - <<'EOF'\nrm -rf precious.txt\nshutil.rmtree('precious.txt')\nEOF",
        ):
            with self.subTest(cmd=cmd):
                self.assertEqual("", self.reason(cmd))

    def test_python_heredoc_with_delete_text_in_string_literal_allowed(self) -> None:
        cmd = (
            "python3 - <<'PY'\n"
            "doc = '''rm -rf precious.txt\n"
            "shutil.rmtree('precious.txt')\n"
            "Path('precious.txt').unlink()\n"
            "'''\n"
            "print(doc)\n"
            "print(\"rm\")\n"
            "import os\n"
            "os.system(\"rm -rf precious.txt\")\n"
            "PY"
        )
        self.assertEqual("", self.reason(cmd))

    def test_computed_cd_without_delete_is_allowed(self) -> None:
        for cmd in (
            'T=$(mktemp -d); cd "$T" && bash ./script.sh',
            'T=$(mktemp -d); cd "$T" && echo "rm -rf foo"',
            'T=$(mktemp -d); (cd "$T" && echo "rm -rf foo")',
            'T=$(mktemp -d); pushd "$T" && ls -la',
            'cd "$T" && find . -name "*.txt" -print',
            'cd "$T" && git clean -n',
            # Absolute targets do not resolve against the computed cwd.
            "cd \"$T\" && rm -rf /nonexistent-7251/x",
            "pushd \"$T\" && rm -f /nonexistent-7251/x",
        ):
            with self.subTest(cmd=cmd):
                self.assertEqual("", self.reason(cmd))

    def test_subshell_computed_cd_does_not_taint_parent_shell(self) -> None:
        remote = self.base / "remote.git"
        subprocess.run([GIT, "init", "-q", "--bare", str(remote)], check=True, capture_output=True)  # nosec B603
        _git(self.repo, "remote", "add", "origin", str(remote))
        _git(self.repo, "push", "-q", "-u", "origin", "main")
        # keep.txt is tracked, clean, and pushed -> allowed after subshell exits
        cmd_allowed = 'T=$(mktemp -d); (cd "$T" && bash ./script.sh); rm -f keep.txt'
        self.assertEqual("", self.reason(cmd_allowed))
        # precious.txt is untracked -> refused for being untracked, NOT as computed cd
        cmd_refused = 'T=$(mktemp -d); (cd "$T" && bash ./script.sh); rm -f precious.txt'
        reason = self.reason(cmd_refused)
        self.assertIn("untracked", reason)
        self.assertNotIn("cd to a computed path", reason)

    # --- Negative / Security tests that MUST STILL be refused ---

    def test_computed_cd_before_real_delete_is_still_refused(self) -> None:
        for cmd in (
            'cd "$T" && rm -rf foo',
            'cd "$T" && rm -rf *.nonexistent_glob',
            'pushd "$T" && rm -rf foo',
            '(cd "$T" && rm -rf foo)',
            'cd -P "$T" && rm -rf foo',
            'cd "$T" && cd sub && rm -rf foo',
            'cd "$T" && find . -delete',
            'cd "$T" && mv foo bar',
            'cd "$T" && git clean -fdx',
            'cd "$T" && bash -c "rm -rf foo"',
            "cd \"$T\" && python3 - <<'PY'\nimport shutil; shutil.rmtree('foo')\nPY",
            'cd "$T" && rm -rf foo /nonexistent-7251/x',
        ):
            with self.subTest(cmd=cmd):
                self.assertIn("cd to a computed path before a delete", self.reason(cmd))

    def test_absolute_delete_after_computed_cd_is_checked_not_blamed_on_cwd(self) -> None:
        cmd = f'cd "$T" && rm -f {self.precious}'
        reason = self.reason(cmd)
        self.assertIn("untracked", reason)
        self.assertNotIn("cd to a computed path", reason)
        py = f'cd "$T" && python3 -c "import os; os.unlink(\'{self.precious}\')"'
        py_reason = self.reason(py)
        self.assertIn("untracked", py_reason)
        self.assertNotIn("cd to a computed path", py_reason)

    def test_shell_heredoc_with_real_delete_is_still_refused(self) -> None:
        for shell in ("sh", "bash", "zsh", "dash"):
            cmd = f"{shell} <<'EOF'\nrm -rf {self.precious}\nEOF"
            with self.subTest(shell=shell):
                self.assertIn("untracked", self.reason(cmd))
        unquoted = f"sh <<EOF\nrm -rf {self.precious}\nEOF"
        self.assertIn("untracked", self.reason(unquoted))
        tab_cmd = f"bash <<-'EOF'\n\trm -rf {self.precious}\n\tEOF"
        self.assertIn("untracked", self.reason(tab_cmd))

    def test_python_heredoc_real_delete_calls_still_caught(self) -> None:
        rmtree_cmd = f"python3 - <<'PY'\nimport shutil\nshutil.rmtree('{self.precious}')\nPY"
        self.assertIn("untracked", self.reason(rmtree_cmd))

        from_import_cmd = f"python3 - <<'PY'\nfrom shutil import rmtree\nrmtree('{self.precious}')\nPY"
        self.assertIn("untracked", self.reason(from_import_cmd))

        os_remove_cmd = f"python3 <<'PY'\nimport os\nos.remove('{self.precious}')\nPY"
        self.assertIn("untracked", self.reason(os_remove_cmd))

        os_unlink_cmd = f"python3 - <<'PY'\nimport os\nos.unlink('{self.precious}')\nPY"
        self.assertIn("untracked", self.reason(os_unlink_cmd))

        from_os_remove_cmd = f"python3 <<'PY'\nfrom os import remove\nremove('{self.precious}')\nPY"
        self.assertIn("untracked", self.reason(from_os_remove_cmd))

        from_os_unlink_cmd = f"python3 <<'PY'\nfrom os import unlink\nunlink('{self.precious}')\nPY"
        self.assertIn("untracked", self.reason(from_os_unlink_cmd))

        pathlib_cmd = f"python3 - <<'PY'\nfrom pathlib import Path\nPath('{self.precious}').unlink(missing_ok=True)\nPY"
        self.assertIn("untracked", self.reason(pathlib_cmd))

        dynamic_cmd = "python3 - <<'PY'\nimport shutil, sys\nshutil.rmtree(sys.argv[1])\nPY"
        self.assertIn("non-literal", self.reason(dynamic_cmd))

    def test_unquoted_delete_after_heredoc_is_still_caught(self) -> None:
        cmd = (
            "cat <<'EOF' > notes.txt\n"
            "rm -rf safe_text_only\n"
            "EOF\n"
            f"rm -rf {self.precious}"
        )
        reason = self.reason(cmd)
        self.assertIn("untracked", reason)
        self.assertIn("precious.txt", reason)

    def test_command_substitution_in_unquoted_heredoc_and_double_quotes_caught(self) -> None:
        unquoted_hd = f"cat <<EOF\n$(rm -rf {self.precious})\nEOF"
        self.assertIn("untracked", self.reason(unquoted_hd))

        quoted_hd = f"cat <<'EOF'\n$(rm -rf {self.precious})\nEOF"
        self.assertEqual("", self.reason(quoted_hd))

        dbl_quoted_sub = f'echo "$(rm -rf {self.precious})"'
        self.assertIn("untracked", self.reason(dbl_quoted_sub))

        sgl_quoted_sub = f"echo '$(rm -rf {self.precious})'"
        self.assertEqual("", self.reason(sgl_quoted_sub))

    def test_genuinely_unclosed_quote_with_delete_still_fails_closed(self) -> None:
        self.assertIn("unparsable delete", self.reason('rm -rf "unclosed'))

    def test_ansi_c_heredoc_delimiter_does_not_swallow_the_next_command(self) -> None:
        cmd = "cat <<$'EOF'\nhello\nEOF\nrm -f precious.txt"
        reason = self.reason(cmd)
        self.assertIn("untracked", reason)
        self.assertIn("precious.txt", reason)
        quoted = 'cat <<$"EOF"\nhello\nEOF\nrm -f precious.txt'
        quoted_reason = self.reason(quoted)
        self.assertIn("untracked", quoted_reason)
        self.assertIn("precious.txt", quoted_reason)

    def test_heredoc_piped_into_shell_or_python_is_scanned(self) -> None:
        shell_cmd = "cat <<'EOF' | bash\nrm -f precious.txt\nEOF"
        shell_reason = self.reason(shell_cmd)
        self.assertIn("untracked", shell_reason)
        self.assertIn("precious.txt", shell_reason)
        env_shell = "cat <<'EOF' | env bash\nrm -f precious.txt\nEOF"
        self.assertIn("precious.txt", self.reason(env_shell))
        python_cmd = "cat <<'EOF' | python3\nimport shutil; shutil.rmtree('precious.txt')\nEOF"
        python_reason = self.reason(python_cmd)
        self.assertIn("untracked", python_reason)
        self.assertIn("precious.txt", python_reason)
        env_python = "cat <<'EOF' | env python3\nimport shutil; shutil.rmtree('precious.txt')\nEOF"
        self.assertIn("precious.txt", self.reason(env_python))

    def test_cd_is_not_applied_when_the_shell_would_not(self) -> None:
        for cmd in (
            "cd /no/such/dir/zzz; rm -f precious.txt",
            "cd /no/such/dir/zzz || rm -f precious.txt",
            "cd /tmp | rm -f precious.txt",
        ):
            with self.subTest(cmd=cmd):
                reason = self.reason(cmd)
                self.assertIn("untracked", reason)
                self.assertIn("precious.txt", reason)

    def test_quote_split_and_ansi_c_command_names_are_refused(self) -> None:
        for cmd in (
            "r'm' -f precious.txt",
            "r\"m\" -f precious.txt",
            "$'r\\x6d' -f precious.txt",
        ):
            with self.subTest(cmd=cmd):
                reason = self.reason(cmd)
                self.assertIn("untracked", reason)
                self.assertIn("precious.txt", reason)

    def test_function_body_delete_is_refused(self) -> None:
        reason = self.reason("f() { rm -f precious.txt; }; f")
        self.assertIn("untracked", reason)
        self.assertIn("precious.txt", reason)

    def _write_only(self) -> None:
        (self.repo / "only.txt").write_text("only copy", encoding="utf-8")

    def test_review2_wrappers_eval_and_coproc_name_are_refused(self) -> None:
        self._write_only()
        for cmd in (
            "time rm -f only.txt",
            "time -p rm -f only.txt",
            "stdbuf -o0 rm -f only.txt",
            "stdbuf -o 0 rm -f only.txt",
            "coproc rm -f only.txt",
            "coproc worker { rm -f only.txt; }",
            "eval 'rm -f only.txt'",
            'eval "rm -f only.txt"',
        ):
            with self.subTest(cmd=cmd):
                reason = self.reason(cmd)
                self.assertIn("untracked", reason)
                self.assertIn("only.txt", reason)
        self.assertEqual("", self.reason("time echo ok"))
        self.assertEqual("", self.reason("eval 'echo ok'"))

    def test_review2_computed_command_head_is_refused(self) -> None:
        self._write_only()
        for cmd in (
            "x=rm; $x -f only.txt",
            "$(echo rm) -f only.txt",
        ):
            with self.subTest(cmd=cmd):
                self.assertIn("computed command head", self.reason(cmd))
        events = GUARD._parse_shell("$(echo rm) -f only.txt")
        commands = [payload for kind, payload in events if kind == "cmd"]
        self.assertTrue(any("echo rm" in sub for cmd in commands for sub in cmd.cmd_subs))
        # Directory expansion may be dynamic; a literal basename must not trip the head check.
        self.assertEqual("", self.reason('"$VENV/bin/python" -c "print(1)"'))
        caught = f'"$VENV/bin/python" -c "import os; os.remove(\'{self.precious}\')"'
        self.assertIn("untracked", self.reason(caught))
        self.assertNotIn("computed command head", self.reason(caught))

    def test_review2_shell_process_substitution_is_refused(self) -> None:
        for shell in ("sh", "bash", "zsh", "dash"):
            cmd = f"{shell} <(printf 'rm -f only.txt\\n')"
            with self.subTest(shell=shell):
                self.assertIn("shell process substitution", self.reason(cmd))
        self.assertEqual("", self.reason("bash -c 'echo hi'"))

    def test_review2_arithmetic_command_substitution_is_refused(self) -> None:
        self._write_only()
        for cmd in (
            "echo $(($(rm -f only.txt)))",
            'echo "$(($(rm -f only.txt)))"',
            "echo $((`rm -f only.txt`))",
        ):
            with self.subTest(cmd=cmd):
                reason = self.reason(cmd)
                self.assertIn("untracked", reason)
                self.assertIn("only.txt", reason)

    def test_review2_function_keyword_body_is_refused(self) -> None:
        self._write_only()
        for cmd in (
            "function f { rm -f only.txt; }; f",
            "function f() { rm -f only.txt; }; f",
        ):
            with self.subTest(cmd=cmd):
                reason = self.reason(cmd)
                self.assertIn("untracked", reason)
                self.assertIn("only.txt", reason)
        self.assertEqual("", self.reason("function f { echo ok; }; f"))

    def test_review2_brace_expansion_and_glob_cd_are_refused(self) -> None:
        brace = self.reason("rm {only,nope}.txt")
        self.assertIn("brace-expanded delete target", brace)
        self.assertIn("{only,nope}.txt", brace)
        ranged = self.reason("rm file{1..3}.txt")
        self.assertIn("brace-expanded delete target", ranged)
        glob_cd = self.reason("cd dir* && rm -f precious.txt")
        self.assertIn("cd to a computed path before a delete", glob_cd)
        self.assertEqual("", self.reason("cd dir* && echo ok"))

    def test_review2_python_getattr_delete_is_refused(self) -> None:
        cmd = "python3 -c \"import os; getattr(os, 'remove')('only.txt')\""
        self.assertIn("indirect Python delete via getattr", self.reason(cmd))
        for attr in ("unlink", "rmtree", "rmdir"):
            with self.subTest(attr=attr):
                inner = f"python3 -c \"import os; getattr(os, '{attr}')('only.txt')\""
                self.assertIn("indirect Python delete via getattr", self.reason(inner))
        self.assertEqual("", self.reason("python3 -c \"import os; getattr(os, 'getcwd')()\""))

    def test_review3_gnu_time_stdbuf_end_opts_and_busybox_are_refused(self) -> None:
        self._write_only()
        refused = (
            "/usr/bin/time -v rm -f only.txt",
            "command time -v rm -f only.txt",
            "/usr/bin/time -o /tmp/t -- rm -f only.txt",
            "/usr/bin/time --verbose rm -f only.txt",
            "/usr/bin/time --output=/tmp/t rm -f only.txt",
            "/usr/bin/time --output /tmp/t rm -f only.txt",
            "/usr/bin/time -f %e rm -f only.txt",
            "/usr/bin/time --format=%e rm -f only.txt",
            "/usr/bin/time --format %e -- rm -f only.txt",
            "/usr/bin/time -a -q -p rm -f only.txt",
            "stdbuf -o0 -- rm -f only.txt",
            "stdbuf --output=L -- rm -f only.txt",
            "busybox rm -f only.txt",
            "busybox -- rm -f only.txt",
        )
        for cmd in refused:
            with self.subTest(cmd=cmd):
                reason = self.reason(cmd)
                self.assertIn("untracked", reason)
                self.assertIn("only.txt", reason)
        for cmd in (
            "time echo ok",
            "/usr/bin/time -v echo ok",
            "stdbuf -o0 -- echo ok",
            "busybox echo ok",
        ):
            with self.subTest(cmd=cmd):
                self.assertEqual("", self.reason(cmd))

    def test_review3_source_and_dot_process_substitution_are_refused(self) -> None:
        for cmd in (
            "source <(printf 'rm -f only.txt\\n')",
            ". <(printf 'rm -f only.txt\\n')",
        ):
            with self.subTest(cmd=cmd):
                self.assertIn("shell process substitution", self.reason(cmd))
        self.assertEqual("", self.reason("source ./env.sh"))
        self.assertEqual("", self.reason(". ./env.sh"))

    def test_review4_getopt_long_prefixes_and_ash_shells_are_refused(self) -> None:
        self._write_only()
        refused = (
            "/usr/bin/time --verb rm -f only.txt",
            "/usr/bin/time --out=/tmp/t rm -f only.txt",
            "/usr/bin/time --out /tmp/t rm -f only.txt",
            "/usr/bin/time --form=%e rm -f only.txt",
            "/usr/bin/time --qui rm -f only.txt",
            "/usr/bin/time --por rm -f only.txt",
            "/usr/bin/time --app rm -f only.txt",
            "/usr/bin/time -l rm -f only.txt",
            "stdbuf --out=0 rm -f only.txt",
            "stdbuf --out=0 -- rm -f only.txt",
            "stdbuf --err=0 rm -f only.txt",
            "stdbuf --in=0 rm -f only.txt",
            "busybox ash -c 'rm -f only.txt'",
            "busybox ksh -c 'rm -f only.txt'",
            "busybox mksh -c 'rm -f only.txt'",
        )
        for cmd in refused:
            with self.subTest(cmd=cmd):
                reason = self.reason(cmd)
                self.assertIn("untracked", reason)
                self.assertIn("only.txt", reason)
        for cmd in (
            "/usr/bin/time --verb echo ok",
            "stdbuf --out=0 echo ok",
            "/usr/bin/time --help rm -f only.txt",
            "busybox ash -c 'echo ok'",
            "busybox ksh -c 'echo ok'",
            "busybox mksh -c 'echo ok'",
        ):
            with self.subTest(cmd=cmd):
                self.assertEqual("", self.reason(cmd))

    def test_review4_match_long_option_unique_prefix(self) -> None:
        match = GUARD._match_long_option
        time_flags = ("--verbose", "--portability", "--append", "--quiet")
        time_values = ("--output", "--format")
        self.assertEqual("flag", match("--verb", time_flags, time_values))
        self.assertEqual("flag", match("--verbose", time_flags, time_values))
        self.assertEqual("flag", match("--por", time_flags, time_values))
        self.assertEqual("flag", match("--app", time_flags, time_values))
        self.assertEqual("flag", match("--qui", time_flags, time_values))
        self.assertEqual("flag", match("--out=/tmp/t", time_flags, time_values))
        self.assertEqual("value", match("--out", time_flags, time_values))
        self.assertEqual("value", match("--output", time_flags, time_values))
        self.assertEqual("flag", match("--form=%e", time_flags, time_values))
        self.assertEqual("value", match("--format", time_flags, time_values))
        self.assertIsNone(match("--help", time_flags, time_values))
        self.assertIsNone(match("--", time_flags, time_values))
        self.assertIsNone(match("-v", time_flags, time_values))
        self.assertIsNone(match("--o", ("--output", "--outfile"), ()))
        stdbuf_values = ("--input", "--output", "--error")
        self.assertEqual("flag", match("--out=0", (), stdbuf_values))
        self.assertEqual("flag", match("--err=0", (), stdbuf_values))
        self.assertEqual("flag", match("--in=0", (), stdbuf_values))
        self.assertEqual("value", match("--out", (), stdbuf_values))
        self.assertEqual("value", match("--error", (), stdbuf_values))

    def _py(self, source: str) -> str:
        return "python3 - <<'PY'\n" + source + "\nPY"

    def test_issue_213_source_and_dot_stdin_heredoc_is_a_shell_script(self) -> None:
        """``source`` / ``.`` of stdin runs the attached heredoc as a shell script.

        ``/dev/stdin``, ``/proc/self/fd/0``, and ``/dev/fd/0`` are the script.
        A heredoc on ``source ./file`` is stdin data for that file, not the script.
        """
        self._write_only()
        refused = (
            "source /dev/stdin <<'EOF'\nrm -f only.txt\nEOF",
            ". /dev/stdin <<'EOF'\nrm -f only.txt\nEOF",
            "source /proc/self/fd/0 <<'EOF'\nrm -f only.txt\nEOF",
            ". /proc/self/fd/0 <<'EOF'\nrm -f only.txt\nEOF",
            "source /dev/fd/0 <<'EOF'\nrm -f only.txt\nEOF",
            ". /dev/fd/0 <<'EOF'\nrm -f only.txt\nEOF",
            "source -- /dev/stdin <<'EOF'\nrm -f only.txt\nEOF",
            ". -- /dev/stdin <<'EOF'\nrm -f only.txt\nEOF",
            "source /dev//stdin <<'EOF'\nrm -f only.txt\nEOF",
            "source /dev/stdin <<EOF\nrm -f only.txt\nEOF",
            "bash -c \"source /dev/stdin <<'EOF'\nrm -f only.txt\nEOF\"",
            ". /dev/stdin <<-EOF\n\trm -f only.txt\n\tEOF",
            "source /dev/stdin <<< 'rm -f only.txt'",
            ". /dev/stdin <<< 'rm -f only.txt'",
            "cat <<'EOF' | source /dev/stdin\nrm -f only.txt\nEOF",
            "cat <<'EOF' | . /dev/fd/0\nrm -f only.txt\nEOF",
            "source /dev/stdin <<'EOF'\npython3 -c \"import os; os.remove('only.txt')\"\nEOF",
            "cd \"$T\" && source /dev/stdin <<'EOF'\nrm -f foo\nEOF",
        )
        for cmd in refused:
            with self.subTest(cmd=cmd):
                reason = self.reason(cmd)
                self.assertNotEqual("", reason)
                if "cd \"$T\"" in cmd:
                    self.assertIn("cd to a computed path before a delete", reason)
                else:
                    self.assertIn("untracked", reason)
                    self.assertIn("only.txt", reason)
        absolute = f"cd \"$T\" && source /dev/stdin <<'EOF'\nrm -f {self.precious}\nEOF"
        absolute_reason = self.reason(absolute)
        self.assertIn("untracked", absolute_reason)
        self.assertIn("precious.txt", absolute_reason)
        self.assertNotIn("cd to a computed path", absolute_reason)
        for cmd in (
            "source /dev/stdin <<'EOF'\necho ok\nEOF",
            ". /dev/stdin <<'EOF'\necho ok\nEOF",
            "source /dev/stdin <<'EOF'\necho rm -f only.txt\nEOF",
            ". /proc/self/fd/0 <<'EOF'\nprintf 'ok\\n'\nEOF",
            "source /dev/stdin <<< 'echo ok'",
            "source ./env.sh <<'EOF'\nrm -f only.txt\nEOF",
            ". ./env.sh <<'EOF'\nrm -f only.txt\nEOF",
            "cat <<'EOF' | source ./env.sh\nrm -f only.txt\nEOF",
            "source ./env.sh <<< 'rm -f only.txt'",
        ):
            with self.subTest(cmd=cmd):
                self.assertEqual("", self.reason(cmd))

    def test_issue_213_folded_getattr_delete_names_are_refused(self) -> None:
        """Constant-folded ``getattr`` names are delete checks, not only ``ast.Constant``.

        A folded ``remove``/``unlink``/``rmtree``/``rmdir`` is refused on any object.
        An unfoldable name is refused when the receiver is ``os``, ``shutil``,
        ``pathlib``, or ``Path(...)`` (including import aliases). A bare
        ``getattr(obj, key)`` stays allowed, and a folded benign name such as
        ``getcwd`` stays allowed.
        """
        refused = (
            "import os\ngetattr(os, 'rem' + 'ove')('only.txt')",
            "import os\ngetattr(os, 'rem' 'ove')('only.txt')",
            "import os\ngetattr(os, f\"{'rem'}{'ove'}\")('only.txt')",
            "import os\ngetattr(os, ''.join(['rem', 'ove']))('only.txt')",
            "import os\ngetattr(os, str.join('', ['rem', 'ove']))('only.txt')",
            "import os\ngetattr(os, 'un' + 'link')('only.txt')",
            "import os\ngetattr(os, 'rm' + 'dir')('only.txt')",
            "import shutil\ngetattr(shutil, 'rm' + 'tree')('only.txt')",
            "obj = object()\ngetattr(obj, 'rem' + 'ove')('only.txt')",
            "import os as operating_system\ngetattr(operating_system, 'rem' + 'ove')('only.txt')",
            "import os\nname = 'remove'\ngetattr(os, name)('only.txt')",
            "import os\nname = 'getcwd'\ngetattr(os, name)()",
            "import shutil\nname = 'copy'\ngetattr(shutil, name)('a', 'b')",
            "import pathlib\nname = 'Path'\ngetattr(pathlib, name)",
            "from pathlib import Path\nname = 'unlink'\ngetattr(Path('only.txt'), name)()",
            "from pathlib import Path\ngetattr(Path('only.txt'), 'un' + 'link')()",
            "import os\ngetattr(os, '{}'.format('remove'))('only.txt')",
            "obj = object()\ngetattr(obj, '{}'.format('remove'))('only.txt')",
            "obj = object()\ngetattr(obj, '%s%s' % ('rem', 'ove'))('only.txt')",
        )
        for source in refused:
            with self.subTest(source=source):
                self.assertIn("indirect Python delete via getattr", self.reason(self._py(source)))
        allowed = (
            "import os\ngetattr(os, 'getcwd')()",
            "import os\ngetattr(os, 'get' + 'cwd')()",
            "import os\ngetattr(os, f\"{'getcwd'}\")()",
            "import os\ngetattr(os, ''.join(['get', 'cwd']))()",
            "from pathlib import Path\ngetattr(Path('only.txt'), 'exists')()",
            "from pathlib import Path\ngetattr(Path('only.txt'), 'name')",
            "obj = object()\nkey = 'remove'\ngetattr(obj, key)",
            "obj = object()\ngetattr(obj, obj.__class__.__name__)",
        )
        for source in allowed:
            with self.subTest(source=source):
                self.assertEqual("", self.reason(self._py(source)))

    def test_issue_213_quoted_braces_are_literal_delete_targets(self) -> None:
        """Quoted ``{a,b}`` is the literal filename. Unquoted braces still expand."""
        literal = self.repo / "{only,nope}.txt"
        literal.write_text("only copy", encoding="utf-8")
        ranged = self.repo / "file{1..3}.txt"
        ranged.write_text("only copy", encoding="utf-8")
        quoted = (
            "rm -f '{only,nope}.txt'",
            'rm -f "{only,nope}.txt"',
            r"rm -f \{only,nope\}.txt",
            r"rm -f $'{only,nope}.txt'",
            "rm -f -- '{only,nope}.txt'",
            "rm -f '{only,nope}'.txt",
            'rm -f {"only,nope"}.txt',
            "rm -f 'file{1..3}.txt'",
            r"rm -f file\{1..3\}.txt",
        )
        for cmd in quoted:
            with self.subTest(cmd=cmd):
                reason = self.reason(cmd)
                self.assertNotIn("brace-expanded delete target", reason)
                self.assertIn("untracked", reason)
        events = GUARD._parse_shell("rm -f '{only,nope}.txt'")
        command = next(payload for kind, payload in events if kind == "cmd")
        self.assertEqual("{only,nope}.txt", command.words[-1])
        self.assertEqual("1" * len(command.words[-1]), command.word_masks[-1])
        partial = GUARD._parse_shell('rm -f {"only,nope"}.txt')
        partial_cmd = next(payload for kind, payload in partial if kind == "cmd")
        word = partial_cmd.words[-1]
        mask = partial_cmd.word_masks[-1]
        self.assertEqual("{only,nope}.txt", word)
        self.assertEqual("1", mask[word.index(",")])
        self.assertEqual("0", mask[0])
        for cmd in (
            "rm -f {only,nope}.txt",
            "rm {only,nope}.txt",
            "rm -f file{1..3}.txt",
            'rm -f {only,"nope"}.txt',
            "rm -f {only,nope}.txt '{only,nope}.txt'",
        ):
            with self.subTest(cmd=cmd):
                reason = self.reason(cmd)
                self.assertIn("brace-expanded delete target", reason)
        absent = self.reason("rm -f '{does-not-exist,either}.txt'")
        self.assertEqual("", absent)

    def test_issue_213_command_sub_head_boundary(self) -> None:
        """Literal ``$(echo ...)`` / ``$(printf ...)`` heads are visible only when safe.

        Allowed: one ``echo`` or ``printf`` with a single literal operand whose
        printed word is one token and is not a delete, shell, interpreter, or
        wrapper (``$(echo ls)``, ``$(printf echo)``, ``$(printf 'ls')``).
        The inner script must not contain another command, a delete, ``eval``,
        a computed head, or a redirection.

        Still refused as a computed command head:
        ``$(echo rm)``, ``$(printf 'rm')``, ``$(printf '%s%s' r m)``,
        ``$(echo r; echo m)``, ``$(echo /bin/rm)``, and ``$(echo bash)``.
        """
        self._write_only()
        for cmd in (
            "$(echo ls)",
            "$(echo ls) -la",
            "$(echo 'ls') -la",
            "$( printf echo ) hello",
            "$(printf 'echo') hello",
            "$(printf echo) rm -f only.txt",
            "`echo ls`",
            "`printf echo` ok",
            "$(echo /bin/ls) -la",
            "$(echo cat) only.txt",
        ):
            with self.subTest(cmd=cmd):
                self.assertEqual("", self.reason(cmd))
        refused = (
            "$(echo rm) -f only.txt",
            "$(echo 'rm') -f only.txt",
            "$(printf 'rm') -f only.txt",
            "$(printf rm) -f only.txt",
            "$(printf '%s%s' r m) -f only.txt",
            "$(printf '%s' rm) -f only.txt",
            "$(echo r; echo m) -f only.txt",
            "$(echo r && echo m) -f only.txt",
            "$(echo /bin/rm) -f only.txt",
            "`echo rm` -f only.txt",
            "`printf '%s%s' r m` -f only.txt",
            "$(echo ls; rm -f only.txt)",
            "$(rm -f only.txt; echo ls)",
            "$(echo ls >/tmp/ce-delete-guard-213)",
            "$(echo bash) -c 'rm -f only.txt'",
            "$(echo python3) -c \"import os; os.remove('only.txt')\"",
            "$(echo env) rm -f only.txt",
            "$(echo unlink) only.txt",
            "$(echo mv) only.txt /tmp/ce-delete-guard-213-dest",
            "x=rm; $x -f only.txt",
        )
        for cmd in refused:
            with self.subTest(cmd=cmd):
                self.assertIn("computed command head", self.reason(cmd))

    def test_review1_source_stdin_slashes_relative_cwd_and_computed_operand(self) -> None:
        """``source`` / ``.`` of stdin keeps working for normalized and relative paths.

        Leading extra slashes collapse (``//dev/stdin``). ``/proc/thread-self/fd/0``
        is stdin. A relative operand resolves against the tracked cwd. A ``$`` or
        backtick in the operand, with a heredoc, here-string, or piped heredoc,
        is refused. ``source ./env.sh`` still does not run its heredoc as a script.
        """
        self._write_only()
        precious = str(self.precious)
        refused_here = (
            "source //dev/stdin <<'EOF'\nrm -f only.txt\nEOF",
            ". //dev/stdin <<'EOF'\nrm -f only.txt\nEOF",
            "source ///dev/stdin <<'EOF'\nrm -f only.txt\nEOF",
            "source //proc/self/fd/0 <<'EOF'\nrm -f only.txt\nEOF",
            ". //dev/fd/0 <<'EOF'\nrm -f only.txt\nEOF",
            "source /proc/thread-self/fd/0 <<'EOF'\nrm -f only.txt\nEOF",
            ". /proc/thread-self/fd/0 <<'EOF'\nrm -f only.txt\nEOF",
            "source //proc/thread-self/fd/0 <<'EOF'\nrm -f only.txt\nEOF",
            "source /proc/thread-self/fd/0 <<< 'rm -f only.txt'",
            f"cd /dev && source stdin <<'EOF'\nrm -f {precious}\nEOF",
            f"cd /dev && . stdin <<'EOF'\nrm -f {precious}\nEOF",
            f"cd /dev && source ./stdin <<'EOF'\nrm -f {precious}\nEOF",
            f"cd /dev/fd && source 0 <<'EOF'\nrm -f {precious}\nEOF",
            f"cd /dev/fd && . 0 <<< 'rm -f {precious}'",
            f"cd / && source dev/stdin <<'EOF'\nrm -f {precious}\nEOF",
            f"cd / && . dev/fd/0 <<'EOF'\nrm -f {precious}\nEOF",
            f"cd /proc && source self/fd/0 <<'EOF'\nrm -f {precious}\nEOF",
            f"cd /proc && source thread-self/fd/0 <<'EOF'\nrm -f {precious}\nEOF",
            f"cd /dev && source ../proc/self/fd/0 <<'EOF'\nrm -f {precious}\nEOF",
            f"cd / && cat <<'EOF' | source dev/stdin\nrm -f {precious}\nEOF",
            f"cd /dev/fd && cat <<'EOF' | . 0\nrm -f {precious}\nEOF",
        )
        for cmd in refused_here:
            with self.subTest(cmd=cmd):
                reason = self.reason(cmd)
                self.assertIn("untracked", reason)
                if precious in cmd:
                    self.assertIn("precious.txt", reason)
                else:
                    self.assertIn("only.txt", reason)
        computed = (
            "source /proc/$$/fd/0 <<'EOF'\nrm -f only.txt\nEOF",
            ". /proc/$$/fd/0 <<'EOF'\nrm -f only.txt\nEOF",
            "source /proc/$$/fd/0 <<< 'rm -f only.txt'",
            "source /proc/`echo self`/fd/0 <<'EOF'\nrm -f only.txt\nEOF",
            "cat <<'EOF' | source /proc/$$/fd/0\nrm -f only.txt\nEOF",
            "cat <<'EOF' | . /dev/`echo fd`/0\nrm -f only.txt\nEOF",
        )
        for cmd in computed:
            with self.subTest(cmd=cmd):
                reason = self.reason(cmd)
                self.assertNotEqual("", reason)
                self.assertTrue(
                    "cannot tell" in reason or "only.txt" in reason,
                    reason,
                )
        for cmd in (
            "source ./env.sh <<'EOF'\nrm -f only.txt\nEOF",
            ". ./env.sh <<'EOF'\nrm -f only.txt\nEOF",
            f"cd / && source ./env.sh <<'EOF'\nrm -f {precious}\nEOF",
            f"cd /tmp && source env.sh <<'EOF'\nrm -f {precious}\nEOF",
            "source stdin <<'EOF'\nrm -f only.txt\nEOF",
            "cd /dev && source ./env.sh <<'EOF'\nrm -f only.txt\nEOF",
        ):
            with self.subTest(cmd=cmd):
                self.assertEqual("", self.reason(cmd))

    def test_review1_qualified_and_aliased_getattr_and_removedirs(self) -> None:
        """``builtins.getattr`` and import aliases are the same delete as ``getattr``.

        ``removedirs`` is a delete name, including through those aliases.
        A folded benign name such as ``getcwd`` stays allowed.
        """
        refused = (
            "import os\nbuiltins.getattr(os, 'rem' + 'ove')('only.txt')",
            "import os\n__builtins__.getattr(os, 'rem' + 'ove')('only.txt')",
            "import builtins as b\nimport os\nb.getattr(os, 'rem' + 'ove')('only.txt')",
            "from builtins import getattr as ga\nimport os\nga(os, 'rem' + 'ove')('only.txt')",
            "import os\nbuiltins.getattr(os, 'remove')('only.txt')",
            "from builtins import getattr as ga\nimport os\nga(os, 'unlink')('only.txt')",
            "import os\ngetattr(os, 'removedirs')('only.txt')",
            "import os\ngetattr(os, 'remove' + 'dirs')('only.txt')",
            "import os\nbuiltins.getattr(os, 'removedirs')('only.txt')",
            "from builtins import getattr as ga\nimport os\nga(os, 'removedirs')('only.txt')",
            "obj = object()\n__builtins__.getattr(obj, 'removedirs')('only.txt')",
        )
        for source in refused:
            with self.subTest(source=source):
                self.assertIn("indirect Python delete via getattr", self.reason(self._py(source)))
        allowed = (
            "import os\nbuiltins.getattr(os, 'getcwd')()",
            "import os\n__builtins__.getattr(os, 'get' + 'cwd')()",
            "import builtins as b\nimport os\nb.getattr(os, 'getcwd')()",
            "from builtins import getattr as ga\nimport os\nga(os, 'getcwd')()",
            "from builtins import open as ga\nimport os\nga('only.txt')",
            "obj = object()\nkey = 'removedirs'\ngetattr(obj, key)",
        )
        for source in allowed:
            with self.subTest(source=source):
                self.assertEqual("", self.reason(self._py(source)))

    def test_review1_command_sub_head_allowlist(self) -> None:
        """A literal ``$(echo ...)`` head is visible only for read-only commands.

        ``perl``, ``ruby``, and ``node`` stay computed heads. ``ls`` and ``echo``
        stay visible.
        """
        self._write_only()
        allowed = (
            "$(echo ls)",
            "$(printf echo)",
            "$(echo pwd)",
            "$(echo date)",
            "$(echo true)",
            "$(echo false)",
            "$(echo uname)",
            "$(echo whoami)",
            "$(echo id)",
            "$(echo cat) only.txt",
            "$(echo head) only.txt",
            "$(echo tail) only.txt",
            "$(echo wc) only.txt",
            "$(echo grep) only.txt",
            "$(echo rg) only.txt",
            "$(echo /bin/ls) -la",
        )
        for cmd in allowed:
            with self.subTest(cmd=cmd):
                self.assertEqual("", self.reason(cmd))
        refused = (
            "$(echo perl) -e 'unlink(\"only.txt\")'",
            "$(echo ruby)",
            "$(echo node)",
            "$(echo perl)",
            "$(echo /usr/bin/perl) -e 'unlink(\"only.txt\")'",
        )
        for cmd in refused:
            with self.subTest(cmd=cmd):
                self.assertIn("computed command head", self.reason(cmd))

    def test_review1_eval_heredoc_and_here_string_are_shell(self) -> None:
        """A heredoc or here-string on ``eval`` is a shell script."""
        self._write_only()
        refused = (
            "eval 'bash' <<'EOF'\nrm -f only.txt\nEOF",
            "eval \"source /dev/stdin\" <<'EOF'\nrm -f only.txt\nEOF",
            "eval 'bash' <<< 'rm -f only.txt'",
            "eval 'sh' <<'EOF'\nrm -f only.txt\nEOF",
            "eval <<'EOF'\nrm -f only.txt\nEOF",
        )
        for cmd in refused:
            with self.subTest(cmd=cmd):
                reason = self.reason(cmd)
                self.assertIn("untracked", reason)
                self.assertIn("only.txt", reason)
        for cmd in (
            "eval 'bash' <<'EOF'\necho ok\nEOF",
            "eval \"source /dev/stdin\" <<'EOF'\necho ok\nEOF",
            "eval 'bash' <<< 'echo ok'",
            "eval 'echo ok'",
        ):
            with self.subTest(cmd=cmd):
                self.assertEqual("", self.reason(cmd))

    def test_review1_echo_printf_pipe_into_shell_or_source_stdin(self) -> None:
        """A literal ``echo`` / ``printf`` piped into a shell or stdin ``source`` is the script."""
        self._write_only()
        precious = str(self.precious)
        refused = (
            "echo 'rm -f only.txt' | bash",
            "echo 'rm -f only.txt' | sh",
            "printf 'rm -f only.txt' | bash",
            "echo 'rm -f only.txt' | source /dev/stdin",
            "echo 'rm -f only.txt' | . /dev/stdin",
            "printf 'rm -f only.txt' | source /dev/fd/0",
            "echo 'rm -f only.txt' | source //dev/stdin",
            "printf '%s' 'rm -f only.txt' | bash",
            "printf '%s\\n' 'rm -f only.txt' | bash",
            "echo rm -f only.txt | bash",
            f"cd /dev && echo 'rm -f {precious}' | source stdin",
            f"echo 'rm -f {precious}' | . /proc/self/fd/0",
        )
        for cmd in refused:
            with self.subTest(cmd=cmd):
                reason = self.reason(cmd)
                self.assertIn("untracked", reason)
                if precious in cmd:
                    self.assertIn("precious.txt", reason)
                else:
                    self.assertIn("only.txt", reason)
        for cmd in (
            "echo 'hello' | bash",
            "echo 'echo ok' | bash",
            "printf 'echo ok' | bash",
            "echo 'hello' | source /dev/stdin",
            "echo 'echo ok' | . /dev/stdin",
            "echo 'rm -f only.txt' | cat",
            "printf 'rm -f only.txt' | cat",
        ):
            with self.subTest(cmd=cmd):
                self.assertEqual("", self.reason(cmd))


if __name__ == "__main__":
    unittest.main()
