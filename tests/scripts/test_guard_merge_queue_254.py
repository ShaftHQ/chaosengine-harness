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


class UnifiedMergeFlagParser254Test(unittest.TestCase):
    def test_value_flags_never_expose_smuggled_flags(self) -> None:
        cases = (
            ("gh pr merge 77 --body '-Rattacker/clean-repo' --merge", None, True),
            ("gh pr merge 77 --body '--squash'", None, False),
            ("gh pr merge 77 -b -s", None, False),
            ("gh pr merge 77 --subject '--repo=attacker/clean-repo'", None, False),
            ("gh pr merge 77 -b--squash --merge", None, True),
        )
        for command, expected_repo, expected_strategy in cases:
            with self.subTest(command=command):
                seen = []

                def probe(target, *, repo=None, has_strategy_flag=None, seen=seen):
                    seen.append((target, repo, has_strategy_flag))
                    return ready()

                self.assertEqual("", GUARD.merge_before_ready_reason(command, probe=probe))
                self.assertEqual([("77", expected_repo, expected_strategy)], seen)

    def test_repo_values_fail_closed(self) -> None:
        for command in (
            "gh pr merge 77 --repo",
            "gh pr merge 77 -R",
            "gh pr merge 77 --repo=",
            "gh pr merge 77 --repo=-owner/repo",
            "gh pr merge 77 -R -owner/repo",
        ):
            with self.subTest(command=command):
                reason = GUARD.merge_before_ready_reason(command, probe=lambda _target: ready())
                self.assertIn("could not be read", reason)

    def test_admin_and_strategy_forms_disqualify_merge_queue_enqueue(self) -> None:
        commands = (
            "gh pr merge 77 --admin",
            "gh pr merge 77 --admin=true",
            "gh pr merge 77 --squash=true",
            "gh pr merge 77 --merge=1",
            "gh pr merge 77 -ds",
            "gh pr merge 77 -dm",
            "gh pr merge 77 -dr",
            "gh pr merge 77 -sd",
        )
        for command in commands:
            with self.subTest(command=command):
                seen = []

                def probe(target, *, repo=None, has_strategy_flag=None, seen=seen):
                    seen.append(has_strategy_flag)
                    return blocked()

                reason = GUARD.merge_before_ready_reason(command, probe=probe)
                self.assertIn("BLOCKED", reason)
                self.assertEqual([True], seen)

    def test_false_strategy_and_admin_values_keep_merge_queue_enqueue(self) -> None:
        for command in ("gh pr merge 77 --squash=false", "gh pr merge 77 --admin=false"):
            with self.subTest(command=command):
                seen = []

                def probe(target, *, repo=None, has_strategy_flag=None, seen=seen):
                    seen.append(has_strategy_flag)
                    return blocked()

                self.assertEqual("", GUARD.merge_before_ready_reason(command, probe=probe))
                self.assertEqual([False], seen)

    def test_double_dash_makes_repo_lookalike_a_positional_target(self) -> None:
        seen = []

        def probe(target, *, repo=None, has_strategy_flag=None, seen=seen):
            seen.append((target, repo, has_strategy_flag))
            return ready()

        command = "gh pr merge -- -Rattacker/clean-repo --merge"
        self.assertEqual("", GUARD.merge_before_ready_reason(command, probe=probe))
        self.assertEqual([("-Rattacker/clean-repo", None, False)], seen)

    def test_repo_inside_bundled_short_flags_is_forwarded(self) -> None:
        seen = []

        def probe(target, *, repo=None, has_strategy_flag=None, seen=seen):
            seen.append((target, repo, has_strategy_flag))
            return ready()

        command = "gh pr merge 77 -dRShaftHQ/clean --merge"
        self.assertEqual("", GUARD.merge_before_ready_reason(command, probe=probe))
        self.assertEqual([("77", "ShaftHQ/clean", True)], seen)

    def test_empty_equals_short_value_does_not_consume_next_token(self) -> None:
        seen = []

        def probe(target, *, repo=None, has_strategy_flag=None, seen=seen):
            seen.append((target, repo, has_strategy_flag))
            return ready(checks=[{"name": "ci", "status": "COMPLETED", "conclusion": "FAILURE"}])

        command = "gh pr merge 10 -R attacker/clean -b= -R real/red"
        reason = GUARD.merge_before_ready_reason(command, probe=probe)
        self.assertNotEqual("", reason)
        self.assertEqual([("10", "real/red", False)], seen)

    def test_empty_equals_body_value_exposes_smuggled_strategy_flag(self) -> None:
        for flag in ("--admin", "--squash"):
            with self.subTest(flag=flag):
                seen = []

                def probe(target, *, repo=None, has_strategy_flag=None, seen=seen):
                    seen.append(has_strategy_flag)
                    return blocked()

                reason = GUARD.merge_before_ready_reason(f"gh pr merge 10 -b= {flag}", probe=probe)
                self.assertIn("BLOCKED", reason)
                self.assertEqual([True], seen)

    def test_repo_bare_equals_fails_closed(self) -> None:
        reason = GUARD.merge_before_ready_reason(
            "gh pr merge 10 -R= attacker/clean", probe=lambda _target: ready()
        )
        self.assertIn("could not be read", reason)


class GlobalRepoBeforeMerge254Test(unittest.TestCase):
    def test_global_and_parent_repo_flags_route_the_gate(self) -> None:
        for command in (
            "gh pr -R real/red merge 10",
            "gh -R real/red pr merge 10",
            "gh --repo=real/red pr merge 10",
            "gh pr --repo real/red merge 10",
        ):
            with self.subTest(command=command):
                seen = []

                def probe(target, *, repo=None, has_strategy_flag=None, seen=seen):
                    seen.append((target, repo, has_strategy_flag))
                    return ready()

                self.assertEqual("", GUARD.merge_before_ready_reason(command, probe=probe))
                self.assertEqual([("10", "real/red", False)], seen)

    def test_repo_after_merge_overrides_pre_merge_repo(self) -> None:
        seen = []

        def probe(target, *, repo=None, has_strategy_flag=None, seen=seen):
            seen.append((target, repo, has_strategy_flag))
            return ready()

        command = "gh -R attacker/clean pr merge 10 -R real/red"
        self.assertEqual("", GUARD.merge_before_ready_reason(command, probe=probe))
        self.assertEqual([("10", "real/red", False)], seen)


if __name__ == "__main__":
    unittest.main()
