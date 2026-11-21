"""SessionStart update check. The fetcher is fake. No network."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from runtime.update_check import session_start_update_check  # noqa: E402


class UpdateCheckTests(unittest.TestCase):
    def test_newer_release_is_reported_and_not_applied_until_confirm(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            marker = root / "VERSION"
            marker.write_text("1.0.0\n", encoding="utf-8")
            payload = {
                "version": "1.1.0",
                "root": str(root),
                "files": {"VERSION": "1.1.0\n"},
            }

            reported = session_start_update_check(lambda: payload, "1.0.0", False)
            self.assertIn("1.1.0", reported)
            self.assertNotIn("applied", reported)
            self.assertEqual("1.0.0\n", marker.read_text(encoding="utf-8"))

            applied = session_start_update_check(lambda: payload, "1.0.0", True)
            self.assertIn("applied", applied)
            self.assertIn("1.1.0", applied)
            self.assertEqual("1.1.0\n", marker.read_text(encoding="utf-8"))

    def test_current_release_is_up_to_date_and_leaves_files(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            marker = root / "VERSION"
            marker.write_text("1.0.0\n", encoding="utf-8")
            payload = {
                "version": "1.0.0",
                "root": str(root),
                "files": {"VERSION": "nope\n"},
            }
            self.assertEqual(
                "up-to-date",
                session_start_update_check(lambda: payload, "1.0.0", True),
            )
            self.assertEqual("1.0.0\n", marker.read_text(encoding="utf-8"))
            self.assertEqual(
                "up-to-date",
                session_start_update_check(lambda: "0.9.0", "1.0.0", True),
            )
            self.assertEqual("1.0.0\n", marker.read_text(encoding="utf-8"))

    def test_fetcher_exception_leaves_files_and_does_not_raise(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            marker = root / "VERSION"
            marker.write_text("1.0.0\n", encoding="utf-8")

            def fetcher():
                raise RuntimeError("offline")

            self.assertEqual("unavailable", session_start_update_check(fetcher, "1.0.0", True))
            self.assertEqual("1.0.0\n", marker.read_text(encoding="utf-8"))

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
        self.assertNotIn("applied", result.stdout)
        self.assertEqual(before, version_path.read_text(encoding="utf-8"))
