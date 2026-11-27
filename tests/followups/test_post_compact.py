"""#24: Claude PostCompact re-injects PreCompact locators and does not decide permissions."""

from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
HOOK = ROOT / "hooks" / "guard.py"


def _kernel():
    name = "hook_kernel_followups"
    spec = importlib.util.spec_from_file_location(name, ROOT / "hooks" / "kernel.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def _hook(event_name: str) -> subprocess.CompletedProcess[str]:
    with tempfile.TemporaryDirectory() as temporary:
        event = {
            "hook_event_name": event_name,
            "session_id": "followups-post-compact",
            "cwd": temporary,
        }
        env = {
            **os.environ,
            "CHAOS_ENGINE_STORE_REFRESH": "0",
            "CHAOS_ENGINE_PROTECTED_CHECKOUTS": str(ROOT),
        }
        return subprocess.run(
            [sys.executable, str(HOOK)],
            input=json.dumps(event),
            capture_output=True,
            text=True,
            check=False,
            env=env,
            cwd=temporary,
        )


def _context(result: subprocess.CompletedProcess[str]) -> str:
    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    if "additionalContext" in payload:
        return str(payload["additionalContext"])
    specific = payload.get("hookSpecificOutput")
    if isinstance(specific, dict) and "additionalContext" in specific:
        return str(specific["additionalContext"])
    return ""


def test_post_compact_reinjects_the_same_locators_as_pre_compact():
    before = _context(_hook("PreCompact"))
    after = _context(_hook("PostCompact"))
    assert "ChaosEngine:" in before and "Companions" in before
    assert after == before


def test_instructions_loaded_does_not_append_companion_bodies():
    result = _hook("InstructionsLoaded")
    assert result.returncode == 0, result.stderr
    text = result.stdout + result.stderr
    assert "Caveman" not in text
    assert "Ponytail" not in text


def test_permission_request_keeps_a_deny_and_drops_an_allow():
    kernel = _kernel()
    denied = kernel.adapt_hook_output(
        {"decision": "deny", "reason": "blocked"},
        "PermissionRequest",
        "claude",
    )
    assert denied.get("decision") == "deny"
    allowed = kernel.adapt_hook_output(
        {"permissionDecision": "allow", "decision": "allow"},
        "PermissionRequest",
        "claude",
    )
    rendered = json.dumps(allowed)
    assert "allow" not in rendered


def test_permission_request_strips_nested_and_paired_allows():
    kernel = _kernel()
    allow_forms = (
        {"behavior": "allow"},
        {"permissionDecision": "approve"},
        {"decision": {"permissionDecision": "allow"}},
        {"hookSpecificOutput": {"permissionDecision": "allow"}},
        {"hookSpecificOutput": {"decision": {"behavior": "allow"}}},
        {"hookSpecificOutput": {"decision": {"behavior": "approve"}, "permissionDecisionReason": "allow it"}},
    )
    for payload in allow_forms:
        rendered = json.dumps(
            kernel.adapt_hook_output(payload, "PermissionRequest", "claude")
        )
        assert "allow" not in rendered, payload
        assert "approve" not in rendered, payload
        assert "deny" not in rendered, payload
    mixed_forms = (
        {"decision": "deny", "permissionDecision": "allow", "reason": "blocked"},
        {"decision": "deny", "behavior": "allow", "reason": "blocked"},
        {
            "decision": "deny",
            "reason": "blocked",
            "hookSpecificOutput": {"decision": {"behavior": "allow"}},
        },
        {
            "decision": "deny",
            "permissionDecision": "allow",
            "permissionDecisionReason": "allow it",
            "reason": "blocked",
        },
    )
    for payload in mixed_forms:
        adapted = kernel.adapt_hook_output(payload, "PermissionRequest", "claude")
        assert adapted.get("decision") == "deny", payload
        rendered = json.dumps(adapted)
        assert "allow" not in rendered, payload
        assert "approve" not in rendered, payload


def test_permission_request_does_not_return_an_allow_decision():
    kernel = _kernel()
    adapted = kernel.adapt_hook_output(
        {"permissionDecision": "allow", "decision": "allow"},
        "PermissionRequest",
        "claude",
    )
    rendered = json.dumps(adapted)
    assert "allow" not in rendered
    assert "deny" not in rendered
    live = _hook("PermissionRequest")
    assert live.returncode == 0
    assert "allow" not in live.stdout.casefold()
    assert "deny" not in live.stdout.casefold()
