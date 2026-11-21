"""Offline hook-event pins and installer fresh-install / upgrade assertions.

Windows CI, the macOS installer leg, and ubuntu pytest all run this module.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from runtime.conformance import (  # noqa: E402
    check_hook_event_registry,
    load_fixture,
    production_hook_registry,
)
from runtime.hosts import (  # noqa: E402
    hook_content,
    lifecycle_hooks_document,
    without_chaos_hooks,
)


def _install():
    import importlib.util

    spec = importlib.util.spec_from_file_location("ce_install_hook_parity", ROOT / "install.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_offline_pin_covers_registered_events_and_codex_decision():
    fixture = load_fixture()
    pins = fixture["hook_events"]
    registry = production_hook_registry()
    assert check_hook_event_registry(registry, pins) == []
    codex = json.loads(lifecycle_hooks_document("codex"))["hooks"]
    assert "PostToolUseFailure" not in codex
    assert "PostToolUse" in codex
    assert "PostToolUseFailure" in json.loads(lifecycle_hooks_document("claude"))["hooks"]
    assert "PostToolUseFailure" in json.loads(lifecycle_hooks_document("grok"))["hooks"]


def test_fresh_install_and_upgrade_write_guard_surfaces(tmp_path: Path):
    project = tmp_path / "consumer"
    project.mkdir()
    foreign = {"command": "./format.sh"}
    hooks = project / ".cursor" / "hooks.json"
    hooks.parent.mkdir()
    hooks.write_text(
        json.dumps({"version": 1, "hooks": {"afterFileEdit": [foreign]}}),
        encoding="utf-8",
    )
    install = _install()
    first = install.wire_receipt_shims(project, which=lambda _name: None)
    assert first == {"cursor": "wired", "opencode": "wired", "antigravity": "wired"}
    cursor = json.loads(hooks.read_text(encoding="utf-8"))
    for event in (
        "sessionStart",
        "beforeSubmitPrompt",
        "preToolUse",
        "postToolUse",
        "postToolUseFailure",
        "subagentStart",
        "subagentStop",
        "stop",
        "preCompact",
        "sessionEnd",
    ):
        command = cursor["hooks"][event][0]["command"]
        assert "hooks/launch.py" in command
        assert event in command
    assert cursor["hooks"]["preToolUse"][0]["failClosed"] is True
    assert "failClosed" not in cursor["hooks"]["sessionStart"][0]
    assert cursor["hooks"]["afterFileEdit"] == [foreign]
    plugin = (project / ".opencode/plugins/chaos-engine-receipt.js").read_text(encoding="utf-8")
    assert "ChaosEngine guard bridge" in plugin
    assert "hooks/launch.py" in plugin
    assert "plugin-adapters" not in plugin
    antigravity = json.loads((project / ".agents/hooks.json").read_text(encoding="utf-8"))
    assert "chaos-engine" in antigravity
    assert "matcher" in antigravity["chaos-engine"]["PreToolUse"][0]
    assert "matcher" not in antigravity["chaos-engine"]["Stop"][0]

    second = install.wire_receipt_shims(project, which=lambda _name: None)
    assert second == first
    upgraded = json.loads(hooks.read_text(encoding="utf-8"))
    assert upgraded["hooks"]["afterFileEdit"] == [foreign]
    assert upgraded["hooks"]["preToolUse"][0]["command"] == cursor["hooks"]["preToolUse"][0]["command"]

    previous = {
        "hooks": {
            "PostToolUseFailure": [
                {"matcher": ".*", "hooks": [{"type": "command", "command": "echo mine"}]},
                {
                    "hooks": [
                        {
                            "type": "command",
                            "command": json.loads(lifecycle_hooks_document("grok"))["hooks"]["PostToolUseFailure"][0]["hooks"][0]["command"],
                        }
                    ]
                },
            ],
            "SessionStart": [
                {"hooks": [{"type": "command", "command": "echo user-start"}]}
            ],
        }
    }
    merged = json.loads(
        hook_content(
            without_chaos_hooks(json.dumps(previous).encode(), "Codex"),
            lifecycle_hooks_document("codex"),
            "Codex",
        )
    )
    owned = merged["hooks"]["PostToolUseFailure"]
    assert owned == [{"matcher": ".*", "hooks": [{"type": "command", "command": "echo mine"}]}]
    assert "PostToolUseFailure" not in json.loads(lifecycle_hooks_document("codex"))["hooks"]
    session = merged["hooks"]["SessionStart"]
    assert any(group.get("hooks") == [{"type": "command", "command": "echo user-start"}] for group in session)

    install.unwire_receipt_shims(project)
    remaining = json.loads(hooks.read_text(encoding="utf-8"))
    assert remaining["hooks"] == {"afterFileEdit": [foreign]}
    assert "chaosEngineGeneratedOn" not in remaining
    assert not (project / ".opencode/plugins/chaos-engine-receipt.js").exists()
    assert not (project / ".agents/hooks.json").exists()
