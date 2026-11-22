"""Thin-brief gate and human-test conflict check (#92). No vendor API."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "runtime"))

import sdlc_flows  # noqa: E402


TITLE_ONLY = {"title": "Login"}
COMPLETE = {
    "request": "A standard user can sign in and see Products.",
    "how_it_works": "Valid credentials open the inventory page.",
    "code_under_test": "src/test/java/testPackage/LoginTest.java",
    "behavior": "standard user sees Products",
    "path": "tests/test_login.py",
}


def test_title_only_refuses_and_names_the_missing_sources():
    result = sdlc_flows.thin_brief_gate(TITLE_ONLY)
    assert result["draft"] is False
    assert result["cases"] == []
    assert result["reasons"] == ["thin-brief"]
    assert result["missing"] == ["request", "how_it_works", "code_under_test"]
    drafted = sdlc_flows.prepare_test_draft(TITLE_ONLY, [])
    assert drafted["drafts"] == []


def test_complete_brief_may_draft_without_a_vendor_call():
    result = sdlc_flows.prepare_test_draft(COMPLETE, [])
    assert result["draft"] is True
    assert result["missing"] == []
    assert result["drafts"][0]["expected"]
    assert result["drafts"][0]["steps"]


def test_already_in_the_tree_is_not_copied():
    tree = [{"behavior": "standard user sees Products", "path": "tests/test_login.py", "human_edited": True}]
    result = sdlc_flows.prepare_test_draft(COMPLETE, tree)
    assert result["drafts"] == []
    assert "already-in-tree" in result["reasons"]


def test_human_edited_file_is_not_overwritten_unless_owner_named_it():
    tree = [{"behavior": "other", "path": "tests/test_login.py", "human_edited": True}]
    brief = {**COMPLETE, "behavior": "locked out user is refused"}
    blocked = sdlc_flows.prepare_test_draft(brief, tree)
    assert blocked["drafts"] == []
    assert "would-overwrite-human-test" in blocked["reasons"]
    allowed = sdlc_flows.prepare_test_draft(brief, tree, owner_named=["tests/test_login.py"])
    assert allowed["draft"] is True
    assert allowed["overwrites"] == []


def test_gap_without_executable_or_expected_is_refused():
    proposed = [{"behavior": "new gap", "path": "tests/test_new.py", "steps": [], "expected": ""}]
    result = sdlc_flows.conflict_check(proposed, [])
    assert result["drafts"] == []
    assert "missing-executable-or-expected" in result["reasons"]
    ready = sdlc_flows.conflict_check(
        [{"behavior": "new gap", "path": "tests/test_new.py", "steps": ["Open the form"], "expected": "The form is shown"}],
        [],
    )
    assert ready["ok"] is True
    assert ready["drafts"]
