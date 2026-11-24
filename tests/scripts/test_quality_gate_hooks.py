"""Test quality gate, 8-host guard deny, and pre-done parity (#219)."""

from __future__ import annotations

import importlib.util
import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
SKILL = ROOT / "skills" / "web-e2e-automation"
FORBIDDEN = ("ShaftHQ", "SHAFT_ENGINE")
GAP_HOSTS = frozenset({"grok", "copilot", "cursor", "opencode"})


def load(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def cat(*parts: str) -> str:
    return "".join(parts)


def sleep_call(prefix: str = "time.") -> str:
    return cat(prefix, "sleep(1)")


def sleep_for(seconds: str = "5") -> str:
    return cat("time.", "sleep(", seconds, ")")


def quoted_root(tail: str) -> str:
    return cat("'", "/", "ht", "ml", tail, "'")


def xpath_eq() -> str:
    return cat("xpath=", "/", "ht", "ml")


def by_xpath() -> str:
    return cat("By.xpath(", '"', "/", "ht", "ml")


def locator_call() -> str:
    return cat("locator(", '"', "xpath=", "/", "ht", "ml")


def html_path(tail: str) -> str:
    return cat("/", "ht", "ml", tail)


def find_element_xpath() -> str:
    return cat("find_element(", '"xpath", "', "/", "ht", "ml")


def skip_mark(kind: str = "pytest") -> str:
    if kind == "pytest":
        return cat("@pytest.mark.", "skip")
    if kind == "unittest":
        return cat("@unittest.", "skip")
    if kind == "ignore":
        return cat("@", "Ignore")
    if kind == "disabled":
        return cat("@", "Disabled")
    if kind == "only":
        return cat("it", ".", "only(")
    if kind == "fdescribe":
        return cat("f", "describe(")
    return cat("f", "it(")


def content_call() -> str:
    return cat("page.", "content()")


def xpath_value() -> str:
    return cat("/", "html", "/", "body", "/div")


def deep_css() -> str:
    return " > ".join(list("abcdefg"))


def fn_with(*lines: str) -> str:
    body = "\n".join(lines)
    return f"def test_pays():\n{body}\n"


class QualityGateTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.gate = load(ROOT / "rules" / "test_quality_gate.py", "ce_test_quality_gate_219")
        cls.guard = load(ROOT / "hooks" / "guard.py", "ce_guard_quality_219")
        cls.pre_done = load(ROOT / "runtime" / "pre_done_review.py", "ce_pre_done_quality_219")

    def test_path_matrix(self):
        gate = self.gate
        matched = (
            "tests/foo.py",
            "test/foo.py",
            "e2e/foo.py",
            "pkg/foo_test.py",
            "pkg/test_foo.py",
            "pkg/FooTest.java",
            "pkg/FooSteps.java",
            "pkg/foo_test.go",
            "pkg/foo.spec.ts",
            "pkg/foo.spec.js",
            "pkg/foo.test.ts",
            "pkg/foo.test.js",
            "pkg/FooTests.java",
            "./tests/nested/test_foo.py",
        )
        for path in matched:
            self.assertTrue(gate.is_test_path(path), path)
        for path in (
            "src/app.py",
            "README.md",
            "vendor/tests/test_foo.py",
            "node_modules/pkg/foo.test.js",
            "",
        ):
            self.assertFalse(gate.is_test_path(path), path)

    def _hits(self, text: str, old: str | None = None, path: str = "tests/test_bad.py") -> set[str]:
        report = self.gate.evaluate_content(path, text, old)
        self.assertIn("ok", report)
        self.assertEqual(path, report["path"])
        return {hit["code"] for hit in report["hits"]}

    def test_each_code_is_red_on_a_bad_fixture(self):
        cases = {
            "sleep": fn_with(f"    {sleep_call()}", "    assertEqual(1, 1)"),
            "skip-or-only": f"{skip_mark()}\n" + fn_with("    assertEqual(1, 1)"),
            "silent-swallow": fn_with(
                "    try:",
                "        run()",
                "    except Exception:",
                "        pass",
                "    assertEqual(1, 1)",
            ),
            "full-source": fn_with(f"    html = {content_call()}", "    assertEqual(1, 1)"),
            "absolute-xpath": fn_with(
                f'    el = driver.find_element("xpath", "{xpath_value()}")',
                "    assertEqual(el.text, 'Pay')",
            ),
            "deep-css": fn_with(
                f'    el = page.locator("{deep_css()}")',
                "    assertEqual(1, 1)",
            ),
        }
        for code, text in cases.items():
            with self.subTest(code=code):
                self.assertIn(code, self._hits(text))
                self.assertFalse(self.gate.evaluate_content("tests/test_bad.py", text)["ok"])
        old = fn_with("    assertEqual(1, 1)")
        weakened = fn_with("    assertTrue(True)")
        weakened_hits = self._hits(weakened, old)
        self.assertIn("assertion-weakening", weakened_hits)
        bare = fn_with("    run()")
        self.assertIn("assertion-weakening", self._hits(bare))

    def test_sleep_and_skip_alternates(self):
        for prefix in ("time.", "Thread.", "asyncio."):
            text = fn_with(f"    {sleep_call(prefix)}", "    assertEqual(1, 1)")
            self.assertIn("sleep", self._hits(text), prefix)
        self.assertIn("sleep", self._hits(fn_with(f"    {cat('waitFor', 'Timeout(1000)')}", "    assertEqual(1, 1)")))
        self.assertIn("sleep", self._hits(fn_with(f"    {cat('cy.', 'wait(1)')}", "    assertEqual(1, 1)")))
        for kind in ("pytest", "unittest", "ignore", "disabled", "only", "fdescribe", "fit"):
            line = skip_mark(kind)
            text = f"{line}\n" + fn_with("    assertEqual(1, 1)")
            self.assertIn("skip-or-only", self._hits(text), kind)

    def test_good_fixture_has_no_hits(self):
        text = fn_with('    page.get_by_role("button", name="Pay").click()', "    assertEqual(1, 1)")
        self.assertEqual(set(), self._hits(text))
        self.assertTrue(self.gate.evaluate_content("tests/test_good.py", text)["ok"])

    def test_inline_allow_tokens(self):
        allowed = {
            "sleep": fn_with(
                "    # sleep-justified: frame clock",
                f"    {sleep_call()}",
                "    assertEqual(1, 1)",
            ),
            "sleep-e2e": fn_with(
                f"    {sleep_call()}  # e2e-allow-sleep: clock",
                "    assertEqual(1, 1)",
            ),
            "skip-or-only": f"# skip-justified: upstream\n{skip_mark()}\n" + fn_with("    assertEqual(1, 1)"),
            "silent-swallow": fn_with(
                "    try:",
                "        run()",
                "    except Exception:  # swallow-justified: probe",
                "        pass",
                "    assertEqual(1, 1)",
            ),
            "assertion-weakening": fn_with("    assertTrue(True)  # assertion-justified: bool contract"),
            "missing-assert": "# assert-justified: process launch\n" + fn_with("    run()"),
            "full-source": fn_with(
                f"    html = {content_call()}  # full-source-justified: archive",
                "    assertEqual(1, 1)",
            ),
            "deep-css": fn_with(
                "    # e2e-allow-css: generated grid",
                f'    el = page.locator("{deep_css()}")',
                "    assertEqual(1, 1)",
            ),
        }
        for name, text in allowed.items():
            with self.subTest(name=name):
                hits = self._hits(text)
                if name == "assertion-weakening":
                    old = fn_with("    assertEqual(1, 1)")
                    hits = self._hits(text, old)
                self.assertNotIn(name.split("-")[0] if name == "sleep-e2e" else name, hits)
                if name == "missing-assert":
                    self.assertNotIn("assertion-weakening", hits)

    def test_non_test_paths_are_green(self):
        bad = "\n".join(
            (
                sleep_call(),
                skip_mark(),
                content_call(),
                xpath_value(),
                deep_css(),
                "except Exception:",
                "    pass",
            )
        )
        for path in ("src/app.py", "README.md", "vendor/tests/test_foo.py", "node_modules/pkg/a.test.js"):
            report = self.gate.evaluate_content(path, bad, None)
            self.assertTrue(report["ok"], path)
            self.assertEqual([], report["hits"])

    def test_untouched_legacy_lines_stay_quiet(self):
        legacy = {
            "sleep": fn_with(f"    {sleep_call()}", "    assertEqual(1, 1)"),
            "skip-or-only": f"{skip_mark()}\n" + fn_with("    assertEqual(1, 1)"),
            "silent-swallow": fn_with(
                "    try:",
                "        run()",
                "    except Exception:",
                "        pass",
                "    assertEqual(1, 1)",
            ),
            "full-source": fn_with(f"    html = {content_call()}", "    assertEqual(1, 1)"),
            "absolute-xpath": fn_with(
                f'    el = driver.find_element("xpath", "{xpath_value()}")',
                "    assertEqual(1, 1)",
            ),
            "deep-css": fn_with(f'    el = page.locator("{deep_css()}")', "    assertEqual(1, 1)"),
            "assertion-weakening": fn_with("    assertEqual(1, 1)"),
        }
        for code, old in legacy.items():
            new = old + "# note\n"
            hits = self._hits(new, old)
            self.assertNotIn(code, hits, msg=f"{code}: {hits}")

    def test_edit_and_git_diff_helpers(self):
        path = "tests/test_edit.py"
        report = self.gate.evaluate_edit(
            path,
            "    assertEqual(1, 1)",
            "    " + sleep_call() + "\n    assertEqual(1, 1)",
            None,
        )
        self.assertFalse(report["ok"])
        self.assertIn("sleep", {hit["code"] for hit in report["hits"]})
        diff = "\n".join(
            (
                "diff --git a/tests/test_bad.py b/tests/test_bad.py",
                "new file mode 100644",
                "--- /dev/null",
                "+++ b/tests/test_bad.py",
                "@@ -0,0 +1,3 @@",
                "+def test_pays():",
                "+    " + sleep_call(),
                "+    assertEqual(1, 1)",
            )
        )
        scored = self.gate.evaluate_git_diff(diff)
        self.assertFalse(scored["ok"])
        self.assertIn("sleep", {hit["code"] for hit in scored["hits"]})
        readme = diff.replace("tests/test_bad.py", "README.md")
        self.assertTrue(self.gate.evaluate_git_diff(readme)["ok"])

    def test_skill_contract(self):
        skill = SKILL / "SKILL.md"
        body = skill.read_bytes()
        self.assertLessEqual(len(body), 2100)
        text = body.decode("utf-8")
        self.assertNotIn("permissions:", text)
        prose = []
        grab = False
        for line in text.splitlines():
            if line.startswith("description:"):
                grab = True
                continue
            if grab:
                if line.startswith((" ", "\t")):
                    prose.append(line.strip())
                else:
                    break
        description = " ".join(prose)
        self.assertGreaterEqual(len(description), 100)
        self.assertLessEqual(len(description), 160)
        self.assertIn("name: web-e2e-automation", text)
        self.assertIn("license: MIT", text)
        for relative in (
            "references/locators-dom.md",
            "references/network-console.md",
            "references/playwright.md",
            "references/selenium-bidi.md",
        ):
            self.assertTrue((SKILL / relative).is_file(), relative)
            self.assertIn(relative, text)
        for path in SKILL.rglob("*"):
            if not path.is_file():
                continue
            source = path.read_text(encoding="utf-8")
            folded = source.casefold()
            for token in FORBIDDEN:
                self.assertNotIn(token, source, path)
                self.assertNotIn(token.casefold(), folded, path)

    def test_f2_helpers_docs_and_page_objects_are_not_tests(self):
        gate = self.gate
        noisy = fn_with(f"    {sleep_for()}", "    assertEqual(1, 1)")
        spared = (
            "tests/conftest.py",
            "tests/helpers.py",
            "tests/__init__.py",
            "tests/fixtures/data.json",
            "tests/utils/helper.py",
            "tests/support/flow.py",
            "e2e/pages/LoginPage.ts",
            "e2e/page_objects/LoginPage.ts",
            "tests/README.md",
            "tests/config.yaml",
            "tests/notes.txt",
        )
        for path in spared:
            with self.subTest(path=path):
                self.assertFalse(gate.is_test_path(path), path)
                report = gate.evaluate_content(path, noisy, None)
                self.assertTrue(report["ok"], path)
                self.assertEqual([], report["hits"])
                diff = "\n".join(
                    (
                        f"diff --git a/{path} b/{path}",
                        "new file mode 100644",
                        "--- /dev/null",
                        f"+++ b/{path}",
                        "@@ -0,0 +1,3 @@",
                        "+def test_pays():",
                        "+    " + sleep_for(),
                        "+    assertEqual(1, 1)",
                    )
                )
                findings = self.pre_done.mechanical_problems({"proof_required": False, "diff": diff})
                self.assertFalse(any(item.startswith("test-quality:") for item in findings), findings)
        named = (
            "pkg/FooTests.java",
            "pkg/PayIT.java",
            "pkg/PayTest.kt",
            "pkg/pay_spec.rb",
            "pkg/PayTests.cs",
            "pkg/pay.spec.tsx",
            "pkg/pay.test.mjs",
            "pkg/pay.spec.cjs",
            "pkg/pay.test.jsx",
        )
        for path in named:
            self.assertTrue(gate.is_test_path(path), path)

    def test_f4_weak_assertions_are_downgrades(self):
        gate = self.gate
        strong = fn_with("    assert x == 5")
        for body in (
            "    assert True",
            "    assert 1",
            "    assert not False",
            "    assert flag",
        ):
            with self.subTest(body=body):
                weakened = fn_with(body)
                self.assertIn("assertion-weakening", self._hits(weakened, strong))
                self.assertFalse(gate.evaluate_content("tests/test_bad.py", weakened, strong)["ok"])
        justified = fn_with("    assert True  # assertion-justified: contract")
        self.assertNotIn("assertion-weakening", self._hits(justified, strong))
        self.assertTrue(
            gate.evaluate_content(
                "tests/test_ok.py",
                fn_with("    assert 1 + 1 == 2"),
                fn_with("    assert 1 == 1"),
            )["ok"]
        )
        self.assertTrue(
            gate.evaluate_content(
                "tests/test_ok.py",
                fn_with("    assert fn(x)"),
                strong,
            )["ok"]
        )
        self.assertTrue(
            gate.evaluate_content(
                "tests/test_ok.py",
                fn_with("    assert a in b"),
                strong,
            )["ok"]
        )
        script = "pkg/pay.test.js"
        before = "expect(res.status).toBe(200)\n"
        for matcher in ("toBeTruthy", "toBeFalsy", "toBeNull", "toBeUndefined", "toBeNullish", "toBeDefined"):
            after = f"expect(res.status).{matcher}()\n"
            with self.subTest(matcher=matcher):
                report = gate.evaluate_content(script, after, before)
                self.assertFalse(report["ok"])
                self.assertIn("assertion-weakening", {hit["code"] for hit in report["hits"]})
        kept = gate.evaluate_content(script, "expect(a).toEqual(1)\n", "expect(a).toBe(1)\n")
        self.assertTrue(kept["ok"], kept)
        excused = "expect(res.status).toBeTruthy()  # assertion-justified: probe\n"
        self.assertTrue(gate.evaluate_content(script, excused, before)["ok"])

    def test_f8_html_urls_are_not_xpath(self):
        gate = self.gate
        for label, line in (
            ("report", f"    client.get({quoted_root('/report')})"),
            ("index", f"    page = {quoted_root('/index.html')}"),
            ("bare-head", f"    el = {quoted_root('/head')}"),
            ("bare-div", f"    el = {quoted_root('/div')}"),
            ("bare-predicate", f"    el = {quoted_root('[')}"),
            ("id-report", f"    driver.find_element('id', {quoted_root('/report')})"),
            (
                "css-report",
                f"    driver.find_element('css selector', \"a[href={quoted_root('/report')}]\")",
            ),
            ("goto", f"    page.goto('https://example.com{html_path('/report')}')"),
        ):
            text = fn_with(line, "    assertEqual(1, 1)")
            with self.subTest(label=label):
                self.assertNotIn("absolute-xpath", self._hits(text))
                self.assertTrue(gate.evaluate_content("tests/test_url.py", text)["ok"])
        for label, line in (
            ("body", f"    el = {quoted_root('/body')}"),
            ("head", f"    el = By.xpath({quoted_root('/head')})"),
            ("div", f"    el = find_element('xpath', {quoted_root('/div')})"),
            ("predicate", f"    el = {xpath_eq()}["),
            ("xpath-eq", f"    el = {xpath_eq()}"),
            ("by-xpath", f"    el = {by_xpath()}"),
            ("locator", f"    el = {locator_call()}"),
            ("find-element", f"    el = {find_element_xpath()}"),
        ):
            text = fn_with(line, "    assertEqual(1, 1)")
            with self.subTest(label=label):
                self.assertIn("absolute-xpath", self._hits(text), text)

    def test_f2_comments_do_not_change_assertion_counts(self):
        gate = self.gate
        commented = "assert x == 5  # .toBeTruthy was rejected\n"
        self.assertEqual((1, 0), gate._counts(commented)[:2])
        self.assertEqual((1, 0), gate._counts("assert x == 5  // .toBeTruthy was rejected\n")[:2])
        self.assertEqual((1, 0), gate._counts("assert x == 5 /* .toBeTruthy() */\n")[:2])
        self.assertEqual((0, 0), gate._counts("# assert x == 5\n")[:2])
        self.assertEqual((0, 0), gate._counts("// assert x == 5\n")[:2])
        self.assertEqual((0, 0), gate._counts("/* assert x == 5 */\n")[:2])
        self.assertEqual((1, 0), gate._counts("assert 4 // 2 == 2\n")[:2])
        self.assertEqual((1, 0), gate._counts("assert x // y == 1\n")[:2])
        preserved = "note = \"# .toBeTruthy was rejected\"\n"
        self.assertEqual(1, gate._counts(preserved)[1])
        same = "expect(res.status).toBe(200); expect(res.ok).toBeTruthy()\n"
        split = "expect(res.status).toBe(200)\nexpect(res.ok).toBeTruthy()\n"
        self.assertEqual(gate._counts(same), gate._counts(split))
        self.assertEqual((1, 1), gate._counts(same)[:2])
        old = fn_with("    assert x == 5")
        kept = fn_with("    assert x == 5  # .toBeTruthy was rejected")
        self.assertTrue(gate.evaluate_content("tests/test_ok.py", kept, old)["ok"])
        removed = fn_with("    # assert x == 5")
        report = gate.evaluate_content("tests/test_bad.py", removed, old)
        self.assertFalse(report["ok"])
        self.assertIn("assertion-weakening", {hit["code"] for hit in report["hits"]})
        script = "pkg/pay.test.js"
        before = "expect(res.status).toBe(200)\nexpect(res.ok).toBeTruthy()\n"
        after = "expect(res.status).toBe(200); expect(res.ok).toBeTruthy()\n"
        self.assertTrue(gate.evaluate_content(script, after, before)["ok"])

    def test_f3_f12_test_filename_beats_helper_directories(self):
        gate = self.gate
        matched = (
            "e2e/pages/login.spec.ts",
            "e2e/Pages/login.spec.ts",
            "tests/utils/test_login.py",
            "tests/support/flow.spec.ts",
            "tests/fixtures/test_login.py",
            "tests/fixtures/test_data.py",
            "tests/helpers/test_common.py",
            "tests/foo.py",
        )
        for path in matched:
            self.assertTrue(gate.is_test_path(path), path)
        spared = (
            "tests/helpers/common.py",
            "tests/Helpers/common.py",
            "tests/helper.py",
            "tests/Helper.py",
            "e2e/page-objects/LoginPage.ts",
            "e2e/pageobjects/LoginPage.ts",
            "e2e/PageObjects/LoginPage.ts",
            "tests/conftest.py",
            "tests/fixtures/data.json",
            "tests/README.md",
            "vendor/tests/test_foo.py",
            "Vendor/tests/test_foo.py",
            "node_modules/pkg/foo.test.js",
        )
        noisy = fn_with(f"    {sleep_for()}", "    assertEqual(1, 1)")
        for path in spared:
            with self.subTest(path=path):
                self.assertFalse(gate.is_test_path(path), path)
                self.assertTrue(gate.evaluate_content(path, noisy, None)["ok"])
        flagged = gate.evaluate_content("tests/fixtures/test_data.py", noisy, None)
        self.assertFalse(flagged["ok"])
        self.assertIn("sleep", {hit["code"] for hit in flagged["hits"]})
        diff = "\n".join(
            (
                "diff --git a/tests/fixtures/test_data.py b/tests/fixtures/test_data.py",
                "new file mode 100644",
                "--- /dev/null",
                "+++ b/tests/fixtures/test_data.py",
                "@@ -0,0 +1,3 @@",
                "+def test_pays():",
                "+    " + sleep_for(),
                "+    assertEqual(1, 1)",
            )
        )
        findings = self.pre_done.mechanical_problems({"proof_required": False, "diff": diff})
        self.assertTrue(any(item.startswith("test-quality:") for item in findings), findings)

    def test_f4_xpath_needs_body_or_locator_context(self):
        gate = self.gate
        quiet = (
            f"    driver.find_element('id', {quoted_root('/report')})",
            f"    driver.find_element('css selector', \"a[href={quoted_root('/report')}]\")",
            f"    client.get({quoted_root('/report')})",
            f"    page.goto('https://example.com{html_path('/report')}')",
            f"    el = {quoted_root('/head')}",
            f"    locator({quoted_root('/report')})",
        )
        for line in quiet:
            text = fn_with(line, "    assertEqual(1, 1)")
            self.assertNotIn("absolute-xpath", self._hits(text), text)
            self.assertTrue(gate.evaluate_content("tests/test_url.py", text)["ok"], text)
        loud = (
            f"    el = {quoted_root('/body')}",
            f"    el = find_element(By.XPATH, {quoted_root('/head')})",
            f"    el = find_element('xpath', {quoted_root('/report')})",
            f"    el = find_element(\"xpath\", {quoted_root('/report')})",
            f"    el = {locator_call()}",
            f"    el = {xpath_eq()}",
            f"    el = {by_xpath()}",
        )
        for line in loud:
            text = fn_with(line, "    assertEqual(1, 1)")
            self.assertIn("absolute-xpath", self._hits(text), text)

    def test_f7_parenthesized_and_negated_bare_asserts_are_weak(self):
        gate = self.gate
        strong = fn_with("    assert x == 5")
        for body in (
            "    assert (True)",
            "    assert ((flag))",
            "    assert not flag",
            "    assert (not flag)",
            "    assert not False",
            "    assert 1",
            "    assert flag",
        ):
            with self.subTest(body=body):
                weakened = fn_with(body)
                self.assertIn("assertion-weakening", self._hits(weakened, strong))
                self.assertFalse(gate.evaluate_content("tests/test_bad.py", weakened, strong)["ok"])
        for body in (
            "    assert x == 6",
            "    assert a in b",
            "    assert fn(x)",
            "    assert len(xs) > 0",
            "    assert (x == 5)",
        ):
            with self.subTest(body=body):
                self.assertTrue(
                    gate.evaluate_content("tests/test_ok.py", fn_with(body), strong)["ok"],
                    body,
                )

    def test_f8_to_be_true_false_empty_are_weak(self):
        gate = self.gate
        script = "pkg/pay.test.js"
        before = "expect(res.status).toBe(200)\n"
        for matcher in ("toBeTrue", "toBeFalse", "toBeEmpty"):
            after = f"expect(res.status).{matcher}()\n"
            with self.subTest(matcher=matcher):
                report = gate.evaluate_content(script, after, before)
                self.assertFalse(report["ok"])
                self.assertIn("assertion-weakening", {hit["code"] for hit in report["hits"]})
        kept = gate.evaluate_content(script, "expect(a).toEqual(1)\n", before)
        self.assertTrue(kept["ok"], kept)


class GuardParityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.guard = load(ROOT / "hooks" / "guard.py", "ce_guard_quality_219")

    def _block(self, event_name: str, tool_name: str, tool_input: dict, host: str = "claude"):
        event = {"hook_event_name": event_name, "cwd": str(ROOT), "session_id": "ws3"}
        buffer = io.StringIO()
        with redirect_stdout(buffer):
            code = self.guard._test_quality_block(event, event_name, tool_name, tool_input, host)
        return code, buffer.getvalue()

    def test_direct_block_denies_only_test_writes(self):
        bad = {
            "file_path": "tests/test_bad.py",
            "content": fn_with(f"    {sleep_call()}", "    assertEqual(1, 1)"),
        }
        code, rendered = self._block("PreToolUse", "Write", bad)
        self.assertEqual(2, code)
        self.assertIn("Test quality gate", rendered)
        self.assertIn("sleep", rendered)
        good = {
            "file_path": "tests/test_good.py",
            "content": fn_with("    assertEqual(1, 1)"),
        }
        self.assertIsNone(self._block("PreToolUse", "Write", good)[0])
        allowed = {
            "file_path": "tests/test_bad.py",
            "content": fn_with("    # sleep-justified: clock", f"    {sleep_call()}", "    assertEqual(1, 1)"),
        }
        self.assertIsNone(self._block("PreToolUse", "Write", allowed)[0])
        other = {"file_path": "src/app.py", "content": sleep_call()}
        self.assertIsNone(self._block("PreToolUse", "Write", other)[0])
        self.assertIsNone(self._block("PostToolUse", "Write", bad)[0])
        self.assertIsNone(self._block("PreToolUse", "Bash", {"command": sleep_call()})[0])
        edit = {
            "file_path": "e2e/test_flow.py",
            "old_string": "    assertEqual(1, 1)",
            "new_string": "    " + sleep_call() + "\n    assertEqual(1, 1)",
        }
        self.assertEqual(2, self._block("PreToolUse", "Edit", edit)[0])

    def test_missing_module_fails_open(self):
        missing = Path("/tmp/ce-missing-test-quality-gate.py")
        event = {"hook_event_name": "PreToolUse", "cwd": str(ROOT)}
        tool_input = {"file_path": "tests/test_bad.py", "content": sleep_call()}
        previous = getattr(self.guard._test_quality_api, "module", None)
        self.guard._test_quality_api.module = None
        try:
            with mock.patch.object(self.guard, "_test_quality_path", return_value=missing):
                self.assertIsNone(
                    self.guard._test_quality_block(event, "PreToolUse", "Write", tool_input, "claude")
                )
        finally:
            self.guard._test_quality_api.module = previous

    def _run(
        self,
        host: str,
        tool_name: str,
        tool_input: dict,
        cwd: str | None = None,
    ) -> subprocess.CompletedProcess[str]:
        payload = {
            "hook_event_name": "PreToolUse",
            "session_id": "ws3-quality",
            "cwd": cwd or str(ROOT),
            "tool_name": tool_name,
            "tool_input": tool_input,
        }
        env = os.environ.copy()
        env["CHAOS_ENGINE_HOST"] = host
        env.pop("GROK_HOOK_EVENT", None)
        return subprocess.run(
            [sys.executable, str(ROOT / "hooks" / "guard.py")],
            input=json.dumps(payload),
            capture_output=True,
            text=True,
            env=env,
            cwd=str(ROOT),
            check=False,
        )

    @staticmethod
    def _payload(completed: subprocess.CompletedProcess[str], host: str) -> dict:
        text = completed.stderr if host == "claude" else completed.stdout
        for line in reversed(text.splitlines()):
            line = line.strip()
            if not line:
                continue
            try:
                value = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(value, dict):
                return value
        return {}

    @staticmethod
    def _reason(payload: dict) -> str:
        chunks: list[str] = []
        for key in ("reason", "permissionDecisionReason", "user_message", "agent_message"):
            value = payload.get(key)
            if isinstance(value, str):
                chunks.append(value)
        specific = payload.get("hookSpecificOutput")
        if isinstance(specific, dict):
            for key in ("permissionDecisionReason", "additionalContext"):
                value = specific.get(key)
                if isinstance(value, str):
                    chunks.append(value)
        return "\n".join(chunks)

    @staticmethod
    def _denied(payload: dict) -> bool:
        if payload.get("decision") in {"block", "deny"}:
            return True
        if payload.get("permissionDecision") == "deny" or payload.get("permission") == "deny":
            return True
        specific = payload.get("hookSpecificOutput")
        return isinstance(specific, dict) and specific.get("permissionDecision") == "deny"

    def test_hosts_deny_a_bad_test_write(self):
        tool_input = {
            "file_path": "tests/test_bad.py",
            "content": fn_with(f"    {sleep_call()}", "    assertEqual(1, 1)"),
        }
        expected_exit = {
            "claude": 2,
            "codex": 2,
            "gemini": 2,
            "grok": 2,
            "copilot": 2,
            "cursor": 2,
            "opencode": 2,
            "antigravity": 0,
        }
        for host, code in expected_exit.items():
            with self.subTest(host=host):
                completed = self._run(host, "Write", tool_input)
                self.assertEqual(code, completed.returncode, completed.stderr)
                payload = self._payload(completed, host)
                self.assertTrue(self._denied(payload), payload)
                reason = self._reason(payload)
                self.assertIn("Test quality gate", reason)
                self.assertIn("sleep", reason)
                if host in GAP_HOSTS:
                    self.assertIn("GAP-EXIT2", reason)
                else:
                    self.assertNotIn("GAP-EXIT2", reason)
                if host == "antigravity":
                    self.assertEqual("deny", payload.get("decision"))
                if host == "cursor":
                    self.assertEqual("deny", payload.get("permission"))
                    self.assertIn("GAP-EXIT2", payload.get("user_message", ""))
                    self.assertIn("GAP-EXIT2", payload.get("agent_message", ""))
                if host == "copilot":
                    self.assertEqual("deny", payload.get("permissionDecision"))
                if host == "claude":
                    self.assertEqual("block", payload.get("decision"))

    def test_host_allows_a_non_test_and_a_clean_test(self):
        """A covered impact receipt still allows non-tests and clean tests."""
        with tempfile.TemporaryDirectory() as temporary:
            project = Path(temporary)
            (project / ".chaos-engine").mkdir()
            (project / ".chaos-engine" / "install.py").write_text("# marker\n", encoding="utf-8")
            state = project / ".chaos-engine-state"
            state.mkdir()
            (state / "research-receipt.md").write_text("retrieve: used\n", encoding="utf-8")
            cwd = str(project)
            noisy = self._run(
                "claude",
                "Write",
                {"file_path": "src/app.py", "content": sleep_call()},
                cwd=cwd,
            )
            blob = noisy.stdout + noisy.stderr
            self.assertNotIn("Test quality gate", blob)
            self.assertEqual(0, noisy.returncode, blob)
            self.assertFalse(self._denied(self._payload(noisy, "claude")))
            clean = self._run(
                "grok",
                "Write",
                {"file_path": "tests/test_good.py", "content": fn_with("    assertEqual(1, 1)")},
                cwd=cwd,
            )
            clean_blob = clean.stdout + clean.stderr
            self.assertNotIn("Test quality gate", clean_blob)
            self.assertEqual(0, clean.returncode, clean_blob)
            self.assertNotIn("GAP-EXIT2", clean_blob)

    def _covered_project(self, root: Path) -> None:
        (root / ".chaos-engine").mkdir()
        (root / ".chaos-engine" / "install.py").write_text("# marker\n", encoding="utf-8")
        state = root / ".chaos-engine-state"
        state.mkdir()
        (state / "research-receipt.md").write_text("retrieve: used\n", encoding="utf-8")

    def _deny_payload(self, host: str, tool_name: str, tool_input: dict, cwd: str | None = None) -> dict:
        completed = self._run(host, tool_name, tool_input, cwd=cwd)
        self.assertEqual(0 if host == "antigravity" else 2, completed.returncode, completed.stdout + completed.stderr)
        payload = self._payload(completed, host)
        self.assertTrue(self._denied(payload), payload)
        if host == "antigravity":
            self.assertEqual("deny", payload.get("decision"))
        self.assertIn("Test quality gate", self._reason(payload))
        return payload

    def test_f1_antigravity_edit_keys_and_unrecognized_payload(self):
        sleep = "    " + sleep_for() + "\n    assertEqual(1, 1)"
        edit = {
            "Path": "tests/test_new.py",
            "Target": "    assertEqual(1, 1)",
            "Replacement": sleep,
        }
        self._deny_payload("antigravity", "edit_file", edit)
        replace = {
            "TargetFile": "tests/test_new.py",
            "TargetContent": "    assertEqual(1, 1)",
            "ReplacementContent": "    value = 1",
        }
        payload = self._deny_payload("antigravity", "replace_file_content", replace)
        self.assertIn("assertion-weakening", self._reason(payload))
        chunks = {
            "TargetFile": "tests/test_new.py",
            "ReplacementChunks": [
                {
                    "TargetContent": "    assertEqual(1, 1)",
                    "ReplacementContent": sleep,
                }
            ],
        }
        self._deny_payload("antigravity", "multi_replace_file_content", chunks)
        with tempfile.TemporaryDirectory() as temporary:
            project = Path(temporary)
            self._covered_project(project)
            target = project / "tests" / "test_new.py"
            target.parent.mkdir(parents=True)
            target.write_text(fn_with("    assertEqual(1, 1)"), encoding="utf-8")
            cwd = str(project)
            kept = self._run(
                "antigravity",
                "edit_file",
                {
                    "Path": "tests/test_new.py",
                    "Target": "    assertEqual(1, 1)",
                    "Replacement": "    assertEqual(2, 2)",
                },
                cwd=cwd,
            )
            kept_blob = kept.stdout + kept.stderr
            self.assertEqual(0, kept.returncode, kept_blob)
            self.assertFalse(self._denied(self._payload(kept, "antigravity")), kept_blob)
            self.assertNotIn("Test quality gate", kept_blob)
            mystery = self._run(
                "antigravity",
                "Edit",
                {"file_path": "tests/test_new.py", "mystery": "nope"},
                cwd=cwd,
            )
            mystery_blob = mystery.stdout + mystery.stderr
            self.assertEqual(0, mystery.returncode, mystery_blob)
            self.assertFalse(self._denied(self._payload(mystery, "antigravity")), mystery_blob)
            self.assertNotIn("Test quality gate", mystery_blob)
            direct = self._block(
                "PreToolUse",
                "Edit",
                {"file_path": "tests/test_new.py", "mystery": "nope"},
            )
            self.assertIsNone(direct[0])

    def test_f3_write_to_file_and_apply_patch(self):
        bad_write = {
            "TargetFile": "tests/test_bad.py",
            "CodeContent": fn_with(f"    {sleep_for()}", "    assertEqual(1, 1)"),
        }
        self._deny_payload("antigravity", "write_to_file", bad_write)
        clean_body = fn_with("    assertEqual(1, 1)")
        with tempfile.TemporaryDirectory() as temporary:
            project = Path(temporary)
            self._covered_project(project)
            cwd = str(project)
            clean = self._run(
                "antigravity",
                "write_to_file",
                {"TargetFile": "tests/test_good.py", "CodeContent": clean_body},
                cwd=cwd,
            )
            blob = clean.stdout + clean.stderr
            self.assertEqual(0, clean.returncode, blob)
            self.assertFalse(self._denied(self._payload(clean, "antigravity")), blob)
            self.assertNotIn("Test quality gate", blob)
        sleep_line = "+    " + sleep_for()
        bad_patch = "\n".join(
            (
                "*** Begin Patch",
                "*** Add File: tests/test_new.py",
                "+def test_pays():",
                sleep_line,
                "+    assertEqual(1, 1)",
                "*** End Patch",
            )
        )
        clean_patch = "\n".join(
            (
                "*** Begin Patch",
                "*** Add File: tests/test_new.py",
                "+def test_pays():",
                "+    assertEqual(1, 1)",
                "*** End Patch",
            )
        )
        for key in ("input", "patch", "diff"):
            with self.subTest(key=key):
                denied = self._run("codex", "apply_patch", {key: bad_patch})
                denied_blob = denied.stdout + denied.stderr
                self.assertEqual(2, denied.returncode, denied_blob)
                payload = self._payload(denied, "codex")
                self.assertTrue(self._denied(payload), payload)
                self.assertIn("Test quality gate", self._reason(payload))
                self.assertIn("sleep", self._reason(payload))
        with tempfile.TemporaryDirectory() as temporary:
            project = Path(temporary)
            self._covered_project(project)
            allowed = self._run(
                "codex",
                "apply_patch",
                {"input": clean_patch},
                cwd=str(project),
            )
            allowed_blob = allowed.stdout + allowed.stderr
            self.assertEqual(0, allowed.returncode, allowed_blob)
            self.assertFalse(self._denied(self._payload(allowed, "codex")), allowed_blob)
            self.assertNotIn("Test quality gate", allowed_blob)

    def test_f1_write_without_content_does_not_score_the_existing_file(self):
        self.assertNotIn("newString", self.guard._QUALITY_WRITE_KEYS)
        with tempfile.TemporaryDirectory() as temporary:
            project = Path(temporary)
            target = project / "tests" / "test_keep.py"
            target.parent.mkdir(parents=True)
            target.write_text(fn_with("    assertEqual(1, 1)"), encoding="utf-8")
            event = {"hook_event_name": "PreToolUse", "cwd": str(project), "session_id": "f1"}
            missing = {"file_path": "tests/test_keep.py"}
            self.assertIsNone(
                self.guard._test_quality_block(event, "PreToolUse", "Write", missing, "claude")
            )
            camel = {"TargetFile": "tests/test_keep.py", "newString": "    " + sleep_for()}
            self.assertIsNone(
                self.guard._test_quality_block(event, "PreToolUse", "write_to_file", camel, "claude")
            )
            bad = {
                "file_path": "tests/test_keep.py",
                "content": fn_with(f"    {sleep_for()}", "    assertEqual(1, 1)"),
            }
            self.assertEqual(
                2, self.guard._test_quality_block(event, "PreToolUse", "Write", bad, "claude")
            )

    def test_f6_camel_case_and_chunk_arrays_score_edits(self):
        self.assertIn("oldString", self.guard._QUALITY_OLD_KEYS)
        self.assertIn("newString", self.guard._QUALITY_NEW_KEYS)
        self.assertNotIn("newString", self.guard._QUALITY_WRITE_KEYS)
        bad_new = "    " + sleep_for() + "\n    assertEqual(1, 1)"
        clean = {
            "filePath": "tests/test_new.py",
            "old_string": "assertEqual(1, 1)",
            "newString": "assertEqual(2, 2)",
        }
        self.assertIsNone(self._block("PreToolUse", "Edit", clean)[0])
        denied = (
            {
                "filePath": "tests/test_new.py",
                "oldString": "    assertEqual(1, 1)",
                "newString": bad_new,
            },
            {
                "filePath": "tests/test_new.py",
                "replacements": [
                    {"old_string": "    assertEqual(1, 1)", "new_string": bad_new},
                ],
            },
            {
                "filePath": "tests/test_new.py",
                "replacementChunks": [
                    {"oldString": "    assertEqual(1, 1)", "newString": bad_new},
                ],
            },
            {
                "filePath": "tests/test_new.py",
                "ReplacementChunks": [
                    {
                        "old_string": "    assertEqual(1, 1)",
                        "newString": bad_new,
                    }
                ],
            },
            {
                "TargetFile": "tests/test_new.py",
                "replacements": [
                    {"TargetContent": "    assertEqual(1, 1)", "ReplacementContent": bad_new},
                ],
            },
        )
        for payload in denied:
            with self.subTest(payload=sorted(payload)):
                code, rendered = self._block("PreToolUse", "Edit", payload)
                self.assertEqual(2, code, rendered)
                self.assertIn("sleep", rendered)


class PreDoneParityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.pre_done = load(ROOT / "runtime" / "pre_done_review.py", "ce_pre_done_quality_219")

    def _diff(self, path: str, line: str) -> str:
        return "\n".join(
            (
                f"diff --git a/{path} b/{path}",
                "new file mode 100644",
                "--- /dev/null",
                f"+++ b/{path}",
                "@@ -0,0 +1,3 @@",
                "+def test_pays():",
                "+    " + line,
                "+    assertEqual(1, 1)",
            )
        )

    def test_gate_json_matches_hook_findings(self):
        bad = self._diff("tests/test_bad.py", sleep_call())
        findings = self.pre_done.mechanical_problems({"proof_required": False, "diff": bad})
        self.assertTrue(any(item.startswith("test-quality:sleep:") for item in findings), findings)
        clean = self._diff("tests/test_good.py", 'assertEqual(1, 1)  # kept')
        # The helper always inserts an assertion line too, so use a hand diff.
        clean = "\n".join(
            (
                "diff --git a/tests/test_good.py b/tests/test_good.py",
                "new file mode 100644",
                "--- /dev/null",
                "+++ b/tests/test_good.py",
                "@@ -0,0 +1,2 @@",
                "+def test_pays():",
                "+    assertEqual(1, 1)",
            )
        )
        self.assertFalse(
            any(item.startswith("test-quality:") for item in self.pre_done.mechanical_problems(
                {"proof_required": False, "diff": clean}
            ))
        )
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "obs.json"
            path.write_text(json.dumps({"proof_required": False, "diff": bad}), encoding="utf-8")
            completed = subprocess.run(
                [sys.executable, str(ROOT / "runtime" / "pre_done_review.py"), "--gate", str(path)],
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(1, completed.returncode, completed.stderr)
            self.assertIn("test-quality:sleep:", completed.stdout)

    def test_working_tree_untracked_test_is_scored(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            subprocess.run(["git", "init"], cwd=root, check=True, capture_output=True)
            target = root / "tests" / "test_new.py"
            target.parent.mkdir(parents=True)
            target.write_text(fn_with(f"    {sleep_call()}", "    assertEqual(1, 1)"), encoding="utf-8")
            findings = self.pre_done.mechanical_problems({"proof_required": False, "project_root": str(root)})
            self.assertTrue(any(item.startswith("test-quality:sleep:") for item in findings), findings)


if __name__ == "__main__":
    unittest.main()
