"""#240: delete guard gh heredoc / --body-file UX and delegation canary/stall/xdist docs."""

from __future__ import annotations

import importlib.util
import os
import re
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

    # --- Positive cases: benign single-quoted heredoc prose in gh commands ---

    def test_benign_gh_issue_create_single_quoted_heredoc_with_quotes_and_rm_prose(self) -> None:
        cmd = (
            'gh issue create --repo o/r --title "t" --body "$(cat <<\'EOF\'\n'
            "Use `rm -rf` carefully; don't break\n"
            'Also mentions "unclosed double quote and (parentheses)\n'
            "EOF\n"
            ')"'
        )
        self.assertEqual("", self.reason(cmd))

    def test_benign_gh_pr_create_and_issue_comment_single_quoted_heredocs(self) -> None:
        cases = (
            (
                'gh pr create --title "PR" --body "$(cat <<\'EOF\'\n'
                "Fixes `rm -rf /tmp/foo` prose; don't panic\n"
                "EOF\n"
                ')"'
            ),
            (
                'gh issue comment 240 --body "$(cat <<\'EOF\'\n'
                "Verified `unlink` and \"unmatched quote; won't regress\n"
                "EOF\n"
                ')"'
            ),
            (
                'gh pr edit 240 -b "$(cat <<-\'EOF\'\n'
                "\tTab-stripped prose mentioning rm -rf and don't\n"
                "\tEOF\n"
                ')"'
            ),
        )
        for cmd in cases:
            with self.subTest(cmd=cmd):
                self.assertEqual("", self.reason(cmd))

    def test_arithmetic_left_shift_and_herestring_inside_cmd_sub(self) -> None:
        self.assertEqual("", self.reason('echo "$(echo $(( 1 << 2 )))"'))
        self.assertEqual("", self.reason('echo "$(cat <<< \'rm -rf precious.txt\')"'))
        refused = self.reason(f'echo "$(sh <<< \'rm -rf {self.precious}\')"')
        self.assertIn("untracked", refused)
        self.assertIn("precious.txt", refused)

    # --- Unparsable gh commands: fail closed WITH explicit --body-file hint ---

    def test_unparsable_gh_commands_refuse_with_body_file_hint(self) -> None:
        cases = (
            # Genuinely unclosed double quote mentioning rm
            'gh issue create --title "t" --body "don\'t run rm -rf precious.txt',
            # Unclosed heredoc inside $(...)
            'gh pr create --title "t" --body "$(cat <<\'EOF\'\ndon\'t rm -rf precious.txt\n)"',
            # Bash EOF) early-close quirk sharing line with ')'
            'gh issue comment 240 --body "$(cat <<\'EOF\'\nrm -rf precious.txt\nEOF)"',
            # gh pr edit unclosed quote
            'gh pr edit 240 --body "mentions rm -rf precious.txt',
        )
        for cmd in cases:
            with self.subTest(cmd=cmd):
                reason = self.reason(cmd)
                self.assertIn("unparsable delete", reason)
                self.assertIn("--body-file", reason)

    # --- Adversarial cases: ALL MUST BE REFUSED ---

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

    def test_adversarial_trailing_delete_inside_cmd_sub_after_eof_refused(self) -> None:
        cmd = (
            'gh issue create --title "t" --body "$(cat <<\'EOF\'\n'
            "hi\n"
            "EOF\n"
            f"rm -rf {self.precious}\n"
            ')"'
        )
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
                f"don't break $(rm -rf {self.precious})\n"
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

    def test_adversarial_eof_same_line_paren_smuggling_refused(self) -> None:
        cases = (
            (
                'gh issue create --title "t" --body "$(cat <<\'EOF\'\n'
                "hi\n"
                f'EOF)"; rm -rf {self.precious} #\n'
                "EOF\n"
                ')"'
            ),
            (
                'gh issue create --title "t" --body "$(cat <<\'EOF\'\n'
                "hi\n"
                f"EOF$(rm -rf {self.precious})\n"
                "EOF\n"
                ')"'
            ),
        )
        for cmd in cases:
            with self.subTest(cmd=cmd):
                reason = self.reason(cmd)
                self.assertNotEqual("", reason)
                self.assertIn("Delete guard", reason)

    def test_adversarial_executing_heredoc_inside_cmd_sub_and_title_delete_refused(self) -> None:
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
