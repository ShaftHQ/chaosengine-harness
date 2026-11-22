"""Replaced literals and unmarked memory causes (#166)."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "runtime"))

import memory_provenance  # noqa: E402
import pre_done_review  # noqa: E402

DIFF = """diff --git a/app.py b/app.py
--- a/app.py
+++ b/app.py
@@ -1 +1 @@
-port = 8080
+port = int(os.environ.get("PORT", "8080"))
"""


def _clean(**extra) -> dict:
    obs = {"proofs": [{"id": "pytest", "ran": True, "exit": 0}]}
    obs.update(extra)
    return obs


def test_replaced_literal_names_the_remaining_reader(tmp_path: Path):
    (tmp_path / "other.py").write_text("port = 8080\n", encoding="utf-8")
    warnings = pre_done_review.check_replaced_literal_readers(DIFF, tmp_path)
    assert any("other.py:1" in item and "8080" in item for item in warnings)
    unchanged = DIFF.replace('os.environ.get("PORT", "8080")', "9090")
    assert pre_done_review.check_replaced_literal_readers(unchanged, tmp_path) == []
    reasons = pre_done_review.mechanical_problems(
        _clean(diff=DIFF, project_root=str(tmp_path))
    )
    assert any("other.py:1" in item and "8080" in item for item in reasons)


def test_cause_without_hypothesis_or_verified_is_rejected():
    rejected = memory_provenance.accept_memory_note("The root cause is a stale cache.")
    assert rejected["ok"] is False
    assert rejected["rejected"] is True
    assert rejected["reasons"] == ["cause-without-hypothesis-or-verified"]
    hypothesis = memory_provenance.accept_memory_note(
        "Hypothesis: the root cause is a stale cache."
    )
    assert hypothesis["ok"] is True
    assert hypothesis["rejected"] is False
    verified = memory_provenance.accept_memory_note(
        {"text": "The root cause is a stale cache.", "verified": True}
    )
    assert verified["ok"] is True
    plain = memory_provenance.accept_memory_note("The cache key includes the host.")
    assert plain["ok"] is True
    reasons = pre_done_review.mechanical_problems(
        _clean(memory_note="because the cache key was stale")
    )
    assert "cause-without-hypothesis-or-verified" in reasons
