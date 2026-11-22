"""Cursor, OpenCode, and Antigravity hook documents.

Adapters normalize and render. Policy stays in the guard and in
``runtime/gate_fail_closed.py``. Every command calls ``hooks/launch.py``.
"""

from __future__ import annotations

import json
import os
import platform
from pathlib import Path

CURSOR_HOOKS = ".cursor/hooks.json"
OPENCODE_PLUGIN = ".opencode/plugins/chaos-engine-receipt.js"
ANTIGRAVITY_HOOKS = ".agents/hooks.json"

# #106 event table. Names are Cursor's native camelCase.
CURSOR_EVENTS = (
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
)

# Native names the OpenCode bridge registers. Canonical mapping lives in the kernel.
OPENCODE_NATIVE_EVENTS = (
    "tool.execute.before",
    "execute.before",
    "tool.execute.after",
    "execute.after",
    "session.created",
    "session.idle",
)

ANTIGRAVITY_HOOK_NAME = "chaos-engine"
ANTIGRAVITY_MATCHER_EVENTS = ("PreToolUse", "PostToolUse")
ANTIGRAVITY_FLAT_EVENTS = ("SessionStart", "PreInvocation", "PostInvocation", "Stop")
ANTIGRAVITY_EVENTS = (*ANTIGRAVITY_MATCHER_EVENTS, *ANTIGRAVITY_FLAT_EVENTS)

_OWNED_MARKERS = ("hooks/launch.py", "receipt_shim.py")
_OPENCODE_MARKERS = (
    "// ChaosEngine guard bridge",
    "// ChaosEngine research-receipt shim",
)


def _fail_closed(event: str) -> bool:
    from runtime.gate_fail_closed import hook_event_fail_closed

    return hook_event_fail_closed(event)


def _locator(host: str, event: str | None = None) -> str:
    from runtime.hosts import chaos_guard_locator_command

    return chaos_guard_locator_command(
        windows=os.name == "nt", host=host, event=event
    )


def generated_platform() -> str:
    return platform.system().casefold()


def cursor_hooks_document() -> dict[str, object]:
    """Version-1 Cursor hooks. failClosed only on the preventive gate."""
    hooks: dict[str, list[dict[str, object]]] = {}
    for event in CURSOR_EVENTS:
        entry: dict[str, object] = {
            "command": _locator("cursor", event),
            "timeout": 30,
        }
        if _fail_closed(event):
            entry["failClosed"] = True
        hooks[event] = [entry]
    return {
        "version": 1,
        "hooks": hooks,
        "chaosEngineGeneratedOn": generated_platform(),
    }


def _owned_command(entry: object) -> bool:
    if not isinstance(entry, dict):
        return False
    command = entry.get("command")
    if not isinstance(command, str):
        return False
    return any(marker in command for marker in _OWNED_MARKERS)


def merge_cursor_hooks(existing: dict[str, object] | None) -> dict[str, object]:
    """Keep foreign hooks. Replace shim and guard entries. Migrate a shim-only file."""
    document = dict(existing) if isinstance(existing, dict) else {}
    desired = cursor_hooks_document()
    hooks = document.get("hooks")
    hooks = dict(hooks) if isinstance(hooks, dict) else {}
    for event, entries in list(hooks.items()):
        if not isinstance(entries, list):
            continue
        kept = [entry for entry in entries if not _owned_command(entry)]
        if kept:
            hooks[event] = kept
        else:
            del hooks[event]
    for event, entries in desired["hooks"].items():  # type: ignore[index]
        hooks.setdefault(event, [])
        current = hooks[event]
        if not isinstance(current, list):
            current = []
            hooks[event] = current
        for entry in entries:
            if entry not in current:
                current.append(entry)
    document["version"] = 1
    document["hooks"] = hooks
    document["chaosEngineGeneratedOn"] = desired["chaosEngineGeneratedOn"]
    return document


def cursor_platform_finding(document: dict[str, object], machine: str | None = None) -> str | None:
    """Doctor: a hooks file generated on another OS is not this machine's command."""
    recorded = str(document.get("chaosEngineGeneratedOn") or "")
    current = (machine or generated_platform()).casefold()
    if recorded and recorded != current:
        return (
            f"cursor hooks were generated on {recorded}; this machine is {current}"
        )
    return None


def opencode_plugin_source() -> str:
    """Plain JS guard bridge. No build and no npm. V1 and V2 from one file."""
    fail_closed = "true" if _fail_closed("PreToolUse") else "false"
    return f"""// ChaosEngine guard bridge. Generated; rerun the installer instead of editing.
// PreToolUse timeout follows runtime/gate_fail_closed.py. Stop on session.idle is observe-only.
import {{ spawn }} from 'node:child_process';

const FAIL_CLOSED_PRE_TOOL = {fail_closed};
const DEFAULT_TIMEOUT_MS = 30000;

function timeoutMs() {{
  const raw = Number(process.env.CE_OPENCODE_GUARD_TIMEOUT_MS || DEFAULT_TIMEOUT_MS);
  if (!Number.isFinite(raw) || raw < 1) return DEFAULT_TIMEOUT_MS;
  return Math.min(raw, DEFAULT_TIMEOUT_MS);
}}

function pythonCandidates() {{
  const forced = process.env.CE_OPENCODE_PYTHON;
  if (forced) return [forced];
  return process.platform === 'win32' ? ['py', 'python'] : ['python3', 'python'];
}}

function runGuard(directory, payload) {{
  const candidates = pythonCandidates();
  const failClosed = FAIL_CLOSED_PRE_TOOL && payload.hook_event_name === 'PreToolUse';
  return new Promise((resolve, reject) => {{
    let index = 0;
    const attempt = () => {{
      if (index >= candidates.length) {{
        const error = new Error('ChaosEngine guard unavailable: Python 3.11+ is missing');
        if (failClosed) reject(error);
        else resolve({{ decision: 'allow' }});
        return;
      }}
      const command = candidates[index++];
      const args = command === 'py'
        ? ['-3', '.chaos-engine/hooks/launch.py', 'opencode']
        : ['.chaos-engine/hooks/launch.py', 'opencode'];
      let child;
      try {{
        child = spawn(command, args, {{ cwd: directory, stdio: ['pipe', 'pipe', 'pipe'] }});
      }} catch (error) {{
        attempt();
        return;
      }}
      let out = '';
      let settled = false;
      const timer = setTimeout(() => {{
        if (settled) return;
        settled = true;
        child.kill();
        if (failClosed) reject(new Error('ChaosEngine guard timed out'));
        else resolve({{ decision: 'allow' }});
      }}, timeoutMs());
      child.stdout.on('data', (chunk) => {{ out += chunk; }});
      child.on('error', () => {{
        if (settled) return;
        settled = true;
        clearTimeout(timer);
        attempt();
      }});
      child.on('close', (code, signal) => {{
        if (settled) return;
        settled = true;
        clearTimeout(timer);
        const text = String(out || '').trim();
        let parsed = null;
        if (text) {{
          try {{
            parsed = JSON.parse(text);
          }} catch (error) {{
            parsed = null;
          }}
        }}
        const denied = Boolean(parsed && typeof parsed === 'object' && (
          parsed.decision === 'block' || parsed.decision === 'deny' || parsed.permission === 'deny'
        ));
        const crashed = code !== 0 || Boolean(signal) || !text || !parsed || typeof parsed !== 'object';
        if (failClosed && crashed && !denied) {{
          reject(new Error(
            !text || !parsed || typeof parsed !== 'object'
              ? 'ChaosEngine guard returned invalid JSON'
              : 'ChaosEngine guard exited ' + String(code == null ? signal : code)
          ));
          return;
        }}
        if (!parsed || typeof parsed !== 'object') {{
          resolve({{ decision: 'allow' }});
          return;
        }}
        resolve(parsed);
      }});
      child.stdin.on('error', () => {{}});
      try {{
        child.stdin.write(JSON.stringify(payload));
        child.stdin.end();
      }} catch (error) {{
        // The error event retries the next interpreter.
      }}
    }};
    attempt();
  }});
}}

function payloadFor(event, input, output) {{
  const source = input || {{}};
  const extra = output || {{}};
  // OpenCode 1.18 calls tool.execute.before(meta, {{args}}). The command is on
  // the second object. tool.execute.after puts args on the first object.
  const toolInput = source.args || source.input || source.tool_input
    || extra.args || extra.input || extra.tool_input
    || {{}};
  return {{
    hook_event_name: event,
    tool_name: source.tool || source.name || '',
    tool_input: toolInput,
    session_id: source.sessionID || source.sessionId || source.session_id || extra.sessionID || '',
    tool_use_id: source.callID || source.tool_use_id || source.id || extra.callID || '',
  }};
}}

async function guard(directory, event, input, output) {{
  const result = await runGuard(directory, payloadFor(event, input, output));
  const denied = result && (
    result.decision === 'block' || result.decision === 'deny' || result.permission === 'deny'
  );
  if (denied) {{
    throw new Error(result.reason || result.user_message || 'Blocked by ChaosEngine.');
  }}
}}

function afterEvent(input, output) {{
  const bag = output && (output.status === 'error' || output.error) ? output : input;
  if (bag && (bag.status === 'error' || bag.error)) return 'PostToolUseFailure';
  return 'PostToolUse';
}}

export function chaosEnginePlugin(input) {{
  const directory = (input && (input.directory || input.worktree || input.cwd)) || process.cwd();
  if (input && input.tool && typeof input.tool.hook === 'function') {{
    input.tool.hook('execute.before', async (call, output) => guard(directory, 'PreToolUse', call, output));
    input.tool.hook('execute.after', async (call, output) => guard(directory, afterEvent(call, output), call, output));
    if (input.event && typeof input.event.hook === 'function') {{
      input.event.hook('session.created', async (call) => guard(directory, 'SessionStart', call));
      input.event.hook('session.idle', async (call) => {{
        try {{ await guard(directory, 'Stop', call); }} catch (error) {{ /* observe-only Stop */ }}
      }});
    }}
    return {{}};
  }}
  return {{
    'tool.execute.before': async (call, output) => guard(directory, 'PreToolUse', call, output),
    'tool.execute.after': async (call, output) => guard(directory, afterEvent(call, output), call, output),
    'session.created': async (call) => guard(directory, 'SessionStart', call),
    'session.idle': async (call) => {{
      try {{ await guard(directory, 'Stop', call); }} catch (error) {{ /* observe-only Stop */ }}
    }},
  }};
}}

export default chaosEnginePlugin;
export const ChaosEngineGuard = chaosEnginePlugin;
"""


def antigravity_hooks_document() -> dict[str, object]:
    """Named hook object for Antigravity (.agents/hooks.json).

    Top-level keys are hook names. Matcher groups wrap tool events; the other
    four events are flat handler arrays (swapping shapes drops flat events).
    """
    spec: dict[str, object] = {}
    for event in ANTIGRAVITY_MATCHER_EVENTS:
        spec[event] = [{
            "matcher": ".*",
            "hooks": [{
                "type": "command",
                "command": _locator("antigravity", event),
            }],
        }]
    for event in ANTIGRAVITY_FLAT_EVENTS:
        spec[event] = [{
            "type": "command",
            "command": _locator("antigravity", event),
        }]
    return {ANTIGRAVITY_HOOK_NAME: spec}


def antigravity_hook_events(document: dict[str, object]) -> set[str]:
    """Return event names registered inside the named Antigravity hook spec."""
    spec = document.get(ANTIGRAVITY_HOOK_NAME)
    if isinstance(spec, dict):
        return {str(key) for key in spec if key in ANTIGRAVITY_EVENTS}
    return {str(key) for key in document if key in ANTIGRAVITY_EVENTS}


def _antigravity_owned(entry: object) -> bool:
    if not isinstance(entry, dict):
        return False
    if _owned_command(entry):
        return True
    hooks = entry.get("hooks")
    if isinstance(hooks, list) and hooks and all(_owned_command(item) for item in hooks):
        return True
    return False


def antigravity_hooks_findings(
    document: object, *, require_chaos_engine: bool = True
) -> list[str]:
    """Doctor checks for .agents/hooks.json named-hook schema and shapes."""
    if not isinstance(document, dict):
        return ["antigravity hooks document is not a JSON object"]
    findings: list[str] = []
    has_legacy = False
    for event in ANTIGRAVITY_EVENTS:
        legacy = document.get(event)
        if isinstance(legacy, list) and any(_antigravity_owned(item) for item in legacy):
            has_legacy = True
            findings.append(
                f"antigravity hooks use legacy top-level event key {event}; "
                "must be nested under a named hook object (rerun installer)"
            )
            break
    spec = document.get(ANTIGRAVITY_HOOK_NAME)
    if spec is None and not require_chaos_engine and not has_legacy:
        return findings
    if not isinstance(spec, dict):
        findings.append(
            f"antigravity hooks missing named '{ANTIGRAVITY_HOOK_NAME}' hook object"
        )
        return findings
    for event in ANTIGRAVITY_MATCHER_EVENTS:
        groups = spec.get(event)
        if not isinstance(groups, list) or not groups:
            findings.append(f"antigravity hook '{ANTIGRAVITY_HOOK_NAME}' missing {event} matcher group")
            continue
        if any(
            not isinstance(group, dict)
            or "matcher" not in group
            or not isinstance(group.get("hooks"), list)
            for group in groups
        ):
            findings.append(f"antigravity hook '{ANTIGRAVITY_HOOK_NAME}' {event} must use matcher+hooks")
        elif not any(_antigravity_owned(group) for group in groups):
            findings.append(f"antigravity hook '{ANTIGRAVITY_HOOK_NAME}' {event} does not call hooks/launch.py")
    for event in ANTIGRAVITY_FLAT_EVENTS:
        handlers = spec.get(event)
        if not isinstance(handlers, list) or not handlers:
            findings.append(f"antigravity hook '{ANTIGRAVITY_HOOK_NAME}' missing {event} handler list")
            continue
        if any(
            not isinstance(handler, dict) or "matcher" in handler or "hooks" in handler
            for handler in handlers
        ):
            findings.append(f"antigravity hook '{ANTIGRAVITY_HOOK_NAME}' {event} must be a flat handler list")
        elif not any(_antigravity_owned(handler) for handler in handlers):
            findings.append(f"antigravity hook '{ANTIGRAVITY_HOOK_NAME}' {event} does not call hooks/launch.py")
    return findings


def merge_antigravity_hooks(existing: dict[str, object] | None) -> dict[str, object]:
    """Keep foreign named hooks, migrate legacy top-level entries, write chaos-engine hook."""
    document = dict(existing) if isinstance(existing, dict) else {}
    # Migrate/strip legacy flat top-level ChaosEngine event arrays.
    for event in ANTIGRAVITY_EVENTS:
        legacy = document.get(event)
        if not isinstance(legacy, list):
            continue
        kept = [entry for entry in legacy if not _antigravity_owned(entry)]
        if kept:
            document[event] = kept
        else:
            del document[event]
    desired_spec = antigravity_hooks_document()[ANTIGRAVITY_HOOK_NAME]
    assert isinstance(desired_spec, dict)
    current_spec = document.get(ANTIGRAVITY_HOOK_NAME)
    merged_spec = dict(current_spec) if isinstance(current_spec, dict) else {}
    for event, groups in desired_spec.items():
        current = merged_spec.get(event)
        if not isinstance(current, list):
            merged_spec[event] = groups
            continue
        kept = [entry for entry in current if not _antigravity_owned(entry)]
        for entry in groups:
            if entry not in kept:
                kept.append(entry)
        merged_spec[event] = kept
    document[ANTIGRAVITY_HOOK_NAME] = merged_spec
    return document


def _write_json(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f"{path.name}.tmp-{os.getpid()}")
    temporary.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def install_cursor(project: Path) -> Path:
    target = project / CURSOR_HOOKS
    try:
        existing = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        existing = {}
    if not isinstance(existing, dict):
        existing = {}
    _write_json(target, merge_cursor_hooks(existing))
    return target


def install_opencode(project: Path) -> Path:
    target = project / OPENCODE_PLUGIN
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_name(f"{target.name}.tmp-{os.getpid()}")
    temporary.write_text(opencode_plugin_source(), encoding="utf-8")
    temporary.replace(target)
    return target


def install_antigravity(project: Path) -> Path:
    target = project / ANTIGRAVITY_HOOKS
    try:
        existing = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        existing = {}
    if not isinstance(existing, dict):
        existing = {}
    _write_json(target, merge_antigravity_hooks(existing))
    return target


def uninstall_cursor(project: Path) -> bool:
    target = project / CURSOR_HOOKS
    try:
        document = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return False
    hooks = document.get("hooks") if isinstance(document, dict) else None
    if not isinstance(hooks, dict):
        return False
    changed = False
    for event, entries in list(hooks.items()):
        if not isinstance(entries, list):
            continue
        kept = [entry for entry in entries if not _owned_command(entry)]
        if len(kept) != len(entries):
            changed = True
            if kept:
                hooks[event] = kept
            else:
                del hooks[event]
    if not changed:
        return False
    if not hooks and set(document) <= {"version", "hooks", "chaosEngineGeneratedOn"}:
        target.unlink()
    else:
        document.pop("chaosEngineGeneratedOn", None)
        _write_json(target, document)
    return True


def uninstall_opencode(project: Path) -> bool:
    target = project / OPENCODE_PLUGIN
    if not target.is_file() or target.is_symlink():
        return False
    text = target.read_text(encoding="utf-8")
    if text.startswith(_OPENCODE_MARKERS):
        target.unlink()
        return True
    return False


def uninstall_antigravity(project: Path) -> bool:
    target = project / ANTIGRAVITY_HOOKS
    try:
        document = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return False
    if not isinstance(document, dict):
        return False
    changed = False
    spec = document.get(ANTIGRAVITY_HOOK_NAME)
    if isinstance(spec, dict):
        updated = dict(spec)
        for event, entries in list(updated.items()):
            if not isinstance(entries, list):
                continue
            kept = [entry for entry in entries if not _antigravity_owned(entry)]
            if len(kept) != len(entries):
                changed = True
                if kept:
                    updated[event] = kept
                else:
                    del updated[event]
        remaining_events = [
            key for key, value in updated.items() if isinstance(value, list) and value
        ]
        if changed:
            if remaining_events:
                document[ANTIGRAVITY_HOOK_NAME] = updated
            else:
                del document[ANTIGRAVITY_HOOK_NAME]
    for event, entries in list(document.items()):
        if not isinstance(entries, list):
            continue
        kept = [entry for entry in entries if not _antigravity_owned(entry)]
        if len(kept) != len(entries):
            changed = True
            if kept:
                document[event] = kept
            else:
                del document[event]
    if not changed:
        return False
    if not document:
        target.unlink()
    else:
        _write_json(target, document)
    return True
