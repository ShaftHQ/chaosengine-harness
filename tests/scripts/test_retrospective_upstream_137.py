"""#137: a retrospective files one upstream harness issue, or cites the open one."""

from __future__ import annotations

import importlib.util
import json
import os
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
REPO = "ShaftHQ/chaosengine-harness"
PROOF = "https://github.com/ShaftHQ/SHAFT_ENGINE/pull/8107"
TEXT = "scan the surviving tip text for committed secrets"


def _load(name: str):
    path = ROOT / "runtime" / f"{name}.py"
    spec = importlib.util.spec_from_file_location(f"ce_{name}_137", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class _Done:
    def __init__(self, stdout: str) -> None:
        self.returncode = 0
        self.stdout = stdout


class RetrospectiveUpstreamTest(unittest.TestCase):
    def setUp(self):
        self.session = _load("learning_session")
        self.calls: list[list[str]] = []

    def _note(self, *, kind: str = "enhancement", surface: str = "rule", proof: str = PROOF) -> str:
        return (
            f"what happened: the gate stayed red after the line was gone\n"
            f"{kind}: {TEXT}\n"
            f"proof: {proof}\n"
            f"surface: {surface}\n"
        )

    def _runner(self, search_stdout: str, create_url: str = ""):
        def runner(argv: list[str]) -> _Done:
            self.calls.append(list(argv))
            if "create" in argv:
                return _Done(create_url + "\n")
            return _Done(search_stdout)

        return runner

    def test_files_on_the_harness_repo_without_implementing(self):
        created = f"https://github.com/{REPO}/issues/201"
        result = self.session.file_abstractable_upstream(
            self._note(),
            runner=self._runner("[]", created),
        )
        self.assertFalse(result["implemented"])
        self.assertEqual("filed", result["action"])
        self.assertEqual(["list", "create"], [call[2] for call in self.calls])
        created_cmd = self.calls[1]
        self.assertEqual(REPO, created_cmd[created_cmd.index("--repo") + 1])
        body = created_cmd[created_cmd.index("--body") + 1]
        self.assertIn(TEXT, body)
        self.assertIn(PROOF, body)
        self.assertIn("rule", body)
        self.assertIn("does not implement", body)
        self.assertEqual(created, result["issues"][0]["url"])

    def test_open_issue_is_cited_and_not_filed_again(self):
        existing = f"https://github.com/{REPO}/issues/120"
        payload = json.dumps(
            [{
                "number": 120,
                "title": "tip scan",
                "url": existing,
                "body": TEXT,
            }]
        )
        result = self.session.file_abstractable_upstream(
            self._note(kind="prevention", surface="playbook"),
            runner=self._runner(payload),
        )
        self.assertEqual("cited", result["action"])
        self.assertFalse(result["implemented"])
        self.assertEqual(["list"], [call[2] for call in self.calls])
        self.assertEqual(existing, result["issues"][0]["url"])
        self.assertNotIn("create", self.calls[0])

    def test_product_note_without_a_harness_surface_files_nothing(self):
        note = f"enhancement: speed up the product indexer\nproof: {PROOF}\n"
        result = self.session.file_abstractable_upstream(note, runner=self._runner("[]"))
        self.assertEqual("none", result["action"])
        self.assertEqual([], self.calls)
        self.assertFalse(result["implemented"])

    def test_finalize_cites_the_filed_issue_and_does_not_implement(self):
        created = f"https://github.com/{REPO}/issues/202"
        note = self._note(surface="memory module") + "\n## Enhancements\nnothing actionable\n"
        with tempfile.TemporaryDirectory() as temporary:
            previous = Path.cwd()
            os.chdir(temporary)
            try:
                receipt = self.session.finalize(
                    "retro-137",
                    disposition="issues-first",
                    extract_heuristics=False,
                    note=note,
                    upstream_runner=self._runner("[]", created),
                )
            finally:
                os.chdir(previous)
        self.assertFalse(receipt["harnessUpstream"]["implemented"])
        self.assertEqual([created], receipt["harnessUpstream"]["urls"])
        self.assertIn(created, receipt["trackingIssues"])
        self.assertEqual("create", self.calls[-1][2])


if __name__ == "__main__":
    unittest.main()
