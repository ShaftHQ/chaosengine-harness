"""#139: evidence-close a nightly tracker when the cause is already on main."""

from __future__ import annotations

import importlib.util
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SHA = "a40ede0b368ddff9d2fda803968708ecb7322a28"
RUN = "https://github.com/example/widgets/actions/runs/44833666425"


def _load():
    path = ROOT / "runtime" / "harness_mindset.py"
    spec = importlib.util.spec_from_file_location("ce_mindset_139", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class _Result:
    def __init__(self) -> None:
        self.returncode = 0


class NightlyEvidenceCloseTest(unittest.TestCase):
    def setUp(self):
        self.mindset = _load()
        self.calls: list[list[str]] = []

        def runner(argv: list[str]) -> _Result:
            self.calls.append(list(argv))
            return _Result()

        self.runner = runner

    def _close(self, **overrides: object) -> dict:
        payload = {
            "repo": "example/widgets",
            "number": 8101,
            "cause_on_main": True,
            "fixing_sha": SHA,
            "failing_run": RUN,
            "closing_keyword_in_product_pr": False,
            "partial_jobs_dispatch": False,
            "runner": self.runner,
            "branch_reader": lambda _repo, _sha: True,
        }
        payload.update(overrides)
        return self.mindset.close_nightly_failure_tracker(**payload)

    def test_product_pr_closing_keyword_does_not_close(self):
        decision = self.mindset.decide_nightly_failure_close(
            repo="example/widgets",
            number=8101,
            cause_on_main=True,
            fixing_sha=SHA,
            failing_run=RUN,
            closing_keyword_in_product_pr=True,
        )
        self.assertEqual("refuse-closing-keyword", decision["action"])
        self.assertEqual([], decision["commands"])
        closed = self._close(closing_keyword_in_product_pr=True)
        self.assertEqual([], self.calls)
        self.assertEqual("refuse-closing-keyword", closed["action"])

    def test_partial_jobs_dispatch_is_not_recovery(self):
        decision = self.mindset.decide_nightly_failure_close(
            repo="example/widgets",
            number=8101,
            cause_on_main=False,
            fixing_sha="",
            failing_run="",
            partial_jobs_dispatch=True,
        )
        self.assertEqual("refuse-partial-dispatch", decision["action"])
        self.assertEqual([], decision["commands"])
        closed = self._close(
            cause_on_main=False,
            fixing_sha="",
            failing_run="",
            partial_jobs_dispatch=True,
        )
        self.assertEqual([], closed["commands"])
        self.assertEqual([], self.calls)

    def test_cause_on_main_closes_with_sha_and_run(self):
        decision = self.mindset.decide_nightly_failure_close(
            repo="example/widgets",
            number=8101,
            cause_on_main=True,
            fixing_sha=SHA,
            failing_run=RUN,
            branch_reader=lambda _repo, _sha: True,
        )
        self.assertEqual("evidence-close", decision["action"])
        self.assertEqual(1, len(decision["commands"]))
        command = decision["commands"][0]
        self.assertEqual("gh", command[0])
        self.assertIn("issue", command)
        self.assertIn("close", command)
        comment = command[command.index("--comment") + 1]
        self.assertIn(SHA, comment)
        self.assertIn(RUN, comment)
        closed = self._close()
        self.assertEqual([command], self.calls)
        self.assertEqual("evidence-close", closed["action"])

    def test_a_failed_branch_read_leaves_the_issue_open(self):
        decision = self.mindset.decide_nightly_failure_close(
            repo="example/widgets",
            number=8101,
            cause_on_main=True,
            fixing_sha=SHA,
            failing_run=RUN,
            branch_reader=lambda _repo, _sha: False,
        )
        self.assertEqual("leave-open", decision["action"])
        self.assertEqual([], decision["commands"])
        closed = self._close(branch_reader=lambda _repo, _sha: (_ for _ in ()).throw(OSError("down")))
        self.assertEqual("leave-open", closed["action"])
        self.assertEqual([], self.calls)

    def test_later_red_nightly_is_not_blocked(self):
        text = re.sub(
            r"\s+",
            " ",
            (ROOT / "references/details/work-github-playbook-promotion.md").read_text(encoding="utf-8"),
        )
        self.assertIn("jobs=all", text)
        self.assertIn("Related to #N", text)
        self.assertIn("A partial `jobs=` dispatch is not recovery.", text)
        self.assertIn("gh issue close", text)
        self.assertIn("fixing SHA", text)
        self.assertIn("failing run", text)
        self.assertIn("A later red nightly may file a new tracker.", text)
        self.assertIn("already on `main`", text)


if __name__ == "__main__":
    unittest.main()
