"""Guarded operations stay denied when they are not the literal shell argv."""

from __future__ import annotations

import json
import os
import shlex
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
HOOK = ROOT / "hooks" / "guard.py"


def _run(event: dict) -> subprocess.CompletedProcess[str]:
    protected = [
        item
        for item in os.environ.get("CHAOS_ENGINE_PROTECTED_CHECKOUTS", "").split(os.pathsep)
        if item
    ]
    protected.append(str(ROOT))
    environment = {
        **os.environ,
        "CHAOS_ENGINE_PROTECTED_CHECKOUTS": os.pathsep.join(protected),
        "CHAOS_ENGINE_STORE_REFRESH": "0",
    }
    return subprocess.run(  # nosec B603 - fixed interpreter and hook.
        [sys.executable, str(HOOK)],
        input=json.dumps(event),
        capture_output=True,
        text=True,
        check=False,
        env=environment,
    )


def _decision(result: subprocess.CompletedProcess[str]) -> str:
    payload = json.loads(result.stdout or "{}")
    decision = payload.get("decision")
    if decision is None:
        specific = payload.get("hookSpecificOutput")
        if isinstance(specific, dict):
            decision = specific.get("permissionDecision") or specific.get("decision")
    return str(decision or "")


class GuardIndirectionTests(unittest.TestCase):
    def assert_denies(self, event: dict) -> None:
        result = _run(event)
        self.assertEqual(2, result.returncode, result.stdout + result.stderr)
        self.assertIn(_decision(result), {"block", "deny"})

    def assert_allows(self, event: dict) -> None:
        result = _run(event)
        self.assertEqual(0, result.returncode, result.stdout + result.stderr)
        self.assertNotIn(_decision(result), {"block", "deny"})

    def test_pre_tool_denies_guarded_operation_through_indirection(self):
        python = "python3 -c \"import subprocess; subprocess.run(['git', 'reset', '--hard'])\""
        node = "node -e \"require('child_process').spawn('git',['reset','--hard'])\""
        heredoc = (
            "python3 - <<'PY'\nimport subprocess\n"
            "subprocess.run(['git', 'reset', '--hard'])\nPY\n"
        )
        bash_c = "bash -c " + shlex.quote(python)
        for command in (python, node, heredoc, bash_c):
            self.assertNotIn("git reset --hard", command)
            self.assert_denies(
                {
                    "hook_event_name": "PreToolUse",
                    "session_id": "indirection",
                    "tool_input": {"command": command},
                }
            )
        sources = (
            'tools["exec_command"]({cmd:"git reset --hard"});',
            'const run = tools.exec_command; await run({cmd:"git reset --hard"});',
            "const {exec_command: r} = tools; await r({cmd:\"git reset --hard\"});",
        )
        for source in sources:
            self.assert_denies(
                {
                    "hook_event_name": "PreToolUse",
                    "session_id": "indirection",
                    "tool_name": "functions.exec",
                    "tool_input": {"input": source},
                }
            )
        nested_cmd = "python3 -c " + shlex.quote(
            "import subprocess\nsubprocess.run(['git', 'reset', '--hard'])\n"
        )
        nested = "await tools.exec_command({cmd:" + json.dumps(nested_cmd) + "});"
        self.assertNotIn("git reset --hard", nested)
        self.assert_denies(
            {
                "hook_event_name": "PreToolUse",
                "session_id": "indirection",
                "tool_name": "functions.exec",
                "tool_input": {"input": nested},
            }
        )
        with tempfile.TemporaryDirectory() as temporary:
            script = Path(temporary) / "task.sh"
            script.write_text("git reset --hard\n", encoding="utf-8")
            self.assert_denies(
                {
                    "hook_event_name": "PreToolUse",
                    "session_id": "indirection",
                    "cwd": temporary,
                    "tool_input": {"command": "bash " + shlex.quote(str(script))},
                }
            )

    def test_pre_tool_allows_plain_interpreter_text(self):
        for command in (
            'python3 -c "print(1)"',
            'node -e "console.log(1)"',
            "python3 -m pytest -q",
        ):
            self.assert_allows(
                {
                    "hook_event_name": "PreToolUse",
                    "session_id": "indirection-allow",
                    "tool_input": {"command": command},
                }
            )
        self.assert_allows(
            {
                "hook_event_name": "PreToolUse",
                "session_id": "indirection-allow",
                "tool_name": "functions.exec",
                "tool_input": {"input": 'await tools.exec_command({cmd:"echo hi"});'},
            }
        )
        with tempfile.TemporaryDirectory() as temporary:
            script = Path(temporary) / "task.sh"
            script.write_text("echo hi\n", encoding="utf-8")
            self.assert_allows(
                {
                    "hook_event_name": "PreToolUse",
                    "session_id": "indirection-allow",
                    "cwd": temporary,
                    "tool_input": {"command": "bash " + shlex.quote(str(script))},
                }
            )
