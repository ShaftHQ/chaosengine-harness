"""#240: delete guard gh --body-file hint UX and delegation canary/stall/xdist docs."""

from __future__ import annotations

import importlib.util
import os
import re
import shutil
import subprocess  # nosec B404 - fixed git argv in temp fixtures.
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
    spec.loader.exec_module(module)
    return module


GUARD = _load("chaos_engine_delete_guard_240", ROOT / "runtime" / "delete_guard.py")


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


# assertion-justified: Issue #240 FR-3/SC-2 step-back removes heredoc-in-paren parser tests in favor of fail-closed --body-file hint tests.
class DeleteGuardGhHeredoc240Test(unittest.TestCase):
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

    def reason(self, command: str) -> str:
        return GUARD.block_reason(command, self.repo, self.repo)

    # --- Positive cases: --body-file allowed; benign arithmetic shift allowed ---

    def test_gh_body_file_commands_are_allowed(self) -> None:
        cases = (
            'gh issue create --repo o/r --title "t" --body-file /tmp/body.md',
            'gh pr create --title "t" --body-file /tmp/pr-body.md',
            "gh issue comment 240 --body-file /tmp/comment.md",
            'gh -R o/r pr edit 240 --body-file /tmp/edit.md',
        )
        for cmd in cases:
            with self.subTest(cmd=cmd):
                self.assertEqual("", self.reason(cmd))

    def test_benign_array_bitshift_in_cmd_sub_is_allowed(self) -> None:
        cases = (
            'echo "$(a[1<<2]=5; echo "rm -rf")"',
            "echo \"$(a[1<<2]=5; echo 'rm -rf')\"",
        )
        for cmd in cases:
            with self.subTest(cmd=cmd):
                self.assertEqual("", self.reason(cmd))

    # --- Unparsable gh commands: fail closed WITH explicit --body-file hint ---

    def test_unparsable_gh_heredoc_and_quote_commands_refuse_with_body_file_hint(self) -> None:
        cases = (
            (
                'gh issue create --repo o/r --title "t" --body "$(cat <<\'EOF\'\n'
                "Use `rm -rf` carefully; don't break\n"
                "EOF\n"
                ')"'
            ),
            (
                'gh pr create --title "t" --body "$(cat <<\'EOF\'\n'
                "don't run rm -rf /\n"
                "EOF\n"
                ')"'
            ),
            (
                'gh issue comment 240 --body "$(cat <<\'EOF\'\n'
                "don't run rm -rf /\n"
                "EOF\n"
                ')"'
            ),
            (
                'gh pr comment 240 --body "$(cat <<\'EOF\'\n'
                "don't run rm -rf /\n"
                "EOF\n"
                ')"'
            ),
            (
                'gh issue edit 240 --body "$(cat <<\'EOF\'\n'
                "don't run rm -rf /\n"
                "EOF\n"
                ')"'
            ),
            (
                'gh pr edit 240 --body "$(cat <<\'EOF\'\n'
                "don't run rm -rf /\n"
                "EOF\n"
                ')"'
            ),
            (
                'gh -R owner/repo issue create --title "t" --body "$(cat <<\'EOF\'\n'
                "don't run rm -rf /\n"
                "EOF\n"
                ')"'
            ),
            (
                'GH_HOST=github.com gh --repo o/r pr create --title "t" --body "$(cat <<\'EOF\'\n'
                "don't run rm -rf /\n"
                "EOF\n"
                ')"'
            ),
            (
                'gh --repo=o/r issue comment 240 --body "$(cat <<\'EOF\'\n'
                "don't run rm -rf /\n"
                "EOF\n"
                ')"'
            ),
            'gh issue create --title "t" --body "don\'t run rm -rf precious.txt',
        )
        for cmd in cases:
            with self.subTest(cmd=cmd):
                reason = self.reason(cmd)
                self.assertIn("unparsable delete:", reason)
                self.assertIn("--body-file", reason)

    def test_non_gh_unparsable_delete_refuses_without_body_file_hint(self) -> None:
        cases = (
            'rm -rf "$(unclosed',
            'rm -rf "unterminated',
            'echo "$(cat <<\'EOF\'\ndon\'t run rm -rf precious.txt\nEOF\n)"',
        )
        for cmd in cases:
            with self.subTest(cmd=cmd):
                reason = self.reason(cmd)
                self.assertIn("unparsable delete:", reason)
                self.assertNotIn("--body-file", reason)

    def test_review3_quoted_gh_on_non_gh_command_no_body_file_hint(self) -> None:
        cases = (
            'echo "gh issue create"; rm -rf "$(unclosed',
            "echo 'gh pr edit 1'; rm -rf \"$(unclosed",
        )
        for cmd in cases:
            with self.subTest(cmd=cmd):
                reason = self.reason(cmd)
                self.assertIn("unparsable delete:", reason)
                self.assertNotIn("--body-file", reason)

    def test_review3_many_gh_flags_linear_no_body_file_hint(self) -> None:
        cmd = "gh -a " * 8000 + 'rm -rf "$(unclosed'
        started = time.monotonic()
        reason = self.reason(cmd)
        elapsed = time.monotonic() - started
        self.assertIn("unparsable delete:", reason)
        self.assertNotIn("--body-file", reason)
        self.assertLess(elapsed, 0.5)

    def test_review3_positive_gh_body_commands_emit_body_file_hint(self) -> None:
        cases = (
            'gh issue create --title "t" --body "don\'t run rm -rf precious.txt',
            'FOO=1 gh -R owner/repo pr comment 12 --body "$(unclosed',
            'cd /tmp && /usr/bin/gh issue edit 5 --body "$(unclosed',
            'gh --repo=owner/repo pr create --body "$(unclosed',
        )
        for cmd in cases:
            with self.subTest(cmd=cmd):
                reason = self.reason(cmd)
                self.assertIn("unparsable delete:", reason)
                self.assertIn("--body-file", reason)

    def test_gh_body_cmd_regex_stays_linear_on_many_flags(self) -> None:
        cmd = "gh " + " ".join(f"-f{i}" for i in range(60)) + " status"
        started = time.monotonic()
        matched = GUARD._is_gh_body_command(cmd)
        elapsed = time.monotonic() - started
        self.assertFalse(matched)
        self.assertLess(elapsed, 0.5)

    # --- Adversarial security cases: ALL MUST BE REFUSED ---

    def test_adversarial_direct_command_substitution_delete_refused(self) -> None:
        cmd = f'gh issue create --title "t" --body "$(rm -rf {self.precious})"'
        reason = self.reason(cmd)
        self.assertIn("untracked", reason)
        self.assertIn("precious.txt", reason)

    def test_adversarial_chained_delete_after_heredoc_refused(self) -> None:
        for sep in (";", "&&", "|"):
            cmd = (
                'gh issue create --title "t" --body "$(cat <<\'EOF\'\n'
                "hi\n"
                "EOF\n"
                f')" {sep} rm -rf {self.precious}'
            )
            with self.subTest(sep=sep):
                reason = self.reason(cmd)
                self.assertIn("untracked", reason)
                self.assertIn("precious.txt", reason)

    def test_adversarial_unquoted_heredoc_command_substitution_delete_refused(self) -> None:
        cases = (
            (
                'gh issue create --title "t" --body "$(cat <<EOF\n'
                f"$(rm -rf {self.precious})\n"
                "EOF\n"
                ')"'
            ),
            (
                'gh issue create --title "t" --body "$(cat <<EOF\n'
                f"`rm -rf {self.precious}`\n"
                "EOF\n"
                ')"'
            ),
        )
        for cmd in cases:
            with self.subTest(cmd=cmd):
                reason = self.reason(cmd)
                self.assertIn("untracked", reason)
                self.assertIn("precious.txt", reason)

    def test_adversarial_executing_heredoc_and_title_delete_refused(self) -> None:
        cases = (
            (
                'gh issue create --title "t" --body "$(bash <<\'EOF\'\n'
                f"rm -rf {self.precious}\n"
                "EOF\n"
                ')"'
            ),
            (
                'gh issue create --title "t" --body "$(cat <<\'EOF\' | sh\n'
                f"rm -rf {self.precious}\n"
                "EOF\n"
                ')"'
            ),
            f'gh issue create --title "$(rm -rf {self.precious})" --body "ok"',
        )
        for cmd in cases:
            with self.subTest(cmd=cmd):
                reason = self.reason(cmd)
                self.assertIn("untracked", reason)
                self.assertIn("precious.txt", reason)

    def test_adversarial_parser_desync_bypasses_all_refused(self) -> None:
        cases = (
            # Review 1 F1: nested $(...) heredoc scoping
            (
                'gh issue create --title "t" --body "$(true <<\'OUTER\' $(cat <<\'INNER\'\n'
                "don't\n"
                "OUTER\n"
                "INNER\n"
                ")\n"
                ")\n"
                "OUTER\n"
                f"rm -rf {self.precious}\n"
                ')"'
            ),
            # Review 1 F1: nested <(...) and >(...) process substitution heredoc scoping
            (
                'gh issue create --title "t" --body "$(true <<\'OUTER\' <(cat <<\'INNER\'\n'
                "don't\n"
                "OUTER\n"
                "INNER\n"
                ")\n"
                ")\n"
                "OUTER\n"
                f"rm -rf {self.precious}\n"
                ')"'
            ),
            (
                'gh issue create --title "t" --body "$(true <<\'OUTER\' >(cat <<\'INNER\'\n'
                "don't\n"
                "OUTER\n"
                "INNER\n"
                ")\n"
                ")\n"
                "OUTER\n"
                f"rm -rf {self.precious}\n"
                ')"'
            ),
            # Review 2 F1: non-comment #<<'EOF' after ')' inside $(...)
            (
                'gh issue create --title "t" --body "$( (true)#<<\'EOF\'\n'
                f')"; rm -rf {self.precious}; exit 0 # "\n'
                "EOF\n"
                ')"'
            ),
            # Review 2 F2: arithmetic array subscript 1<<EOF bitshift vs heredoc desync
            (
                'gh issue create --title "t" --body "$(a[1<<EOF ]=0\n'
                f')"; rm -rf {self.precious}; exit 0\n'
                "EOF\n"
                ')"'
            ),
        )
        for cmd in cases:
            with self.subTest(cmd=cmd):
                reason = self.reason(cmd)
                self.assertNotEqual("", reason)
                self.assertIn("Delete guard", reason)


class DelegationCanaryStallXdistDoc240Test(unittest.TestCase):
    def test_delegation_documents_canary_stall_threshold_and_xdist_probe_vendor_neutrally(self) -> None:
        text = (ROOT / "references" / "delegation.md").read_text(encoding="utf-8")
        lowered = text.casefold()
        # FR-1: fast pre-dispatch canary + short idle-output stall threshold + failover
        self.assertIn("canary", lowered)
        self.assertRegex(lowered, r"short-timeout|readiness check")
        self.assertIn("stall", lowered)
        self.assertRegex(text, r"3[–-]5\s*min")
        self.assertIn("fallback ladder", lowered)
        # FR-2: xdist probe and targeted local suites fallback
        self.assertIn('python3 -c "import xdist"', text)
        self.assertIn("pytest -n auto", text)
        self.assertIn("targeted", lowered)
        # Vendor neutrality: do not pin vendor/model IDs into delegation policy
        for forbidden in (
            r"\bopenai\b",
            r"\banthropic\b",
            r"\bclaude[-_0-9]",
            r"\bgpt[-_0-9]",
            r"\bgemini[-_0-9]",
            r"\bdeepseek\b",
            r"\bqwen\b",
            r"\bgrok\b",
            r"\bopenrouter\b",
        ):
            self.assertIsNone(
                re.search(forbidden, lowered),
                f"references/delegation.md must stay vendor-neutral; matched {forbidden}",
            )


if __name__ == "__main__":
    unittest.main()
