"""#254: cross-repo -R/--repo forwarding and merge_queue BLOCKED readiness gate."""

from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


GUARD = _load("chaos_engine_guard_254", ROOT / "hooks" / "guard.py")


def ready(**overrides):
    snapshot = {
        "checks": [
            {"name": "ci", "status": "COMPLETED", "conclusion": "SUCCESS", "isRequired": True},
        ],
        "unresolved": 0,
        "hasNextPage": False,
        "mergeStateStatus": "CLEAN",
        "files": ["README.md"],
        "filesComplete": True,
    }
    snapshot.update(overrides)
    return snapshot


def blocked(**overrides):
    snapshot = ready(
        mergeStateStatus="BLOCKED",
        baseHasMergeQueue=True,
        hasStrategyFlag=False,
        reviewDecision="APPROVED",
    )
    snapshot.update(overrides)
    return snapshot


class RepoForwarding254Test(unittest.TestCase):
    def test_repo_reaches_probe_for_every_cli_spelling(self) -> None:
        cases = (
            ("gh pr merge 8189 -R ShaftHQ/SHAFT_ENGINE --merge", "ShaftHQ/SHAFT_ENGINE"),
            ("gh pr merge 8189 --repo ShaftHQ/SHAFT_ENGINE --merge", "ShaftHQ/SHAFT_ENGINE"),
            ("gh pr merge 8189 --repo=ShaftHQ/SHAFT_ENGINE --merge", "ShaftHQ/SHAFT_ENGINE"),
            ("gh pr merge 8189 -RShaftHQ/SHAFT_ENGINE --merge", "ShaftHQ/SHAFT_ENGINE"),
        )
        for command, expected in cases:
            with self.subTest(command=command):
                seen = []

                def probe(target, *, repo=None, has_strategy_flag=None, seen=seen):
                    seen.append((target, repo, has_strategy_flag))
                    return ready()

                self.assertEqual("", GUARD.merge_before_ready_reason(command, probe=probe))
                self.assertEqual([("8189", expected, True)], seen)

    def test_live_probe_forwards_repo_to_gh_pr_view(self) -> None:
        calls = []

        def fake(args):
            calls.append(list(args))
            if args[:2] == ["pr", "view"]:
                return {
                    "id": "",
                    "url": "https://github.com/ShaftHQ/SHAFT_ENGINE/pull/8189",
                    "mergeStateStatus": "CLEAN",
                    "statusCheckRollup": [],
                    "files": [],
                }, ""
            if args[:2] == ["api", "graphql"]:
                return {
                    "data": {
                        "repository": {
                            "pullRequest": {
                                "reviewThreads": {
                                    "pageInfo": {"hasNextPage": False},
                                    "nodes": [],
                                }
                            }
                        }
                    }
                }, ""
            return [], ""

        original = GUARD._gh_json
        GUARD._gh_json = fake
        try:
            snapshot = GUARD.live_merge_probe("8189", repo="ShaftHQ/SHAFT_ENGINE")
        finally:
            GUARD._gh_json = original
        self.assertNotIn("error", snapshot)
        view = next(call for call in calls if call[:2] == ["pr", "view"])
        self.assertIn("--repo", view)
        self.assertIn("ShaftHQ/SHAFT_ENGINE", view)


class MergeQueueReadiness254Test(unittest.TestCase):
    def test_merge_queue_enqueue_is_allowed_when_every_gate_is_green(self) -> None:
        self.assertEqual("", GUARD.merge_readiness_reason(blocked()))

    def test_merge_queue_enqueue_allows_no_review_decision(self) -> None:
        for decision in ("", None, "APPROVED"):
            with self.subTest(decision=decision):
                self.assertEqual("", GUARD.merge_readiness_reason(blocked(reviewDecision=decision)))

    def test_draft_and_dirty_are_always_denied(self) -> None:
        for state in ("DRAFT", "DIRTY"):
            with self.subTest(state=state):
                reason = GUARD.merge_readiness_reason(blocked(mergeStateStatus=state))
                self.assertIn(state, reason)

    def test_blocked_without_merge_queue_is_denied(self) -> None:
        for value in (False, None, "yes"):
            with self.subTest(value=value):
                reason = GUARD.merge_readiness_reason(blocked(baseHasMergeQueue=value))
                self.assertIn("BLOCKED", reason)

    def test_blocked_with_strategy_flag_is_denied(self) -> None:
        reason = GUARD.merge_readiness_reason(blocked(hasStrategyFlag=True))
        self.assertIn("BLOCKED", reason)

    def test_blocked_with_review_requirements_is_denied(self) -> None:
        for decision in ("CHANGES_REQUESTED", "REVIEW_REQUIRED"):
            with self.subTest(decision=decision):
                reason = GUARD.merge_readiness_reason(blocked(reviewDecision=decision))
                self.assertIn("BLOCKED", reason)

    def test_blocked_with_failing_check_is_denied(self) -> None:
        snapshot = blocked(checks=[{"name": "ci", "status": "COMPLETED", "conclusion": "FAILURE"}])
        reason = GUARD.merge_readiness_reason(snapshot)
        self.assertNotEqual("", reason)
        self.assertNotIn("merge state is BLOCKED", reason)

    def test_blocked_with_open_thread_is_denied(self) -> None:
        reason = GUARD.merge_readiness_reason(blocked(unresolved=1))
        self.assertIn("review comments are still open", reason)

    def test_live_probe_records_merge_queue_state(self) -> None:
        calls = []

        def fake(args):
            calls.append(list(args))
            if args[:2] == ["pr", "view"]:
                return {
                    "id": "",
                    "url": "https://github.com/acme/widgets/pull/77",
                    "mergeStateStatus": "BLOCKED",
                    "baseRefName": "main",
                    "reviewDecision": "APPROVED",
                    "statusCheckRollup": [
                        {"name": "ci", "status": "COMPLETED", "conclusion": "SUCCESS"}
                    ],
                    "files": [],
                }, ""
            if args[:2] == ["api", "graphql"]:
                return {
                    "data": {
                        "repository": {
                            "pullRequest": {
                                "reviewThreads": {
                                    "pageInfo": {"hasNextPage": False},
                                    "nodes": [],
                                }
                            }
                        }
                    }
                }, ""
            if args[0] == "api" and any("rules/branches" in item for item in args):
                return [{"type": "pull_request"}, {"type": "merge_queue"}], ""
            return None, "unexpected gh call: " + " ".join(args)

        original = GUARD._gh_json
        GUARD._gh_json = fake
        try:
            snapshot = GUARD.live_merge_probe("77", has_strategy_flag=False)
        finally:
            GUARD._gh_json = original
        self.assertTrue(snapshot.get("baseHasMergeQueue"))
        self.assertEqual("APPROVED", snapshot.get("reviewDecision"))
        self.assertIn("main", " ".join(item for call in calls for item in call))
        self.assertEqual("", GUARD.merge_readiness_reason(snapshot))

    def test_ruleset_lookup_error_fails_closed(self) -> None:
        def fake(args):
            if args[:2] == ["pr", "view"]:
                return {
                    "id": "",
                    "url": "https://github.com/acme/widgets/pull/78",
                    "mergeStateStatus": "BLOCKED",
                    "baseRefName": "main",
                    "reviewDecision": "APPROVED",
                    "statusCheckRollup": [
                        {"name": "ci", "status": "COMPLETED", "conclusion": "SUCCESS"}
                    ],
                    "files": [],
                }, ""
            if args[:2] == ["api", "graphql"]:
                return {
                    "data": {
                        "repository": {
                            "pullRequest": {
                                "reviewThreads": {
                                    "pageInfo": {"hasNextPage": False},
                                    "nodes": [],
                                }
                            }
                        }
                    }
                }, ""
            if args[0] == "api" and any("rules/branches" in item for item in args):
                return None, "gh could not read rules."
            return None, "unexpected gh call: " + " ".join(args)

        original = GUARD._gh_json
        GUARD._gh_json = fake
        try:
            snapshot = GUARD.live_merge_probe("78", has_strategy_flag=False)
        finally:
            GUARD._gh_json = original
        self.assertFalse(snapshot.get("baseHasMergeQueue"))
        self.assertIn("BLOCKED", GUARD.merge_readiness_reason(snapshot))

    def test_clean_state_does_not_query_rulesets(self) -> None:
        calls = []

        def fake(args):
            calls.append(list(args))
            if args[:2] == ["pr", "view"]:
                return {
                    "id": "",
                    "url": "https://github.com/acme/widgets/pull/79",
                    "mergeStateStatus": "CLEAN",
                    "statusCheckRollup": [],
                    "files": [],
                }, ""
            if args[:2] == ["api", "graphql"]:
                return {
                    "data": {
                        "repository": {
                            "pullRequest": {
                                "reviewThreads": {
                                    "pageInfo": {"hasNextPage": False},
                                    "nodes": [],
                                }
                            }
                        }
                    }
                }, ""
            return None, "unexpected gh call: " + " ".join(args)

        original = GUARD._gh_json
        GUARD._gh_json = fake
        try:
            GUARD.live_merge_probe("79")
        finally:
            GUARD._gh_json = original
        self.assertFalse(any("rules/branches" in item for call in calls for item in call))


if __name__ == "__main__":
    unittest.main()
