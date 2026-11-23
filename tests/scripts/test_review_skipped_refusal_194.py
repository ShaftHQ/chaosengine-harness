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


if __name__ == "__main__":
    unittest.main()
