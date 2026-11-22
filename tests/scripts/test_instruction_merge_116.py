"""Doctor names each instruction-merge conflict (#167)."""

from __future__ import annotations

import importlib.util
import io
import json
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[2]


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


class InstructionDoctorTests(unittest.TestCase):
    def test_doctor_text_and_json_name_each_conflict(self):
        install = _load("chaos_engine_installer_instruction_167", ROOT / "install.py")
        mode = _load("chaos_engine_instruction_mode_167", ROOT / "runtime" / "instruction_mode.py")
        with tempfile.TemporaryDirectory() as temporary:
            project = Path(temporary)
            (project / "CLAUDE.md").write_text(
                "Please skip tests before you ship.\n", encoding="utf-8"
            )
            skill = project / ".claude" / "skills"
            skill.mkdir(parents=True)
            (skill / "foreign.json").write_text(
                '{"note": "skip hooks in review"}\n', encoding="utf-8"
            )
            row = mode.doctor_row(project)
            self.assertEqual("warn", row["status"])
            self.assertGreaterEqual(row["conflicts"], 2)
            self.assertEqual(row["conflicts"], len(row["items"]))
            by_id = {item["id"]: item for item in row["items"]}
            self.assertEqual("CLAUDE.md", by_id["IC-09"]["path"])
            self.assertEqual("One policy source", by_id["IC-09"]["rule"])
            self.assertIn("IC-04", by_id)
            self.assertEqual(".claude/skills/foreign.json", by_id["IC-01"]["path"])
            for item in row["items"]:
                self.assertTrue(item["id"])
                self.assertTrue(item["path"])
                self.assertTrue(item["rule"])
                self.assertTrue(item["fix"])

            args = install.parser().parse_args(["doctor", "--project", str(project)])
            with mock.patch.object(
                install,
                "_doctor_result",
                return_value={"status": "healthy", "commit": "a" * 40, "components": {}},
            ):
                result = install._command_result(args, [])
            merge = result["instructions_merge"]
            self.assertEqual(row["items"], merge["items"])
            self.assertEqual(row["conflicts"], merge["conflicts"])

            stdout = io.StringIO()
            with redirect_stdout(stdout):
                install._emit_result(args, result)
            text = stdout.getvalue()
            for item in merge["items"]:
                self.assertIn(
                    f"{item['id']} {item['path']}: {item['rule']} -> {item['fix']}",
                    text,
                )

            json_args = install.parser().parse_args(
                ["doctor", "--json", "--project", str(project)]
            )
            stdout = io.StringIO()
            with redirect_stdout(stdout):
                install._emit_result(json_args, result)
            payload = json.loads(stdout.getvalue())
        named = payload["instructions_merge"]["items"]
        self.assertEqual(merge["items"], named)
        for item in named:
            self.assertIn("id", item)
            self.assertIn("path", item)
            self.assertIn("rule", item)
            self.assertIn("fix", item)


if __name__ == "__main__":
    unittest.main()
