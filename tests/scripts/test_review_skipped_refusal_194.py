"""Skipped refusal is a regression fail even when the brief omits the payload.

An example the brief does not name stays a residual when it is not a skipped
refusal. The brief's extra ``rm`` lines are not the ``curl | bash`` payload.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from runtime.review_contract import classify_unbound_example  # noqa: E402
from runtime.review_packet import CHECKLIST, is_pass  # noqa: E402


def _floor_pass(**extra: object) -> dict:
    review = {
        "verdict": "PASS",
        "sha": "abcdef1234567890",
        "checklist": list(CHECKLIST),
    }
    review.update(extra)
    return review


class SkippedRefusalReviewTest(unittest.TestCase):
    def test_unnamed_curl_bash_skip_is_regression_fail(self):
        # Old path refused ``curl | bash``. New path allows it.
        # The brief only names extra ``rm`` lines, not this payload.
        self.assertEqual(
            {"heading": "regression", "verdict": "fail"},
            classify_unbound_example(
                old_refused=True,
                new_allows=True,
                brief_names_example=False,
            ),
        )

    def test_named_skipped_refusal_is_still_regression_fail(self):
        self.assertEqual(
            {"heading": "regression", "verdict": "fail"},
            classify_unbound_example(
                old_refused=True,
                new_allows=True,
                brief_names_example=True,
            ),
        )

    def test_still_refused_unnamed_payload_is_residual_pass(self):
        self.assertEqual(
            {"heading": "residual", "verdict": "pass"},
            classify_unbound_example(
                old_refused=True,
                new_allows=False,
                brief_names_example=False,
            ),
        )

    def test_unnamed_example_old_path_did_not_refuse_is_residual_pass(self):
        self.assertEqual(
            {"heading": "residual", "verdict": "pass"},
            classify_unbound_example(
                old_refused=False,
                new_allows=True,
                brief_names_example=False,
            ),
        )

    def test_named_example_that_is_not_a_skipped_refusal_is_unbound_check_pass(self):
        self.assertEqual(
            {"heading": "unbound-check", "verdict": "pass"},
            classify_unbound_example(
                old_refused=False,
                new_allows=True,
                brief_names_example=True,
            ),
        )

    def test_is_pass_regression_fails_even_when_floor_would_pass(self):
        """Skipped refusal fails is_pass and is stored once in unbound_findings.

        unbound_findings is the list of classifier results on the review dict.
        """
        review = _floor_pass(
            old_refused=True,
            new_allows=True,
            brief_names_example=False,
        )
        self.assertFalse(is_pass(review))
        self.assertEqual(
            [{"heading": "regression", "verdict": "fail"}],
            review["unbound_findings"],
        )
        self.assertFalse(is_pass(review))
        self.assertEqual(
            [{"heading": "regression", "verdict": "fail"}],
            review["unbound_findings"],
        )

    def test_named_example_and_residual_do_not_fail_is_pass(self):
        named = _floor_pass(
            old_refused=False,
            new_allows=True,
            brief_names_example=True,
        )
        residual = _floor_pass(
            old_refused=True,
            new_allows=False,
            brief_names_example=False,
        )
        unnamed_allowed = _floor_pass(
            old_refused=False,
            new_allows=True,
            brief_names_example=False,
        )
        self.assertTrue(is_pass(named))
        self.assertTrue(is_pass(residual))
        self.assertTrue(is_pass(unnamed_allowed))
        self.assertNotIn("unbound_findings", named)
        self.assertNotIn("unbound_findings", residual)
        self.assertNotIn("unbound_findings", unnamed_allowed)

    def test_already_failed_review_records_regression_once(self):
        review = {
            "verdict": "FAIL",
            "old_refused": True,
            "new_allows": True,
            "brief_names_example": True,
        }
        self.assertFalse(is_pass(review))
        self.assertEqual(
            [{"heading": "regression", "verdict": "fail"}],
            review["unbound_findings"],
        )
        self.assertFalse(is_pass(review))
        self.assertEqual(1, len(review["unbound_findings"]))

    def test_is_pass_without_the_three_bool_keys_is_unchanged(self):
        passing = _floor_pass()
        self.assertTrue(is_pass(passing))
        self.assertEqual(
            {"verdict", "sha", "checklist"},
            set(passing),
        )
        partial = _floor_pass(old_refused=True, new_allows=True)
        self.assertTrue(is_pass(partial))
        self.assertNotIn("unbound_findings", partial)
        coerced = _floor_pass(
            old_refused="yes",
            new_allows=True,
            brief_names_example=False,
        )
        self.assertTrue(is_pass(coerced))
        self.assertNotIn("unbound_findings", coerced)
        lgtm = {"verdict": "LGTM"}
        self.assertFalse(is_pass(lgtm))
        self.assertEqual({"verdict": "LGTM"}, lgtm)
        self.assertFalse(is_pass("PASS"))


if __name__ == "__main__":
    unittest.main()
