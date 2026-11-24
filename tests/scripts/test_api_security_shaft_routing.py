"""API pack routing, security posture, and skill boundaries (#220)."""

from __future__ import annotations

import difflib
import importlib.util
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
API = ROOT / "skills" / "api-integration-testing"
SECURITY = ROOT / "skills" / "security-audit"
FORBIDDEN = ("ShaftHQ", "SHAFT_ENGINE")
PYRAMID_MAX = int(4.5 * 1024)


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    assert spec is not None and spec.loader is not None
    spec.loader.exec_module(module)
    return module


VERIFY = _load("ce_security_verify_220", SECURITY / "verify.py")
ROUTE = _load("ce_api_route_220", API / "route.py")


def _description(path: Path) -> str:
    text = path.read_text(encoding="utf-8")
    match = re.search(r"(?ms)^---\n.*?^description:\s*(.+?)\n(?:[a-z_-]+:|---)", text)
    if match is None:
        return ""
    value = re.sub(r"^[>|][-+]?\s*", "", match.group(1).strip())
    return " ".join(value.strip("\"'").split())


class ClassifyTests(unittest.TestCase):
    def test_signature_is_unchanged(self) -> None:
        source = (SECURITY / "verify.py").read_text(encoding="utf-8")
        self.assertIn(
            "def classify(repo_owned: bool, verifier_is_writer: bool, second_pass_verified: bool) -> str:",
            source,
        )

    def test_unowned_repository_stops(self) -> None:
        for writer in (False, True):
            for second in (False, True):
                with self.subTest(writer=writer, second=second):
                    self.assertEqual("stop", VERIFY.classify(False, writer, second))

    def test_writer_or_missing_second_pass_is_unconfirmed(self) -> None:
        self.assertEqual("unconfirmed", VERIFY.classify(True, True, True))
        self.assertEqual("unconfirmed", VERIFY.classify(True, True, False))
        self.assertEqual("unconfirmed", VERIFY.classify(True, False, False))

    def test_independent_second_pass_confirms(self) -> None:
        self.assertEqual("confirmed", VERIFY.classify(True, False, True))


class ScanPostureTests(unittest.TestCase):
    def test_authorized_target_is_keyword_only(self) -> None:
        with self.assertRaises(TypeError):
            VERIFY.scan_posture(True, True, True, True)  # type: ignore[misc]

    def test_unowned_and_unauthorized_stops(self) -> None:
        for named in (False, True):
            for active in (False, True):
                with self.subTest(named=named, active=active):
                    self.assertEqual("stop", VERIFY.scan_posture(False, named, active))

    def test_active_scan_without_a_named_target_stops(self) -> None:
        self.assertEqual("stop", VERIFY.scan_posture(True, False, True))
        self.assertEqual(
            "stop",
            VERIFY.scan_posture(False, False, True, authorized_target=True),
        )

    def test_named_active_scan_is_authorized_for_owned_or_authorized_targets(self) -> None:
        self.assertEqual("authorized", VERIFY.scan_posture(True, True, True))
        self.assertEqual(
            "authorized",
            VERIFY.scan_posture(False, True, True, authorized_target=True),
        )
        self.assertEqual(
            "authorized",
            VERIFY.scan_posture(True, True, True, authorized_target=True),
        )

    def test_inactive_owned_or_authorized_work_is_design_only(self) -> None:
        self.assertEqual("design-only", VERIFY.scan_posture(True, False, False))
        self.assertEqual("design-only", VERIFY.scan_posture(True, True, False))
        self.assertEqual(
            "design-only",
            VERIFY.scan_posture(False, True, False, authorized_target=True),
        )


class RouteTests(unittest.TestCase):
    def test_denied_none_and_empty_are_native(self) -> None:
        self.assertEqual("native", ROUTE.route("core", True, denied=True))
        self.assertEqual("native", ROUTE.route("user", True, True))
        self.assertEqual("native", ROUTE.route("none", True))
        self.assertEqual("native", ROUTE.route("none", False, denied=True))
        self.assertEqual("native", ROUTE.route("", True))

    def test_core_and_user_follow_the_addon(self) -> None:
        self.assertEqual("pack", ROUTE.route("core", True))
        self.assertEqual("blocked", ROUTE.route("core", False))
        self.assertEqual("pack", ROUTE.route("user", True, False))
        self.assertEqual("blocked", ROUTE.route("user", False, False))

    def test_unknown_kind_raises(self) -> None:
        with self.assertRaises(ValueError):
            ROUTE.route("other", True)
        with self.assertRaises(ValueError):
            ROUTE.route("CORE", True)


class SkillBoundaryTests(unittest.TestCase):
    def test_skill_markdown_stays_within_byte_budgets(self) -> None:
        api = len((API / "SKILL.md").read_bytes())
        security = len((SECURITY / "SKILL.md").read_bytes())
        pyramid = len((SECURITY / "references" / "security-pyramid.md").read_bytes())
        self.assertLessEqual(api, 2100)
        self.assertLessEqual(security, 2200)
        self.assertLessEqual(api, 2200)
        self.assertLessEqual(security, 2200)
        self.assertLessEqual(pyramid, PYRAMID_MAX)

    def test_trigger_descriptions_do_not_overlap(self) -> None:
        api = _description(API / "SKILL.md")
        security = _description(SECURITY / "SKILL.md")
        self.assertGreaterEqual(len(api), 100)
        self.assertLessEqual(len(api), 160)
        self.assertGreaterEqual(len(security), 100)
        self.assertLessEqual(len(security), 160)
        self.assertLess(difflib.SequenceMatcher(None, api, security).ratio(), 0.75)
        self.assertNotIn(api, security)
        self.assertNotIn(security, api)
        self.assertIn("route()", api)
        self.assertNotIn("audit", api.casefold())
        self.assertNotIn("second pass", api.casefold())
        self.assertIn("repository we own", security)
        self.assertIn("executable security", security)
        self.assertNotIn("openapi", security.casefold())
        self.assertNotIn("schemathesis", security.casefold())
        self.assertNotIn("route()", security)

    def test_frontmatter_has_no_permissions_block(self) -> None:
        for path in (API / "SKILL.md", SECURITY / "SKILL.md"):
            text = path.read_text(encoding="utf-8")
            block = text.split("---", 2)[1]
            self.assertNotIn("permissions:", block)
            self.assertIn("license: MIT", block)

    def test_no_vendor_tokens_under_the_skills(self) -> None:
        roots = (API, SECURITY)
        seen = 0
        for root in roots:
            for path in sorted(root.rglob("*")):
                if not path.is_file():
                    continue
                seen += 1
                payload = path.read_bytes()
                for token in FORBIDDEN:
                    self.assertNotIn(token.encode("utf-8"), payload, f"{path} contains {token}")
        self.assertGreaterEqual(seen, 8)

    def test_routers_name_their_modes_and_references(self) -> None:
        api = (API / "SKILL.md").read_text(encoding="utf-8")
        security = (SECURITY / "SKILL.md").read_text(encoding="utf-8")
        pyramid = (SECURITY / "references" / "security-pyramid.md").read_text(encoding="utf-8")
        routing = (ROOT / "packs" / "shaft" / "routing.md").read_text(encoding="utf-8")
        self.assertIn("route(pack_kind, addon_present, denied)", api)
        for name in ("protocols.md", "coverage-matrix.md", "environments.md", "tooling.md"):
            self.assertIn(f"references/{name}", api)
        for mode in ("`audit`", "`executable-tests`", "`active-scan`"):
            self.assertIn(mode, security)
        self.assertIn('returns `authorized`', security)
        self.assertIn("design-only", security)
        self.assertIn("second pass", security)
        self.assertIn("exploit", security)
        self.assertIn("references/security-pyramid.md", security)
        for phrase in (
            "OWASP Top 10 2025",
            "OWASP ASVS 5.0.0",
            "v5.0.0-V",
            "API1",
            "BOLA",
            "API5",
            "BFLA",
            "API7",
            "SSRF",
            "MASVS v2.1.0",
            "MASTG",
            "SP 800-218",
            "Semgrep",
            "FindSecBugs",
            "OSV-Scanner",
            "pip-audit",
            "secret_guard.py",
            "TruffleHog",
            "baseline",
        ):
            self.assertIn(phrase, pyramid)
        for phrase in (
            "shaft-developer",
            "shaft-api-testing",
            "shaft-assertions",
            "shaft-database-testing",
            "shaft-test-data-design",
            "shaft-test-execution",
            "shaft-locator-design",
            "shaft-nonfunctional-test-design",
            "shaft-skills/shaft-developer/SKILL.md",
            ".chaos-engine/addons/shaft-engine-users/shaft-developer/SKILL.md",
            "--with-shaft-engine-users",
            "--without-shaft-engine-users",
            "depth 3",
            "50",
            "build.gradle",
            "Schemathesis",
            "Draft-7",
        ):
            self.assertIn(phrase, routing)


if __name__ == "__main__":
    unittest.main()
