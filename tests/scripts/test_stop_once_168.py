"""One retrospective, one retrieve demand, and a named destructive denial.

The older hook module is quarantined because it imports SHAFT-only
``scripts.agents``. These checks load the portable hooks directly.
"""

from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
HOOK = ROOT / "hooks" / "guard.py"
REFLECTION = ROOT / "hooks" / "reflection.py"
JUSTIFICATION = ROOT / "hooks" / "retrieve_justification.py"
HIDDEN = "import subprocess\ncmd = ['echo', 'hi']\nsubprocess.run(cmd)\nnote = 'rm -rf /'\n"


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _env(temporary: str) -> dict[str, str]:
    return {
        **os.environ,
        "TMPDIR": temporary,
        "TEMP": temporary,
        "TMP": temporary,
        "CHAOS_ENGINE_STORE_REFRESH": "0",
        "PYTHONDONTWRITEBYTECODE": "1",
    }


def _run(event: dict, env: dict[str, str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(  # nosec B603 - fixed interpreter and portable hook.
        [sys.executable, str(HOOK)],
        input=json.dumps(event),
        capture_output=True,
        text=True,
        check=False,
        env=env,
    )


class StopOnceTest(unittest.TestCase):
    def test_terminal_reflection_is_demanded_once(self):
        with tempfile.TemporaryDirectory() as temporary:
            environment = _env(temporary)
            previous = {key: os.environ.get(key) for key in ("TMPDIR", "TEMP", "TMP")}
            os.environ.update(environment)
            try:
                reflection = _load("ce_reflection_once", REFLECTION)
                reflection.record_session_start("terminal-once", "2020-01-01T00:00:00+00:00")
            finally:
                for key, value in previous.items():
                    if value is None:
                        os.environ.pop(key, None)
                    else:
                        os.environ[key] = value
            first = _run({"hook_event_name": "Stop", "session_id": "terminal-once"}, environment)
            second = _run(
                {
                    "hook_event_name": "Stop",
                    "session_id": "terminal-once",
                    "stop_hook_active": False,
                },
                environment,
            )
        self.assertEqual("block", json.loads(first.stdout).get("decision"), first.stdout)
        self.assertIn("Terminal reflection required", first.stdout)
        self.assertNotIn("Terminal reflection required", second.stdout)
        self.assertNotEqual("block", json.loads(second.stdout or "{}").get("decision"))

    def test_short_retrospective_headings_are_accepted(self):
        note = (
            "## Learning retrospective\n"
            "What happened: the stop hook asked again\n"
            "Why:\n"
            "the labels were short\n"
            "Continue:\n"
            "accept a heading\n"
            "Stop:\n"
            "asking on every stop\n"
            "Start:\n"
            "one demand per session\n"
            "Next action: nothing actionable\n"
            "## Enhancements\n"
            "nothing actionable\n"
        )
        with tempfile.TemporaryDirectory() as temporary:
            environment = _env(temporary)
            previous = {key: os.environ.get(key) for key in ("TMPDIR", "TEMP", "TMP")}
            os.environ.update(environment)
            try:
                reflection = _load("ce_reflection_short", REFLECTION)
                reflection.record_session_start("terminal-short", "2020-01-01T00:00:00+00:00")
            finally:
                for key, value in previous.items():
                    if value is None:
                        os.environ.pop(key, None)
                    else:
                        os.environ[key] = value
            paid = _run(
                {
                    "hook_event_name": "Stop",
                    "session_id": "terminal-short",
                    "last_assistant_message": note,
                },
                environment,
            )
            later = _run({"hook_event_name": "Stop", "session_id": "terminal-short"}, environment)
        self.assertNotEqual("block", json.loads(paid.stdout or "{}").get("decision"), paid.stdout)
        self.assertNotIn("Terminal reflection required", paid.stdout)
        self.assertNotIn("Terminal reflection required", later.stdout)

    def test_retrieve_stop_is_asked_once_and_skipped_after_a_blocked_retrieve(self):
        with tempfile.TemporaryDirectory() as temporary:
            environment = _env(temporary)
            project = Path(temporary) / "project"
            tool = project / ".chaos-engine" / "tool.py"
            tool.parent.mkdir(parents=True)
            tool.write_text(HIDDEN, encoding="utf-8")
            _run(
                {
                    "hook_event_name": "PreToolUse",
                    "tool_name": "Grep",
                    "cwd": str(project),
                    "session_id": "retrieve-once",
                    "tool_input": {"pattern": "class", "glob": "*.java"},
                },
                environment,
            )
            first = _run(
                {
                    "hook_event_name": "Stop",
                    "cwd": str(project),
                    "session_id": "retrieve-once",
                    "stop_hook_active": False,
                },
                environment,
            )
            second = _run(
                {
                    "hook_event_name": "Stop",
                    "cwd": str(project),
                    "session_id": "retrieve-once",
                    "stop_hook_active": False,
                },
                environment,
            )
            _run(
                {
                    "hook_event_name": "PreToolUse",
                    "tool_name": "Grep",
                    "cwd": str(project),
                    "session_id": "retrieve-blocked",
                    "tool_input": {"pattern": "class", "glob": "*.java"},
                },
                environment,
            )
            allowed = _run(
                {
                    "hook_event_name": "PreToolUse",
                    "tool_name": "Bash",
                    "cwd": str(project),
                    "session_id": "retrieve-blocked",
                    "tool_input": {
                        "command": 'python3 .chaos-engine/tool.py retrieve --store graphify "q"',
                    },
                },
                environment,
            )
            justify = _load("ce_justify_once", JUSTIFICATION)
            justify.note_retrieve_blocked(project, "retrieve-blocked")
            after_deny = _run(
                {
                    "hook_event_name": "Stop",
                    "cwd": str(project),
                    "session_id": "retrieve-blocked",
                    "stop_hook_active": False,
                },
                environment,
            )
        self.assertIn("tool.py retrieve --store graphify", first.stdout)
        self.assertEqual(2, first.returncode, first.stdout + first.stderr)
        self.assertNotIn("tool.py retrieve", second.stdout)
        self.assertNotEqual("block", json.loads(second.stdout or "{}").get("decision"))
        self.assertEqual(0, allowed.returncode, allowed.stdout + allowed.stderr)
        self.assertNotIn("destructive broad scope", allowed.stdout)
        self.assertNotIn("tool.py retrieve", after_deny.stdout)

    def test_retrieve_demand_follows_the_project_when_session_ids_collide(self):
        with tempfile.TemporaryDirectory() as temporary:
            environment = _env(temporary)
            previous = {key: os.environ.get(key) for key in ("TMPDIR", "TEMP", "TMP")}
            os.environ.update(environment)
            try:
                reflection = _load("ce_reflection_shared_session", REFLECTION)
                reflection.record_activity("shared-session", "retrieve-demanded")
            finally:
                for key, value in previous.items():
                    if value is None:
                        os.environ.pop(key, None)
                    else:
                        os.environ[key] = value
            stops = []
            first_project = None
            for name in ("alpha", "beta"):
                project = Path(temporary) / name
                tool = project / ".chaos-engine" / "tool.py"
                tool.parent.mkdir(parents=True)
                tool.write_text(HIDDEN, encoding="utf-8")
                if first_project is None:
                    first_project = project
                _run(
                    {
                        "hook_event_name": "PreToolUse",
                        "tool_name": "Grep",
                        "cwd": str(project),
                        "session_id": "shared-session",
                        "tool_input": {"pattern": "class", "glob": "*.java"},
                    },
                    environment,
                )
                stops.append(
                    _run(
                        {
                            "hook_event_name": "Stop",
                            "cwd": str(project),
                            "session_id": "shared-session",
                            "stop_hook_active": False,
                        },
                        environment,
                    )
                )
            again = _run(
                {
                    "hook_event_name": "Stop",
                    "cwd": str(first_project),
                    "session_id": "shared-session",
                    "stop_hook_active": False,
                },
                environment,
            )
        self.assertIn("tool.py retrieve --store graphify", stops[0].stdout)
        self.assertIn("tool.py retrieve --store graphify", stops[1].stdout)
        self.assertNotIn("tool.py retrieve", again.stdout)

    def test_project_tool_py_reads_are_allowed_and_a_nested_copy_is_named(self):
        with tempfile.TemporaryDirectory() as temporary:
            environment = _env(temporary)
            parent = Path(temporary) / "mono"
            child = parent / "app"
            (parent / "chaos-engine").mkdir(parents=True)
            (parent / "chaos-engine" / "install.py").write_text("raise SystemExit(0)\n", encoding="utf-8")
            tool = child / ".chaos-engine" / "tool.py"
            tool.parent.mkdir(parents=True)
            tool.write_text(HIDDEN, encoding="utf-8")
            evil = child / "evil"
            evil.mkdir()
            (evil / "tool.py").write_text(HIDDEN, encoding="utf-8")
            source = Path(temporary) / "src"
            (source / "hooks").mkdir(parents=True)
            (source / "runtime").mkdir()
            (source / "hooks" / "guard.py").write_text("# guard\n", encoding="utf-8")
            (source / "runtime" / "hosts.py").write_text("# hosts\n", encoding="utf-8")
            (source / "tool.py").write_text(HIDDEN, encoding="utf-8")
            allowed = (
                (child, 'python3 .chaos-engine/tool.py retrieve --store memory "q"'),
                (child, "python3 .chaos-engine/tool.py entry"),
                (child, "python3 .chaos-engine/tool.py ce-version 2>&1 | tail -3"),
                (source, "python3 tool.py entry"),
                (source, 'python3 ./tool.py retrieve --store graphify "q"'),
            )
            for cwd, command in allowed:
                result = _run(
                    {
                        "hook_event_name": "PreToolUse",
                        "tool_name": "Bash",
                        "cwd": str(cwd),
                        "session_id": "tool-allow",
                        "tool_input": {"command": command},
                    },
                    environment,
                )
                self.assertEqual(0, result.returncode, command + result.stdout + result.stderr)
                self.assertNotIn("destructive broad scope", result.stdout, command)
            denied = _run(
                {
                    "hook_event_name": "PreToolUse",
                    "tool_name": "Bash",
                    "cwd": str(child),
                    "session_id": "tool-deny",
                    "tool_input": {"command": 'python3 evil/tool.py retrieve "test"'},
                },
                environment,
            )
            compound = _run(
                {
                    "hook_event_name": "PreToolUse",
                    "tool_name": "Bash",
                    "cwd": str(child),
                    "session_id": "tool-compound",
                    "tool_input": {
                        "command": "python3 .chaos-engine/tool.py retrieve && git reset --hard HEAD",
                    },
                },
                environment,
            )
            removed = _run(
                {
                    "hook_event_name": "PreToolUse",
                    "tool_name": "Bash",
                    "cwd": str(child),
                    "session_id": "tool-rm",
                    "tool_input": {
                        "command": "python3 .chaos-engine/tool.py retrieve && rm -rf /",
                    },
                },
                environment,
            )
        self.assertEqual("block", json.loads(denied.stdout).get("decision"), denied.stdout)
        self.assertIn("branch=uninspected", denied.stdout)
        self.assertIn("fragment=", denied.stdout)
        self.assertIn("evil/tool.py", denied.stdout)
        self.assertEqual("block", json.loads(compound.stdout).get("decision"), compound.stdout)
        self.assertIn("branch=compound", compound.stdout)
        self.assertIn("git reset --hard", compound.stdout)
        self.assertEqual("block", json.loads(removed.stdout).get("decision"), removed.stdout)
        self.assertIn("Delete guard", removed.stdout)
        self.assertIn("`/`", removed.stdout)


if __name__ == "__main__":
    unittest.main()
