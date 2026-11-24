"""#230: ``assert not (atom)`` is a weak assertion; other ``not`` operands stay strong."""

from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def load(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def fn_with(body: str) -> str:
    return f"def test_pays():\n    {body}\n"


class ParenthesizedNotAtomTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.gate = load(ROOT / "rules" / "test_quality_gate.py", "ce_test_quality_gate_230")

    def _codes(self, text: str, old: str) -> set[str]:
        report = self.gate.evaluate_content("tests/test_bad.py", text, old)
        return {hit["code"] for hit in report["hits"]}

    def test_parenthesized_not_atom_is_weak(self) -> None:
        strong = fn_with("assert x == 5")
        for body in (
            "assert not (flag)",
            "assert not ((flag))",
            "assert (not (flag))",
            "assert not(flag)",
            "assert not ( flag )",
        ):
            with self.subTest(body=body):
                report = self.gate.evaluate_content("tests/test_bad.py", fn_with(body), strong)
                self.assertFalse(report["ok"])
                self.assertIn("assertion-weakening", {hit["code"] for hit in report["hits"]})

    def test_parenthesized_not_expression_stays_strong(self) -> None:
        strong = fn_with("assert x == 5")
        for body in (
            "assert not (x == 5)",
            "assert not (fn(x))",
            "assert not (a and b)",
            "assert not (flag) and other",
            "assert not not flag",
        ):
            with self.subTest(body=body):
                text = fn_with(body)
                report = self.gate.evaluate_content("tests/test_ok.py", text, strong)
                self.assertNotIn("assertion-weakening", self._codes(text, strong))
                self.assertTrue(report["ok"], report)


if __name__ == "__main__":
    unittest.main()
