"""#6986: gh pr create/edit bodies are checked for the riskiest-assumption section."""

from __future__ import annotations

import importlib.util
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def _load_guard():
    spec = importlib.util.spec_from_file_location("ce_guard_6986", ROOT / "hooks/guard.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class PrBodyPreflightTest(unittest.TestCase):
    def setUp(self) -> None:
        self.guard = _load_guard()

    def test_body_file_without_targeted_test_is_blocked(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            body = Path(temporary, "body.md")
            body.write_text("Fixes things\n\n## Riskiest assumption\nThat it works.\n", encoding="utf-8")
            reason = self.guard._pr_body_block((f"gh pr create --title t --body-file {body}",))
        self.assertIn("PR body would fail the CI PR Body guard", reason)
        self.assertIn("targeted test", reason)

    def test_missing_section_on_inline_body_is_blocked(self) -> None:
        reason = self.guard._pr_body_block(("gh pr edit 5 --body 'just text'",))
        self.assertIn("missing the Riskiest assumption", reason)

    def test_valid_bodies_and_other_commands_pass(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            body = Path(temporary, "good.md")
            body.write_text("<!-- chaos-engine:agentic -->\nx\n\n## Plan\nspec-x.md\n\nretrieve: mempalace used\nretrieve: graphify skipped index is stale\n\n"
                            "## Riskiest assumption\nThat y. Targeted test: `test_y`.\n", encoding="utf-8")
            self.assertEqual("", self.guard._pr_body_block(
                (f"gh pr create --head ChaosEngine/example --body-file {body}",)))
        self.assertEqual("", self.guard._pr_body_block((
            "gh pr create --head ChaosEngine/example --body "
            "'<!-- chaos-engine:agentic -->\n## Plan\nsteps\nretrieve: mempalace used\n\n## Riskiest assumption\nN/A'",
        )))

    def test_agentic_create_rejects_foreign_head(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            body = Path(temporary, "good.md")
            body.write_text(
                "<!-- chaos-engine:agentic -->\nx\n\n## Plan\nspec-x.md\n\nretrieve: mempalace used\n"
                "retrieve: graphify skipped index is stale\n\n"
                "## Riskiest assumption\nThat y. Targeted test: `test_y`.\n",
                encoding="utf-8",
            )
            reason = self.guard._pr_body_block((f"gh pr create --head fix/example --body-file {body}",))
        self.assertIn("ChaosEngine/<short-slug>", reason)
        self.assertIn("fix/example", reason)

    def test_agentic_create_without_head_reads_checkout_branch(self) -> None:
        self.guard._checkout_branch = lambda: "fix/example"
        command = (
            "gh pr create --body '<!-- chaos-engine:agentic -->\n## Plan\nsteps\n"
            "retrieve: mempalace used\n\n## Riskiest assumption\nN/A'"
        )
        reason = self.guard._pr_body_block((command,))
        self.assertIn("ChaosEngine/<short-slug>", reason)
        self.assertIn("fix/example", reason)
        edit = command.replace("gh pr create", "gh pr edit 5", 1)
        self.assertEqual("", self.guard._pr_body_block((edit,)))
        headed_edit = edit.replace("gh pr edit 5", "gh pr edit 5 --head fix/example", 1)
        self.assertEqual("", self.guard._pr_body_block((headed_edit,)))
        self.assertEqual("", self.guard._pr_body_block(("gh pr create --fill",)))
        self.assertEqual("", self.guard._pr_body_block(("gh pr create --body-file /no/such/file",)))

    def test_gh_hostname_flag_is_not_the_head_branch(self) -> None:
        body = (
            "'<!-- chaos-engine:agentic -->\n## Plan\nsteps\n"
            "retrieve: mempalace used\n\n## Riskiest assumption\nN/A'"
        )
        command = f"gh -H github.com pr create --head ChaosEngine/example --body {body}"
        self.assertEqual("", self.guard._pr_body_block((command,)))
        _exe, arguments = self.guard.command_head(self.guard.shell_tokens(command))
        self.assertEqual("ChaosEngine/example", self.guard._pr_head_argument(arguments))
        equals = command.replace("--head ChaosEngine/example", "--head=ChaosEngine/example", 1)
        _exe, equals_arguments = self.guard.command_head(self.guard.shell_tokens(equals))
        self.assertEqual("ChaosEngine/example", self.guard._pr_head_argument(equals_arguments))
        self.assertIsNone(self.guard._pr_head_argument(["-H", "github.com", "pr", "create"]))
        self.guard._checkout_branch = lambda: "ChaosEngine/example"
        self.assertEqual("", self.guard._pr_body_block((f"gh pr create -H github.com --body {body}",)))

    def test_global_gh_flags_do_not_skip_the_head_gate(self) -> None:
        body = (
            "'<!-- chaos-engine:agentic -->\n## Plan\nsteps\n"
            "retrieve: mempalace used\n\n## Riskiest assumption\nN/A'"
        )
        host = f"gh -H github.com pr create --head cursor/evil --body {body}"
        reason = self.guard._pr_body_block((host,))
        self.assertIn("cursor/", reason)
        repo = f"gh --repo ShaftHQ/chaosengine-harness pr create --head cursor/evil --body {body}"
        self.assertIn("cursor/", self.guard._pr_body_block((repo,)))
        allowed = f"gh --hostname github.com pr create --head ChaosEngine/example --body {body}"
        self.assertEqual("", self.guard._pr_body_block((allowed,)))
        equals = f"gh --hostname=github.com pr create --head cursor/evil --body {body}"
        self.assertIn("cursor/", self.guard._pr_body_block((equals,)))

    def test_missing_plan_or_receipt_is_blocked(self) -> None:
        no_plan = "gh pr create --body '<!-- chaos-engine:agentic -->\nretrieve: mempalace used\n\n## Riskiest assumption\nN/A'"
        self.assertIn("`## Plan`", self.guard._pr_body_block((no_plan,)))
        no_receipt = "gh pr create --body '<!-- chaos-engine:agentic -->\n## Plan\nsteps\n\n## Riskiest assumption\nN/A'"
        self.assertIn("receipt line", self.guard._pr_body_block((no_receipt,)))
        bare_skip = "gh pr create --body '<!-- chaos-engine:agentic -->\n## Plan\nsteps\nretrieve: graphify skipped\n\n## Riskiest assumption\nN/A'"
        self.assertIn("skipped without a reason", self.guard._pr_body_block((bare_skip,)))
        unmarked = "gh pr create --body '## Plan\nsteps\nretrieve: mempalace used\n\n## Riskiest assumption\nN/A'"
        self.assertIn("chaos-engine:agentic", self.guard._pr_body_block((unmarked,)))
        self.assertEqual("", self.guard._pr_body_block(("gh pr view 5",)))
        self.assertEqual("", self.guard._pr_body_block(("gh pr create --fill",)))
        self.assertEqual("", self.guard._pr_body_block(("gh pr create --body-file /no/such/file",)))

    def test_comment_body_does_not_replace_the_pull_request_body(self) -> None:
        valid = (
            "<!-- chaos-engine:agentic -->\n\n## Plan\nsteps\n\n"
            "retrieve: mempalace used\n\n## Riskiest assumption\nN/A\n"
        )
        with tempfile.TemporaryDirectory() as temporary:
            body = Path(temporary, "body.md")
            body.write_text(valid, encoding="utf-8")
            for separator in ("&&", "||", ";"):
                command = f"gh pr edit 1 --body-file {body} {separator} gh pr comment 1 --body note"
                self.assertEqual("", self.guard._pr_body_block((command,)), separator)
        replaced = (
            "gh pr edit 1 --body 'just text' && gh pr comment 1 --body "
            "'<!-- chaos-engine:agentic -->\n## Plan\nsteps\nretrieve: mempalace used\n\n"
            "## Riskiest assumption\nN/A'"
        )
        reason = self.guard._pr_body_block((replaced,))
        self.assertIn("missing the Riskiest assumption", reason)
        self.assertEqual("", self.guard._pr_body_block(("gh pr comment 1 --body note",)))
        lone = self.guard._pr_body_block(("gh pr edit 2 --body 'just text'",))
        self.assertIn("missing the Riskiest assumption", lone)


if __name__ == "__main__":
    unittest.main()
