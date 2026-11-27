"""Review floor (#8055, #8048 R2, #8063). Packet lint calls the shipped function."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "runtime"))

import review_packet  # noqa: E402

CLEAN = """## Artifact
SHA: abcdef1234567890

## Checklist
- missing tests
- hidden scope
- unverified claims
- reader-cost
- safety

## Diff
diff --git a/honesty.py b/honesty.py
"""


def test_packet_with_plan_fails_lint():
    reasons = review_packet.lint_packet("## Plan\nAuthor decided to skip the test.\n")
    assert any("## Plan" in item for item in reasons)


def test_packet_with_author_reasoning_fails_lint():
    reasons = review_packet.lint_packet("author reasoning: the model thought the check passed.\n")
    assert any("author reasoning" in item for item in reasons)
    assert review_packet.lint_packet(CLEAN) == []


def test_floor_is_one_and_two_for_high_stakes():
    assert review_packet.required_reviews() == 1
    assert review_packet.required_reviews(public_contract=True) == 2
    assert review_packet.required_reviews(irreversible=True) == 2
    assert review_packet.required_reviews(outbound=True) == 2
    assert review_packet.required_reviews() != 0


def test_lgtm_without_checklist_and_sha_is_not_pass():
    assert review_packet.is_pass({"verdict": "LGTM"}) is False
    assert review_packet.is_pass({"verdict": "PASS", "sha": "abcdef1234567890"}) is False
    assert review_packet.is_pass(
        {
            "verdict": "PASS",
            "sha": "abcdef1234567890",
            "checklist": list(review_packet.CHECKLIST),
        }
    ) is True


def test_timeout_counts_as_round_and_does_not_retry():
    result = review_packet.bounded_round(CLEAN, elapsed_s=30, limit_s=10, rounds_used=0)
    assert result["rounds_used"] == 1
    assert result["counted"] is True
    assert result["fallback"] == "self-review"
    assert result["retry"] is False
    assert result["verdict"] == "timeout"
    assert result["spawned"] is False


def test_in_time_review_is_diff_scoped():
    result = review_packet.bounded_round(CLEAN, elapsed_s=1, limit_s=10, rounds_used=0)
    assert result["diff_scoped"] is True
    assert result["retry"] is False
    assert result["fallback"] is None
    planned = review_packet.bounded_round("## Plan\nessay\n", elapsed_s=1, limit_s=10, rounds_used=0)
    assert planned["diff_scoped"] is False
    assert planned["problems"]


def test_missing_second_cli_stays_same_model():
    result = review_packet.resolve_reviewer("codex", binary_present=False)
    assert result["reviewer"] == "grok"
    assert result["log"] == "second lens unavailable"
    assert result["spawned"] is False


def test_docs_only_budget_matches_floor_and_cap():
    small = review_packet.budget(files=1, lines=12, public_contract=False)
    assert small["min"] == 1 and small["max"] == 1
    public = review_packet.budget(files=1, lines=12, public_contract=True)
    assert public["min"] == 2 and public["max"] == 2
    large = review_packet.budget(files=20, lines=4000, public_contract=True, blast="high")
    assert large["min"] == 2 and large["max"] == 3
    assert review_packet.blocks_at_max("nit: wording", at_max=True) is False
    assert review_packet.blocks_at_max("unsafe: secret left in the receipt", at_max=True) is True


def test_delivery_cycle_keeps_min_max_and_states_floor():
    text = (ROOT / "references" / "delivery-cycle.md").read_text(encoding="utf-8")
    assert "MAX = MIN" in text
    assert "There is no zero-review path." in text
    assert "self-review" in text
    assert "no retry" in text
    assert "Future:" in text
    assert "cloud agent" in text.casefold()
    assert "Do not run" in text and "in parallel" in text
    assert "one after another" in text


def test_reviews_run_one_after_another():
    one = review_packet.review_sequence(1)
    two = review_packet.review_sequence(2)
    assert one == (
        "develop",
        "test",
        "self-accept",
        "adversarial-review-1",
        "develop",
        "test",
        "accept",
        "finalize",
    )
    assert two == (
        "develop",
        "test",
        "self-accept",
        "adversarial-review-1",
        "develop",
        "test",
        "accept",
        "adversarial-review-2",
        "develop",
        "test",
        "accept",
        "finalize",
    )
    assert two.index("adversarial-review-2") > two.index("adversarial-review-1")
    between = two[
        two.index("adversarial-review-1") + 1 : two.index("adversarial-review-2")
    ]
    assert between == ("develop", "test", "accept")
    try:
        review_packet.review_sequence(0)
    except ValueError as error:
        assert "zero-review" in str(error)
    else:
        raise AssertionError("a zero-review path was accepted")
    card = (ROOT / "skills" / "chaos-engine" / "SKILL.md").read_text(encoding="utf-8")
    assert "review 1 with the self-accept push" in card
    assert "Do not start both reviewers in one step" in card
