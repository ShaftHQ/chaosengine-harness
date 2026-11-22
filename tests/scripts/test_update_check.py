"""Session-start update check. The fetcher is injected. No network."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
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

    def test_confirmed_payload_writes_named_files_and_refuses_traversal(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            marker = root / "VERSION"
            marker.write_text("1.0.0\n", encoding="utf-8")
            payload = {
                "version": "1.1.0",
                "root": str(root),
                "files": {"VERSION": "1.1.0\n", "../outside": "no\n"},
            }
            reported = session_start_update_check(lambda: payload, "1.0.0", False)
            self.assertEqual("update available: 1.1.0", reported)
            self.assertEqual("1.0.0\n", marker.read_text(encoding="utf-8"))
            applied = session_start_update_check(lambda: payload, "1.0.0", True)
            self.assertEqual("update confirmed: 1.1.0", applied)
            self.assertEqual("1.1.0\n", marker.read_text(encoding="utf-8"))
            self.assertFalse((root.parent / "outside").exists())

    def test_failed_fetch_does_not_raise_or_change_files(self):
        target = self._version_file("0.4.20261115.5")
        before = target.read_bytes()

        def broken() -> str:
            raise OSError("network down")

        status = session_start_update_check(
            fetcher=broken,
            version_file=target,
            confirm=True,
            apply=lambda _version: None,
        )
        self.assertEqual("update check failed", status)
        self.assertEqual(before, target.read_bytes())

    def test_session_start_names_the_check_in_lifecycle_and_the_guard(self):
        text = (ROOT / "references" / "lifecycle-hooks.md").read_text(encoding="utf-8")
        row = next(line for line in text.splitlines() if line.startswith("| `SessionStart` |"))
        self.assertIn("session_start_update_check", row)
        lifecycle = (ROOT / "hooks" / "lifecycle.py").read_text(encoding="utf-8")
        guard = (ROOT / "hooks" / "guard.py").read_text(encoding="utf-8")
        self.assertIn("session_start_update_check()", lifecycle)
        self.assertNotIn("session_start_update_check(", guard)

    def test_session_start_reports_a_newer_release_without_changing_files(self):
        version_path = ROOT / "VERSION"
        before = version_path.read_text(encoding="utf-8")
        environment = {
            **os.environ,
            "CHAOS_ENGINE_RELEASE_VERSION": "9.9.9",
            "CHAOS_ENGINE_STORE_REFRESH": "0",
            "CHAOS_ENGINE_PROTECTED_CHECKOUTS": str(ROOT),
        }
        environment.pop("CHAOS_ENGINE_APPLY_UPDATE", None)
        result = subprocess.run(  # nosec B603 - fixed interpreter and hook.
            [sys.executable, str(ROOT / "hooks" / "guard.py")],
            input=json.dumps({"hook_event_name": "SessionStart", "cwd": str(ROOT)}),
            capture_output=True,
            text=True,
            check=False,
            env=environment,
        )
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertIn("9.9.9", result.stdout)
        self.assertNotIn("update confirmed", result.stdout)
        self.assertEqual(before, version_path.read_text(encoding="utf-8"))

    def _version_file(self, text: str) -> Path:
        directory = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, directory, True)
        path = directory / "VERSION"
        path.write_text(text + "\n", encoding="utf-8")
        return path


if __name__ == "__main__":
    unittest.main()
