"""P0 retrieve eval: 60 frozen path:line questions and the K1/K2/K3 arms.

The measured routers are the two entries already in runtime/retrieve.py.
retrieve_py forces the one-store pick_store path. router_v2 is classify_scope
via retrieve() with no store. This test does not add a router.
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
QUESTIONS = ROOT / "experiments" / "retrieve-router" / "questions.json"
SCORE = ROOT / "experiments" / "retrieve-router" / "score.py"
KIND_COUNTS = {"structural": 20, "history": 15, "gotcha": 10, "conceptual": 15}


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def _canonical_questions(questions: list) -> bytes:
    return json.dumps(questions, indent=2, sort_keys=True).encode("utf-8")


class FrozenRetrieveP0Test(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.score = _load("ce_retrieve_router_p0_score", SCORE)
        cls.retrieve = cls.score.RETRIEVE

    def test_sixty_real_questions_and_k_arms(self):
        raw = QUESTIONS.read_bytes()
        payload = json.loads(raw)
        questions = payload["questions"]
        real, dropped = self._real_questions(questions)
        self.assertEqual(0, dropped, "unresolved gold path:line")
        self.assertEqual(60, len(real))
        counts: dict[str, int] = {}
        no_rare = 0
        for item in real:
            counts[item["kind"]] = counts.get(item["kind"], 0) + 1
            route = self.retrieve.classify_scope(item["question"])
            self.assertEqual(item["gold_route"], route["reason"], item["id"])
            gold = item["gold"][0]
            line = (ROOT / gold["path"]).read_text(encoding="utf-8").splitlines()[gold["line"] - 1]
            blob = f"{gold['path']} {line}"
            self.assertEqual(bool(item["implicit"]), self.retrieve.implicit_clue(item["question"], blob), item["id"])
            if not self.retrieve.question_rare_tokens(item["question"]):
                no_rare += 1
                self.assertTrue(item["implicit"], item["id"])
        self.assertEqual(KIND_COUNTS, counts)
        self.assertGreaterEqual(no_rare, 10)
        digest = hashlib.sha256(_canonical_questions(questions)).hexdigest()
        self.assertEqual(digest, payload["frozen_questions_sha256"])
        self.assertTrue(hasattr(self.retrieve, "classify_scope"))
        before = QUESTIONS.read_bytes()
        result = self.score.evaluate()
        self.assertEqual(before, QUESTIONS.read_bytes())
        self.assertEqual(60, result["questions"])
        self.assertGreaterEqual(result["implicit_questions"], 10)
        recall = result["recall_at_5"]
        self.assertIn("no_retrieve", recall)
        self.assertIn("oracle", recall)
        self.assertEqual(0.0, recall["no_retrieve"])
        self.assertEqual(1.0, recall["oracle"])
        for name in ("retrieve_py", "router_v2"):
            arm = result["arms"][name]
            self.assertIn("recall_at_5", arm)
            self.assertIn("implicit_recall_at_5", arm)
            self.assertIn("gap_closed", arm)
            self.assertIn("k2_follow_up", arm)
            gap = (arm["recall_at_5"] - recall["no_retrieve"]) / (recall["oracle"] - recall["no_retrieve"])
            self.assertAlmostEqual(gap, arm["gap_closed"])
            points = (arm["recall_at_5"] - arm["implicit_recall_at_5"]) * 100
            self.assertEqual(points >= 15, arm["k2_follow_up"])
            for store in ("memory", "mempalace"):
                scale = arm["scale"][store]
                sizes = [scale[factor]["bytes"] for factor in ("N", "4N", "16N")]
                self.assertGreaterEqual(sizes[0], sizes[1])
                self.assertGreaterEqual(sizes[1], sizes[2])
                self.assertTrue(all(scale[factor]["within_budget"] for factor in ("N", "4N", "16N")))

    def _real_questions(self, questions: list) -> tuple[list, int]:
        real = []
        dropped = 0
        seen: set[str] = set()
        for item in questions:
            golds = item.get("gold") if isinstance(item.get("gold"), list) else []
            if not golds or item.get("id") in seen:
                dropped += 1
                continue
            gold = golds[0]
            relative = str(gold.get("path") or "")
            line_no = gold.get("line")
            expect = str(item.get("expect") or "")
            question = str(item.get("question") or "")
            path = ROOT / relative
            if (
                not relative
                or relative.startswith(("/", "../"))
                or ".." in Path(relative).parts
                or not isinstance(line_no, int)
                or line_no < 1
                or not path.is_file()
                or not expect
                or not question
                or "placeholder" in question.casefold()
            ):
                dropped += 1
                continue
            lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
            if line_no > len(lines) or expect not in lines[line_no - 1]:
                dropped += 1
                continue
            seen.add(item["id"])
            real.append(item)
        return real, dropped


if __name__ == "__main__":
    unittest.main()
