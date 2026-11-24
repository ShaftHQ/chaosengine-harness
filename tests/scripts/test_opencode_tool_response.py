"""OpenCode after-hook forwards tool output into the guard payload (#227).

PostToolUse stdout secret scan reads ``tool_response``. The bridge must put the
after-hook output on that field.
"""

from __future__ import annotations

import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"unable to load {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


class OpenCodeToolResponseTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.surfaces = load("ce_opencode_tool_response_surfaces", ROOT / "runtime" / "hook_surfaces.py")

    def test_after_hook_forwards_tool_response_stdout(self):
        node = shutil.which("node")
        if node is None:
            self.fail("node is required to prove the OpenCode tool_response bridge")
        source = self.surfaces.opencode_plugin_source()
        self.assertIn("tool_response", source)
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "package.json").write_text('{"type":"module"}\n', encoding="utf-8")
            (root / "plugin.js").write_text(source, encoding="utf-8")
            fake = root / "fake-python.py"
            fake.write_text(
                textwrap.dedent(
                    """\
                    import json, os, sys
                    raw = sys.stdin.read()
                    open(os.environ["FAKE_STDIN"], "w", encoding="utf-8").write(raw)
                    print(json.dumps({"decision": "allow"}))
                    """
                ),
                encoding="utf-8",
            )
            driver = root / "driver.mjs"
            driver.write_text(
                textwrap.dedent(
                    """\
                    import { chaosEnginePlugin } from "./plugin.js";
                    const plugin = chaosEnginePlugin({ directory: process.cwd() });
                    const output = {
                      stdout: "AKIAIOSFODNN7EXAMPLE",
                      stderr: "",
                      exit_code: 0,
                    };
                    await plugin["tool.execute.after"](
                      { tool: "bash", args: { command: "printf hidden" }, sessionID: "ses", callID: "call" },
                      output,
                    );
                    console.log("after-ok");
                    """
                ),
                encoding="utf-8",
            )
            hooks = root / ".chaos-engine" / "hooks"
            hooks.mkdir(parents=True)
            (hooks / "launch.py").write_text(fake.read_text(encoding="utf-8"), encoding="utf-8")
            env = os.environ.copy()
            env["FAKE_STDIN"] = str(root / "stdin.txt")
            env["CE_OPENCODE_PYTHON"] = sys.executable
            completed = subprocess.run(
                [node, str(driver)],
                cwd=root,
                capture_output=True,
                text=True,
                env=env,
                check=False,
                timeout=15,
            )
            self.assertIn("after-ok", completed.stdout, completed.stderr)
            recorded = json.loads((root / "stdin.txt").read_text(encoding="utf-8"))
        self.assertEqual("PostToolUse", recorded["hook_event_name"])
        self.assertEqual({"command": "printf hidden"}, recorded["tool_input"])
        response = recorded["tool_response"]
        self.assertIsInstance(response, dict)
        self.assertIn("AKIAIOSFODNN7EXAMPLE", str(response.get("stdout") or response.get("output") or ""))


if __name__ == "__main__":
    unittest.main()
