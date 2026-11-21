"""The checkout root stays a small front door."""

from __future__ import annotations

import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
ROOT_PYTHON = {"bootstrap.py", "chaosengine_harness.py", "install.py", "tool.py"}


def _parallel_temp_dir(name: str) -> bool:
    """tempfile.mkdtemp names are ``tmp`` plus eight letters. They are not layout."""
    if len(name) != 11 or not name.startswith("tmp"):
        return False
    return all(char in "abcdefghijklmnopqrstuvwxyz0123456789_" for char in name[3:])


class RepoLayoutTest(unittest.TestCase):
    def test_root_python_is_only_the_entry_points(self):
        found = {path.name for path in ROOT.glob("*.py") if path.is_file()}
        self.assertEqual(ROOT_PYTHON, found)

    def test_layout_names_every_top_level_directory(self):
        layout = (ROOT / "docs/layout.md").read_text(encoding="utf-8")
        self.assertIn("runtime/", layout)
        self.assertIn("skills/chaos-engine/SKILL.md", layout)
        missing = [
            path.name
            for path in ROOT.iterdir()
            if path.is_dir() and not path.name.startswith(".") and path.name != "__pycache__"
            and not _parallel_temp_dir(path.name)
            and path.name not in layout
        ]
        self.assertEqual([], missing)


if __name__ == "__main__":
    unittest.main()
