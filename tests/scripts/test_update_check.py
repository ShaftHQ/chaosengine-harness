"""Session-start update check. The fetcher is injected. No network."""

from __future__ import annotations

import shutil
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from runtime.update_check import session_start_update_check  # noqa: E402


class UpdateCheckTests(unittest.TestCase):
    def test_same_version_is_up_to_date_and_does_not_change_the_file(self):
        target = self._version_file("0.4.20261115.5")
        before = target.read_bytes()
        applied: list[str] = []
        status = session_start_update_check(
            fetcher=lambda: "v0.4.20261115.5",
            version_file=target,
            confirm=True,
            apply=applied.append,
        )
        self.assertEqual("up-to-date", status)
        self.assertEqual(before, target.read_bytes())
        self.assertEqual([], applied)

    def test_older_remote_is_up_to_date(self):
        status = session_start_update_check(
            fetcher=lambda: "0.4.20261114.1",
            installed="0.4.20261115.5",
        )
        self.assertEqual("up-to-date", status)

    def test_newer_release_without_confirmation_does_not_apply(self):
        target = self._version_file("0.4.20261115.5")
        before = target.read_bytes()
        applied: list[str] = []
        status = session_start_update_check(
            fetcher=lambda: "0.4.20261116.1",
            version_file=target,
            confirm=False,
            apply=applied.append,
        )
        self.assertEqual("update available: 0.4.20261116.1", status)
        self.assertEqual(before, target.read_bytes())
        self.assertEqual([], applied)

    def test_confirmation_calls_apply_once(self):
        applied: list[str] = []
        status = session_start_update_check(
            fetcher=lambda: "v0.4.20261116.1",
            installed="0.4.20261115.5",
            confirm=True,
            apply=applied.append,
        )
        self.assertEqual("update confirmed: v0.4.20261116.1", status)
        self.assertEqual(["v0.4.20261116.1"], applied)

    def test_failed_fetch_does_not_raise_or_change_files(self):
        target = self._version_file("0.4.20261115.5")
        before = target.read_bytes()
        applied: list[str] = []

        def broken() -> str:
            raise OSError("network down")

        status = session_start_update_check(
            fetcher=broken,
            version_file=target,
            confirm=True,
            apply=applied.append,
        )
        self.assertEqual("update check failed", status)
        self.assertEqual(before, target.read_bytes())
        self.assertEqual([], applied)

    def test_session_start_row_names_the_check(self):
        text = (ROOT / "references" / "lifecycle-hooks.md").read_text(encoding="utf-8")
        row = next(line for line in text.splitlines() if line.startswith("| `SessionStart` |"))
        self.assertIn("session_start_update_check", row)
        source = (ROOT / "hooks" / "lifecycle.py").read_text(encoding="utf-8")
        self.assertIn("session_start_update_check()", source)
        self.assertNotIn("session_start_update_check", (ROOT / "hooks" / "guard.py").read_text(encoding="utf-8"))

    def _version_file(self, text: str) -> Path:
        directory = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, directory, True)
        path = directory / "VERSION"
        path.write_text(text + "\n", encoding="utf-8")
        return path


if __name__ == "__main__":
    unittest.main()
