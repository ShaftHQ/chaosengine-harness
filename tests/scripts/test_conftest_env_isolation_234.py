"""#234: harness env does not leak, and the ce_ui sync check is fast."""

from __future__ import annotations

import os
import shutil
import tempfile
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_01_set_secret_guard():
    os.environ["CHAOS_ENGINE_SECRET_GUARD"] = "0"
    assert os.environ["CHAOS_ENGINE_SECRET_GUARD"] == "0"


def test_02_secret_guard_does_not_leak():
    assert os.environ.get("CHAOS_ENGINE_SECRET_GUARD") != "0"


class CeUiSyncSpeedTest(unittest.TestCase):
    def test_fast_validator_detects_inline_drift(self):
        import importlib.util

        spec = importlib.util.spec_from_file_location(
            "ce_overlay_234", ROOT / "scripts" / "ci" / "overlay_pre_push.py"
        )
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "runtime").mkdir()
            (root / "scripts" / "ci").mkdir(parents=True)
            shutil.copy(ROOT / "scripts" / "ci" / "sync_ce_ui.py", root / "scripts" / "ci" / "sync_ce_ui.py")
            source = root / "runtime" / "ce_ui.py"
            source.write_text("VALUE = 1\n", encoding="utf-8")
            bootstrap = root / "bootstrap.py"
            bootstrap.write_text(
                "head\n# >>> generated: ce_ui\nVALUE = 0\n# <<< generated: ce_ui\ntail\n",
                encoding="utf-8",
            )
            started = time.perf_counter()
            failures = module.ce_ui_sync_failures(root)
            self.assertLess(time.perf_counter() - started, 1.0)
            self.assertTrue(any("ce_ui inline drift" in item for item in failures))
            hooked = module.overlay_pre_push_failures(root, ["runtime/ce_ui.py"])
            self.assertTrue(any("ce_ui inline drift" in item for item in hooked))


if __name__ == "__main__":
    unittest.main()
