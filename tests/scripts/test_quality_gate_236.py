"""#236: Java and Kotlin bodies, page-object calls, and the assert-justified hint."""

from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


JAVA_JUSTIFIED = """
class LoginTest {
    @Test
    public void testFoo() {
        // assert-justified: delegated to page object
        openLogin();
    }
}
"""

JAVA_PAGE = """
class LoginTest {
    @Test
    public void testFoo() {
        page.verifyLogin();
    }
}
"""

KOTLIN_PAGE = """
class CartTest {
    @Test
    fun testTotal() {
        page.checkTotal()
        homePage.assertHeaderVisible()
    }
}
"""

KOTLIN_EXPRESSION_BODY_BLEED = """
class CartTest {
    @Test
    fun testFirst() = openCart()

    @Test
    fun testSecond() {
      assertTrue(true)
    }
}
"""

KOTLIN_EXPRESSION_BODY_ASSERTED = """
class CartTest {
    @Test
    fun testFirst() = assertTrue(true)
}
"""

JAVA_BARE = """
class LoginTest {
    @Test
    public void testFoo() {
        openLogin();
    }
}
"""


class JavaKotlinAssertionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.gate = load("ce_quality_236", ROOT / "rules" / "test_quality_gate.py")
        cls.guard = load("ce_guard_236", ROOT / "hooks" / "guard.py")

    def _report(self, path: str, text: str):
        return self.gate.evaluate_content(path, text, "")

    def test_assert_justified_inside_java_body_passes(self):
        report = self._report("tests/LoginTest.java", JAVA_JUSTIFIED)
        self.assertNotIn("assertion-weakening", {hit["code"] for hit in report["hits"]})
        self.assertTrue(report["ok"], report)

    def test_page_object_verify_calls_pass(self):
        for path, text in (
            ("tests/LoginTest.java", JAVA_PAGE),
            ("tests/CartTest.kt", KOTLIN_PAGE),
        ):
            with self.subTest(path=path):
                report = self._report(path, text)
                self.assertNotIn("assertion-weakening", {hit["code"] for hit in report["hits"]}, report)
                self.assertTrue(report["ok"], report)

    def test_java_without_assertion_or_token_fails(self):
        report = self._report("tests/LoginTest.java", JAVA_BARE)
        self.assertFalse(report["ok"])
        details = " ".join(hit["detail"] for hit in report["hits"])
        self.assertIn("assert-justified:", details)
        self.assertIn("inside the test body", details)
        self.assertEqual(1, sum(1 for hit in report["hits"] if hit["code"] == "assertion-weakening"))

    def test_kotlin_expression_body_does_not_absorb_the_next_test(self):
        report = self._report("tests/CartTest.kt", KOTLIN_EXPRESSION_BODY_BLEED)
        self.assertFalse(report["ok"])
        self.assertTrue(any(hit["line"] == 3 for hit in report["hits"]), report)

    def test_kotlin_expression_body_assertion_passes(self):
        report = self._report("tests/CartTest.kt", KOTLIN_EXPRESSION_BODY_ASSERTED)
        self.assertTrue(report["ok"], report)

    def test_block_message_names_the_token_and_position(self):
        reason = self.guard._quality_reason({"path": "tests/LoginTest.java", "hits": []})
        self.assertIn("assert-justified:", reason)
        self.assertIn("above the test or annotation", reason)
        self.assertIn("inside the test body", reason)
        self.assertIn("# assert-justified:", reason)
        self.assertIn("// assert-justified:", reason)


if __name__ == "__main__":
    unittest.main()
