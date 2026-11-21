"""Per-tool-result byte counts and the code-mode step 0 share."""

from __future__ import annotations

import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def _load():
    path = ROOT / "runtime" / "learn_traces.py"
    spec = importlib.util.spec_from_file_location("ce_learn_traces_bytes", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class LearnTracesToolBytesTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.learn = _load()

    def test_stamp_records_utf8_bytes_on_the_tool_result(self):
        rows = [
            {
                "type": "user",
                "message": {
                    "role": "user",
                    "content": [{"type": "tool_result", "tool_use_id": "t1", "content": "abcdé"}],
                },
            }
        ]
        sizes = self.learn.stamp_tool_result_bytes(rows)
        self.assertEqual([6], sizes)
        self.assertEqual(6, rows[0]["message"]["content"][0]["resultBytes"])

    def test_collect_keeps_the_byte_counts(self):
        with tempfile.TemporaryDirectory() as temporary:
            home = Path(temporary)
            session = home / ".claude" / "projects" / "demo"
            session.mkdir(parents=True)
            (session / "s.jsonl").write_text(
                "\n".join(
                    [
                        json.dumps(
                            {
                                "type": "user",
                                "message": {"role": "user", "content": [{"type": "text", "text": "hello"}]},
                            }
                        ),
                        json.dumps(
                            {
                                "type": "user",
                                "message": {
                                    "role": "user",
                                    "content": [{"type": "tool_result", "content": "xy"}],
                                },
                            }
                        ),
                    ]
                )
                + "\n",
                encoding="utf-8",
            )
            out = home / "run"
            manifest = self.learn.collect(home, out)
            self.assertEqual(1, manifest["sessions_kept"])
            saved = json.loads(next((out / "sessions").glob("*.json")).read_text(encoding="utf-8"))
            self.assertEqual([2], saved["toolResultBytes"])
            block = saved["messages"][1]["message"]["content"][0]
            self.assertEqual(2, block["resultBytes"])

    def test_share_uses_uncached_tokens_and_pipe_turns(self):
        rows = [
            {
                "type": "user",
                "message": {"role": "user", "content": [{"type": "text", "text": "hi"}]},
            },
            {
                "type": "assistant",
                "message": {
                    "id": "a1",
                    "role": "assistant",
                    "content": [{"type": "text", "text": "ok"}],
                    "usage": {"input_tokens": 100, "cache_read_input_tokens": 0},
                },
            },
            {
                "type": "user",
                "message": {
                    "role": "user",
                    "content": [{"type": "tool_result", "content": "abcd"}],
                },
            },
            {
                "type": "assistant",
                "message": {
                    "id": "a2",
                    "role": "assistant",
                    "content": [{"type": "tool_use", "id": "t", "name": "rg", "input": {}}],
                    "usage": {"input_tokens": 25, "cache_read_input_tokens": 100},
                },
            },
        ]
        scored = self.learn.score_claude_rows(rows)
        self.assertEqual(4, scored["tool_result_bytes"])
        self.assertEqual(125, scored["uncached_tokens"])
        self.assertEqual(25, scored["intermediate_uncached_tokens"])
        self.assertEqual(1, scored["pipe_turns"])
        self.assertEqual(2, scored["model_turns"])
        report = self.learn._pressure_report(scored, grok_tool_result_bytes=0, grok_tool_results=0)
        self.assertEqual(0.2, report["intermediate_share"])
        self.assertEqual(0.5, report["pipe_share"])
        self.assertEqual("drop", report["decision"])

    def test_missing_sizes_and_usage_do_not_invent_a_share(self):
        report = self.learn._pressure_report(
            self.learn._empty_pressure(), grok_tool_result_bytes=0, grok_tool_results=0
        )
        self.assertIsNone(report["intermediate_share"])
        self.assertIsNone(report["pipe_share"])
        self.assertEqual("incomplete", report["decision"])
        self.assertIsNone(report["grok_token_share"])


if __name__ == "__main__":
    unittest.main()
