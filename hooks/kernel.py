#!/usr/bin/env python3
"""Provider-neutral ChaosEngine lifecycle policy kernel."""

from __future__ import annotations

import contextlib
import hashlib
import json
import os
import re
import threading
import time
from dataclasses import dataclass, field, replace
from pathlib import Path
from types import MappingProxyType
from typing import Callable, Mapping


SCHEMA_VERSION = 1
STATE_SCHEMA_VERSION = 3
CANONICAL_IDENTITY = "chaos-engine"
# Provider-neutral roles. A person token is not an identity.
JOURNAL_ROLES = frozenset({
    "orchestrator",
    "implementer",
    "reviewer",
    "tester",
    "mechanical-helper",
})


def _accepted_journal_identity(identity: str, schema_version: int) -> bool:
    """Accept the product identity, or a v1 role. Never a person token."""
    if identity == CANONICAL_IDENTITY:
        return True
    return schema_version == 1 and identity in JOURNAL_ROLES


TERMINAL_PHASES = frozenset({"Complete", "Blocked"})
LIFECYCLE_TRANSITIONS: Mapping[str, tuple[str, ...]] = {
    "ReadOnly": ("Complete", "Planned", "Blocked"),
    "Planned": ("Approved", "Blocked"),
    "Approved": ("Do", "Blocked"),
    "Do": ("Check", "Blocked"),
    # A warm maven cache is not proof of a newly declared repository.
    # jitpack.io served the docker-java POM for a coordinate that was not the
    # intended artifact. Stay in Check until a resolve that does not reuse that
    # cache succeeds.
    "Check": ("Act", "Blocked"),
    "Act": ("PullRequest", "Blocked"),
    "PullRequest": ("Reviewed", "Blocked"),
    "Reviewed": ("Authorized", "Blocked"),
    "Authorized": ("Merged", "Blocked"),
    "Merged": ("Learned", "Blocked"),
    "Learned": ("Complete", "Blocked"),
    "Complete": (),
    "Blocked": (),
}

CLAUDE_EVENTS = (
    "SessionStart",
    "UserPromptSubmit",
    "PreToolUse",
    "PostToolUse",
    "PostToolUseFailure",
    "Stop",
    "SubagentStop",
    "PreCompact",
    "PostCompact",
    "SessionEnd",
)
# Official Codex hooks have no PostToolUseFailure. Failure stays on PostToolUse.
# PreCompact and PostCompact are official; the guard already emits them.
CODEX_EVENTS = (
    "SessionStart",
    "UserPromptSubmit",
    "PreToolUse",
    "PostToolUse",
    "Stop",
    "SubagentStop",
    "PreCompact",
    "PostCompact",
    "SessionEnd",
)
GROK_EVENTS = (
    "SessionStart",
    "UserPromptSubmit",
    "PreToolUse",
    "PostToolUse",
    "PostToolUseFailure",
    "Stop",
    "SubagentStop",
    "PreCompact",
    "PostCompact",
    "SessionEnd",
)
GEMINI_EVENTS = (
    "SessionStart",
    "UserPromptSubmit",
    "PreToolUse",
    "PostToolUse",
    "Stop",
    "PreCompact",
    "SessionEnd",
)
COPILOT_EVENTS = (
    "SessionStart",
    "UserPromptSubmit",
    "PreToolUse",
    "PostToolUse",
    "PostToolUseFailure",
    "Stop",
    "SubagentStop",
    "PreCompact",
    "SessionEnd",
)


@dataclass(frozen=True)
class HostCapability:
    instruction_paths: tuple[str, ...]
    event_aliases: Mapping[str, str]
    supported_events: tuple[str, ...]
    strict_json_stdout: bool = True
    live_gate: bool = True
    static_surfaces: tuple[str, ...] = ()
    # How a deny becomes a hard block on this host (parity with #5579).
    hard_block_mechanism: str = "decision_json"
    deny_exit_code: int = 2
    # True when the host/process boundary reliably honors exit code 2 (or
    # equivalent native deny). False hosts still emit deny payloads + exit 2
    # from ChaosEngine; trust the adapter and surface blocking_gap to owners.
    process_exit2_honored: bool = True
    blocking_gap: str = ""
    # Host CLI executable doctor probes for exit-2 fidelity (#6408).
    cli: str = ""



# Plugin hook copies do not ship references/. Keep this equal to the
# GAP-EXIT2-SENTENCE line in references/host-parity-matrix.md.
_GAP_EXIT2_FALLBACK = (
    "GAP-EXIT2: ChaosEngine still emits decision=block or "
    "permissionDecision=deny and exit 2; verify host trust."
)


def gap_exit2_sentence() -> str:
    """Single compensating sentence owned by host-parity-matrix.md."""
    path = Path(__file__).resolve().parents[1] / "references" / "host-parity-matrix.md"
    marker = "GAP-EXIT2-SENTENCE:"
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return _GAP_EXIT2_FALLBACK
    for line in lines:
        if line.startswith(marker):
            sentence = line[len(marker):].strip()
            if sentence:
                return sentence
    raise RuntimeError("GAP-EXIT2 sentence missing from host-parity-matrix.md")


GAP_EXIT2_SENTENCE = gap_exit2_sentence()

# A subagent is a new session on Claude, Codex, and Grok. Those hosts do not
# fire SessionStart for it. The same locator injection handles the native name.
# Official native name. Convenience spellings stay in INPUT_SYNONYMS so the
# pin check only sees names the host documents.
_OFFICIAL_SUBAGENT_START = {"SubagentStart": "SessionStart"}
INPUT_SYNONYMS = MappingProxyType({
    # Convenience spellings. Official names stay in each host's event_aliases.
    # The 2026-11-22 Grok hooks page lists PascalCase only.
    "SubagentStart": "SessionStart",
    "subagentStart": "SessionStart",
    "subagent_start": "SessionStart",
    "preToolUse": "PreToolUse",
    "postToolUse": "PostToolUse",
    "postToolUseFailure": "PostToolUseFailure",
    "agentStop": "Stop",
    "sessionEnd": "SessionEnd",
    "sessionStart": "SessionStart",
    "session_start": "SessionStart",
    "user_prompt_submit": "UserPromptSubmit",
    "pre_tool_use": "PreToolUse",
    "post_tool_use": "PostToolUse",
    "post_tool_use_failure": "PostToolUseFailure",
    "stop": "Stop",
    "subagent_stop": "SubagentStop",
    "session_end": "SessionEnd",
})


def _aliases(supported: tuple[str, ...], **values: str) -> Mapping[str, str]:
    base = {event: event for event in supported}
    base.update(values)
    return MappingProxyType(base)


HOST_CAPABILITIES: Mapping[str, HostCapability] = {
    "codex": HostCapability(
        ("AGENTS.md", ".agents/skills/chaos-engine/SKILL.md"),
        _aliases(CODEX_EVENTS, **_OFFICIAL_SUBAGENT_START),
        CODEX_EVENTS,
        hard_block_mechanism="permission_decision",
        deny_exit_code=2,
        process_exit2_honored=True,
    ),
    "claude": HostCapability(
        ("CLAUDE.md", ".claude/skills/chaos-engine/SKILL.md"),
        _aliases(CLAUDE_EVENTS, **_OFFICIAL_SUBAGENT_START),
        CLAUDE_EVENTS,
        hard_block_mechanism="exit_2",
        deny_exit_code=2,
        process_exit2_honored=True,
    ),
    "gemini": HostCapability(
        ("GEMINI.md", ".gemini/skills/chaos-engine/SKILL.md"),
        _aliases(
            (),
            SessionStart="SessionStart",
            SessionEnd="SessionEnd",
            BeforeTool="PreToolUse",
            AfterTool="PostToolUse",
            BeforeAgent="UserPromptSubmit",
            AfterAgent="Stop",
            PreCompress="PreCompact",
        ),
        GEMINI_EVENTS,
        hard_block_mechanism="decision_json",
        deny_exit_code=2,
        process_exit2_honored=True,
    ),
    "grok": HostCapability(
        ("AGENTS.md", ".grok/plugins/chaos-engine"),
        _aliases(GROK_EVENTS, **_OFFICIAL_SUBAGENT_START),
        GROK_EVENTS,
        hard_block_mechanism="decision_json",
        deny_exit_code=2,
        process_exit2_honored=False,
        blocking_gap=GAP_EXIT2_SENTENCE,
        cli="grok",
    ),
    "copilot": HostCapability(
        ("AGENTS.md", ".github/copilot-instructions.md", ".github/skills/chaos-engine/SKILL.md"),
        _aliases(
            (),
            sessionStart="SessionStart",
            userPromptSubmitted="UserPromptSubmit",
            preToolUse="PreToolUse",
            postToolUse="PostToolUse",
            postToolUseFailure="PostToolUseFailure",
            agentStop="Stop",
            subagentStop="SubagentStop",
            preCompact="PreCompact",
            sessionEnd="SessionEnd",
        ),
        COPILOT_EVENTS,
        static_surfaces=("cloud", "ide"),
        hard_block_mechanism="permission_decision",
        deny_exit_code=2,
        process_exit2_honored=False,
        blocking_gap=GAP_EXIT2_SENTENCE,
        cli="copilot",
    ),
    # Exit-2 stays unhonored until a live probe. The adapter still renders
    # the host's deny fields. Do not flip process_exit2_honored from docs.
    "cursor": HostCapability(
        ("AGENTS.md",),
        _aliases(
            (),
            sessionStart="SessionStart",
            beforeSubmitPrompt="UserPromptSubmit",
            preToolUse="PreToolUse",
            postToolUse="PostToolUse",
            postToolUseFailure="PostToolUseFailure",
            subagentStart="SessionStart",
            subagentStop="SubagentStop",
            stop="Stop",
            preCompact="PreCompact",
            sessionEnd="SessionEnd",
        ),
        (
            "SessionStart",
            "UserPromptSubmit",
            "PreToolUse",
            "PostToolUse",
            "PostToolUseFailure",
            "SubagentStop",
            "Stop",
            "PreCompact",
            "SessionEnd",
        ),
        hard_block_mechanism="permission_decision",
        deny_exit_code=2,
        process_exit2_honored=False,
        blocking_gap=GAP_EXIT2_SENTENCE,
        cli="cursor-agent",
    ),
    "opencode": HostCapability(
        ("AGENTS.md",),
        _aliases(
            (),
            **{
                "tool.execute.before": "PreToolUse",
                "execute.before": "PreToolUse",
                "tool.execute.after": "PostToolUse",
                "execute.after": "PostToolUse",
                "session.created": "SessionStart",
                "session.idle": "Stop",
            },
        ),
        ("SessionStart", "PreToolUse", "PostToolUse", "PostToolUseFailure", "Stop"),
        hard_block_mechanism="throw",
        deny_exit_code=2,
        process_exit2_honored=False,
        blocking_gap=GAP_EXIT2_SENTENCE,
        cli="opencode",
    ),
    "antigravity": HostCapability(
        ("AGENTS.md", "GEMINI.md", ".agents/skills/chaos-engine/SKILL.md"),
        _aliases(
            (),
            SessionStart="SessionStart",
            PreToolUse="PreToolUse",
            PostToolUse="PostToolUse",
            PreInvocation="UserPromptSubmit",
            PostInvocation="PostToolUse",
            Stop="Stop",
        ),
        ("SessionStart", "PreToolUse", "PostToolUse", "UserPromptSubmit", "Stop"),
        hard_block_mechanism="decision_json",
        deny_exit_code=0,
        process_exit2_honored=False,
        blocking_gap=GAP_EXIT2_SENTENCE,
        cli="agy",
    ),
}

FIELD_ALIASES = {
    "hookEventName": "hook_event_name",
    "toolName": "tool_name",
    "toolInput": "tool_input",
    "toolArgs": "tool_input",
    "sessionId": "session_id",
    "conversationId": "session_id",
    "agentId": "agent_id",
    "agentType": "agent_type",
    "toolResponse": "tool_response",
    "toolResult": "tool_result",
    "lastAssistantMessage": "last_assistant_message",
    "lastUserInput": "prompt",
    "stopHookActive": "stop_hook_active",
    "continuationActive": "stop_hook_active",
    "toolUseId": "tool_use_id",
    "targetPhase": "target_phase",
}
TOOL_ALIASES = {
    "bash": "PowerShell",
    "powershell": "PowerShell",
    "shellcommand": "PowerShell",
    "shell_command": "PowerShell",
    "execcommand": "PowerShell",
    "exec_command": "PowerShell",
    "runshellcommand": "PowerShell",
    "run_shell_command": "PowerShell",
    "runinterminal": "PowerShell",
    "run_in_terminal": "PowerShell",
    "runcommand": "PowerShell",
    "run_command": "PowerShell",
    "read": "Read",
    "view": "Read",
    "viewfile": "Read",
    "view_file": "Read",
    "readfile": "Read",
    "read_file": "Read",
    "readmanyfiles": "Read",
    "read_many_files": "Read",
    "glob": "Glob",
    "list_dir": "Glob",
    "listdir": "Glob",
    "findbyname": "Glob",
    "find_by_name": "Glob",
    "grep": "Grep",
    "search": "Grep",
    "grepsearch": "Grep",
    "grep_search": "Grep",
    "edit": "Edit",
    "editfile": "Edit",
    "edit_file": "Edit",
    "replace": "Edit",
    "replacestringinfile": "Edit",
    "replace_string_in_file": "Edit",
    "multireplacestringinfile": "Edit",
    "multi_replace_string_in_file": "Edit",
    "replacefilecontent": "Edit",
    "replace_file_content": "Edit",
    "multireplacefilecontent": "Edit",
    "multi_replace_file_content": "Edit",
    "write": "Write",
    "writefile": "Write",
    "write_file": "Write",
    "writetofile": "Write",
    "write_to_file": "Write",
    "createfile": "Write",
    "create_file": "Write",
    "applypatch": "apply_patch",
    "apply_patch": "apply_patch",
}

_DIRECT_READ_ONLY_TOOLS = frozenset({"glob", "grep", "listdir", "read"})


@dataclass(frozen=True)
class HookEvent:
    name: str
    host: str
    session_id: str
    agent_id: str
    tool_name: str
    tool_input: Mapping[str, object]
    stop_hook_active: bool
    stateful_mutation: bool
    raw_fields: tuple[str, ...]
    tool_call_id: str = ""
    phase: str = "ReadOnly"
    target_phase: str = ""
    cancelled: bool = False
    timed_out: bool = False


_HOST_ALIASES = {"agy": "antigravity"}


def detect_host(raw: Mapping[str, object] | None = None) -> str:
    configured = os.environ.get("CHAOS_ENGINE_HOST", "").strip().lower()
    configured = _HOST_ALIASES.get(configured, configured)
    if configured in HOST_CAPABILITIES:
        return configured
    if os.environ.get("GROK_HOOK_EVENT"):
        return "grok"
    supplied = raw or {}
    declared = str(supplied.get("host") or supplied.get("provider") or "").strip().lower()
    declared = _HOST_ALIASES.get(declared, declared)
    if declared in HOST_CAPABILITIES:
        return declared
    if str(supplied.get("hook_event_name", "")).startswith(("Before", "After")):
        return "gemini"
    if any(key in supplied for key in ("toolArgs", "stopReason", "sessionId")):
        return "copilot"
    if os.environ.get("CLAUDE_CODE_ENTRYPOINT") or os.environ.get("CLAUDE_PLUGIN_ROOT"):
        return "claude"
    if os.environ.get("CODEX_HOME"):
        return "codex"
    return "unknown"


def _event_name(value: object, host: str) -> str:
    rendered = str(value or "")
    capability = HOST_CAPABILITIES.get(host)
    if capability is not None and rendered in capability.event_aliases:
        return capability.event_aliases[rendered]
    if rendered in INPUT_SYNONYMS:
        return INPUT_SYNONYMS[rendered]
    return rendered


def _tool_name(value: object) -> str:
    rendered = str(value or "")
    key = re.sub(r"[^a-z_]", "", rendered.casefold())
    return TOOL_ALIASES.get(key, rendered)


def _is_mutation(tool_name: str, _tool_input: Mapping[str, object]) -> bool:
    compact_name = re.sub(r"[^a-z]", "", tool_name.casefold())
    # Shell tools can execute configured helpers even for commands which look
    # read-only. Exempt only host-native tools whose contract is direct reading.
    return compact_name not in _DIRECT_READ_ONLY_TOOLS


def normalize_event(raw: Mapping[str, object], host: str | None = None) -> HookEvent:
    selected = host or detect_host(raw)
    normalized = dict(raw)
    for source, target in FIELD_ALIASES.items():
        if target not in normalized and source in normalized:
            normalized[target] = normalized[source]
    if selected == "grok" and not normalized.get("hook_event_name") and os.environ.get("GROK_HOOK_EVENT"):
        normalized["hook_event_name"] = os.environ["GROK_HOOK_EVENT"]
    if selected == "grok" and not normalized.get("session_id") and os.environ.get("GROK_SESSION_ID"):
        normalized["session_id"] = os.environ["GROK_SESSION_ID"]
    if selected == "cursor":
        if not normalized.get("session_id"):
            normalized["session_id"] = str(
                normalized.get("conversation_id") or raw.get("conversation_id") or ""
            )
        if not normalized.get("tool_use_id"):
            normalized["tool_use_id"] = str(
                raw.get("tool_call_id") or raw.get("generation_id") or ""
            )
    if selected == "opencode":
        if not normalized.get("tool_name"):
            normalized["tool_name"] = raw.get("tool") or raw.get("name") or ""
        if "tool_input" not in normalized and isinstance(raw.get("args"), Mapping):
            normalized["tool_input"] = raw.get("args")
    tool_call = raw.get("toolCall")
    if isinstance(tool_call, Mapping):
        if not normalized.get("tool_name") and tool_call.get("name"):
            normalized["tool_name"] = tool_call.get("name")
        if not normalized.get("tool_use_id") and tool_call.get("id"):
            normalized["tool_use_id"] = tool_call.get("id")
        if "tool_input" not in normalized and isinstance(tool_call.get("args"), Mapping):
            normalized["tool_input"] = tool_call.get("args")
    name = _event_name(normalized.get("hook_event_name"), selected)
    tool_input = normalized.get("tool_input")
    if isinstance(tool_input, str):
        try:
            tool_input = json.loads(tool_input)
        except (json.JSONDecodeError, ValueError):
            tool_input = {"invalidJson": True}
    if not isinstance(tool_input, Mapping):
        tool_input = {}
    tool_input = dict(tool_input)
    if "file_path" not in tool_input and "filePath" in tool_input:
        tool_input["file_path"] = tool_input["filePath"]
    for alt_path in ("Path", "AbsolutePath", "TargetFile"):
        if "file_path" not in tool_input and alt_path in tool_input:
            tool_input["file_path"] = tool_input[alt_path]
    for alt_dir in ("SearchDirectory", "SearchPath", "DirectoryPath"):
        if "path" not in tool_input and alt_dir in tool_input:
            tool_input["path"] = tool_input[alt_dir]
    if "command" not in tool_input and "CommandLine" in tool_input:
        tool_input["command"] = tool_input["CommandLine"]
    if "startLine" not in tool_input and "StartLine" in tool_input:
        tool_input["startLine"] = tool_input["StartLine"]
    if "endLine" not in tool_input and "EndLine" in tool_input:
        tool_input["endLine"] = tool_input["EndLine"]
    tool_name = _tool_name(normalized.get("tool_name"))
    return HookEvent(
        name=name,
        host=selected,
        session_id=str(normalized.get("session_id") or "").strip(),
        agent_id=str(normalized.get("agent_id") or "").strip(),
        tool_name=tool_name,
        tool_input=tool_input,
        stop_hook_active=bool(normalized.get("stop_hook_active")),
        stateful_mutation=_is_mutation(tool_name, tool_input),
        raw_fields=tuple(sorted(str(key) for key in raw)),
        tool_call_id=str(normalized.get("tool_use_id") or "").strip(),
        phase=str(normalized.get("phase") or "ReadOnly"),
        target_phase=str(normalized.get("target_phase") or ""),
        cancelled=(
            normalized.get("cancelled") is True or normalized.get("canceled") is True
        ),
        timed_out=(
            normalized.get("timed_out") is True or normalized.get("timeout") is True
        ),
    )


def normalize_hook_input(raw: Mapping[str, object]) -> dict[str, object]:
    """Compatibility projection for existing source callbacks."""
    event = normalize_event(raw)
    normalized = dict(raw)
    normalized.update(
        {
            "hook_event_name": event.name,
            "session_id": event.session_id,
            "agent_id": event.agent_id,
            "tool_name": event.tool_name,
            "tool_input": dict(event.tool_input),
            "stop_hook_active": event.stop_hook_active,
        }
    )
    if event.tool_call_id and not normalized.get("tool_use_id"):
        normalized["tool_use_id"] = event.tool_call_id
    if "prompt" not in normalized and isinstance(raw.get("lastUserInput"), str):
        normalized["prompt"] = raw["lastUserInput"]
    if not str(normalized.get("reason") or "").strip():
        term = normalized.get("terminationReason")
        if not isinstance(term, str) or not term.strip():
            term = normalized.get("termination_reason")
        if isinstance(term, str) and term.strip():
            normalized["reason"] = term.strip().casefold()
    if (
        event.host == "antigravity"
        and event.name == "PostToolUse"
        and raw.get("error")
        and "tool_response" not in normalized
    ):
        normalized["tool_response"] = {"isError": True, "error": str(raw["error"])}
    return normalized


_NO_DECISION_EVENTS = frozenset({"PermissionRequest", "Elicitation", "ElicitationResult"})

# Claude reads additionalContext only inside hookSpecificOutput, and only on
# these events. PreCompact stdout is the compaction summary. PostCompact has
# no context channel. hookEventName must be the raw host name: a Claude
# SubagentStart is normalized to SessionStart before this adapter runs.
_CLAUDE_CONTEXT_EVENTS = frozenset({
    "SessionStart",
    "SubagentStart",
    "UserPromptSubmit",
    "PreToolUse",
    "PostToolUse",
    "PostToolUseFailure",
    "PostToolBatch",
    "Stop",
    "SubagentStop",
})


def _drop_permission_decision(output: dict[str, object]) -> dict[str, object]:
    """PermissionRequest and elicitation stay guide-only. Never allow or deny."""
    cleaned = dict(output)
    for key in ("permissionDecision", "decision", "behavior"):
        cleaned.pop(key, None)
    specific = cleaned.get("hookSpecificOutput")
    if isinstance(specific, dict):
        inner = dict(specific)
        for key in ("permissionDecision", "permissionDecisionReason", "decision", "behavior"):
            inner.pop(key, None)
        cleaned["hookSpecificOutput"] = inner
    return cleaned


def _claude_context_event(event_name: str, native_event: str) -> str:
    """Return the hookEventName Claude will read, or empty when it has no channel."""
    shown = native_event or event_name
    if shown in _CLAUDE_CONTEXT_EVENTS:
        return shown
    if event_name in _CLAUDE_CONTEXT_EVENTS:
        return event_name
    return ""


def _nest_claude_additional_context(
    adapted: dict[str, object], event_name: str, native_event: str
) -> None:
    """Move top-level additionalContext into hookSpecificOutput. Leave decisions."""
    shown = _claude_context_event(event_name, native_event)
    if not shown or "additionalContext" not in adapted:
        return
    context = adapted.pop("additionalContext")
    current = adapted.get("hookSpecificOutput")
    specific = dict(current) if isinstance(current, dict) else {}
    specific["hookEventName"] = shown
    specific["additionalContext"] = context
    adapted["hookSpecificOutput"] = specific


def adapt_hook_output(
    output: Mapping[str, object],
    event_name: str,
    host: str,
    native_event: str = "",
) -> dict[str, object]:
    """Project canonical decisions/context into each host's native hook protocol."""
    if event_name in _NO_DECISION_EVENTS:
        return _drop_permission_decision(dict(output))
    adapted = dict(output)
    if host == "claude":
        _nest_claude_additional_context(adapted, event_name, native_event)
    if host == "codex":
        # Codex docs require the native SubagentStart name. The alias to
        # SessionStart is internal and must not be what the host reads.
        shown = event_name
        if event_name == "SessionStart" and native_event in {
            "SubagentStart",
            "subagentStart",
            "subagent_start",
        }:
            shown = "SubagentStart"
        specific: dict[str, object] = {"hookEventName": shown}
        context = adapted.pop("additionalContext", None)
        if context is not None:
            specific["additionalContext"] = context
        if event_name == "PreToolUse":
            decision = adapted.pop("decision", None)
            reason = adapted.pop("reason", None)
            if decision in {"block", "deny"}:
                specific["permissionDecision"] = "deny"
                specific["permissionDecisionReason"] = str(
                    reason or "Blocked by ChaosEngine."
                )
            elif decision == "allow":
                specific["permissionDecision"] = "allow"
        if len(specific) > 1:
            adapted["hookSpecificOutput"] = specific
    if host == "gemini" and "additionalContext" in adapted:
        context = adapted.pop("additionalContext")
        adapted["hookSpecificOutput"] = {"additionalContext": context}
    if host == "copilot" and event_name == "PreToolUse":
        decision = adapted.pop("decision", None)
        reason = adapted.pop("reason", None)
        if decision in {"block", "deny"}:
            adapted["permissionDecision"] = "deny"
            adapted["permissionDecisionReason"] = str(reason or "Blocked by ChaosEngine.")
        elif decision == "allow":
            adapted["permissionDecision"] = "allow"
    # GAP-EXIT2 hosts ignore exit 2. The continuation channel is the text
    # they still surface after a Stop that returned decision=block.
    capability = HOST_CAPABILITIES.get(host)
    if (
        capability is not None
        and not capability.process_exit2_honored
        and event_name in {"Stop", "SubagentStop"}
        and adapted.get("decision") in {"block", "deny"}
    ):
        reason = str(adapted.get("reason") or "")
        if reason:
            adapted["additionalContext"] = reason
            if host == "copilot":
                adapted["permissionDecision"] = "deny"
                adapted["permissionDecisionReason"] = reason
    _copy_grok_session_start(adapted, event_name, host)
    if host == "cursor":
        _adapt_cursor(adapted, event_name)
    elif host == "antigravity":
        _adapt_antigravity(adapted, event_name, native_event)
    return adapted


def _adapt_cursor(adapted: dict[str, object], event_name: str) -> None:
    """Render Cursor fields. No policy: the decision is already made."""
    context = adapted.pop("additionalContext", None)
    decision = adapted.pop("decision", None)
    reason = adapted.pop("reason", None)
    if isinstance(context, str) and context:
        adapted["additional_context"] = context
    if decision in {"block", "deny"}:
        if event_name == "PreToolUse":
            text = str(reason or "Blocked by ChaosEngine.")
            adapted["permission"] = "deny"
            adapted["user_message"] = text
            adapted["agent_message"] = text
        elif event_name == "UserPromptSubmit":
            adapted["continue"] = False
            if reason:
                adapted["user_message"] = str(reason)
        elif event_name in {"Stop", "SubagentStop"}:
            adapted["followup_message"] = str(reason or "Blocked by ChaosEngine.")
    elif decision == "allow" and event_name == "PreToolUse":
        adapted["permission"] = "allow"


def _adapt_antigravity(
    adapted: dict[str, object], event_name: str, native_event: str = ""
) -> None:
    """Project canonical decisions/context into Antigravity's native hook contract.

    Deny is JSON on exit 0. Context uses `injectSteps` with nested `systemMessage`.
    `PreToolUse` requires `decision`; `PostToolUse` expects `{}`; `Stop` continues
    with `decision: "continue"` and `reason`.
    """
    decision = adapted.get("decision")
    reason = adapted.get("reason")
    context = adapted.get("additionalContext")
    if event_name == "PreToolUse":
        adapted.clear()
        if decision in {"block", "deny"}:
            adapted["decision"] = "deny"
            if reason:
                adapted["reason"] = reason
        else:
            adapted["decision"] = "allow"
        return
    if event_name == "Stop":
        adapted.clear()
        if decision in {"block", "deny"}:
            adapted["decision"] = "continue"
            if reason:
                adapted["reason"] = reason
        return
    if event_name == "SessionStart":
        adapted.clear()
        if isinstance(context, str) and context:
            adapted["injectSteps"] = [{"systemMessage": {"systemMessage": context}}]
        return
    if event_name in {"UserPromptSubmit", "PreInvocation"} or native_event == "PreInvocation":
        adapted.clear()
        if decision in {"block", "deny"}:
            adapted["injectSteps"] = [
                {"errorMessage": {"userMessage": str(reason or "Blocked by ChaosEngine.")}}
            ]
            adapted["terminationBehavior"] = "terminate"
        elif isinstance(context, str) and context:
            adapted["injectSteps"] = [{"systemMessage": {"systemMessage": context}}]
        return
    if event_name == "PostInvocation" or native_event == "PostInvocation":
        adapted.clear()
        if decision in {"block", "deny"}:
            adapted["injectSteps"] = [
                {"errorMessage": {"userMessage": str(reason or "Blocked by ChaosEngine.")}}
            ]
            adapted["terminationBehavior"] = "terminate"
        elif isinstance(context, str) and context:
            adapted["injectSteps"] = [{"systemMessage": {"systemMessage": context}}]
        return
    if event_name == "PostToolUse":
        adapted.clear()
        return


_IDENTITY_BODY = re.compile(r"Identity \(`([^`]*)`\):\n(?:- [^\n]*\n)+")


def _session_start_max_bytes() -> int:
    cached = getattr(_session_start_max_bytes, "value", None)
    if isinstance(cached, int):
        return cached
    import importlib.util

    path = Path(__file__).resolve().parent / "lifecycle.py"
    spec = importlib.util.spec_from_file_location("chaos_engine_lifecycle_budget", path)
    if spec is None or spec.loader is None:
        return 4096
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    value = int(module.SESSION_START_MAX_BYTES)
    _session_start_max_bytes.value = value
    return value


def _grok_session_bytes(context: str) -> int:
    payload = {"additionalContext": context, "systemMessage": context}
    return len(json.dumps(payload).encode("utf-8"))


def _degrade_identity_to_path(context: str) -> str:
    match = _IDENTITY_BODY.search(context)
    if match is None:
        return context
    locator = match.group(1) or ".chaos-engine/identity.md"
    return f"{context[: match.start()]}Identity: `{locator}`\n{context[match.end() :]}"


def _fit_grok_session_start(context: str) -> str:
    """Keep the doubled Grok payload inside SESSION_START_MAX_BYTES.

    Drop the identity body to its path line before cutting the tail. Drift and
    unfinished-task lines are the tail, so the path line survives that cut.
    """
    budget = _session_start_max_bytes()
    if _grok_session_bytes(context) <= budget:
        return context
    degraded = _degrade_identity_to_path(context)
    if _grok_session_bytes(degraded) <= budget:
        return degraded
    lo, hi = 0, len(degraded)
    best = ""
    while lo <= hi:
        mid = (lo + hi) // 2
        candidate = degraded[:mid]
        if _grok_session_bytes(candidate) <= budget:
            best = candidate
            lo = mid + 1
        else:
            hi = mid - 1
    newline = best.rfind("\n")
    if newline > 0:
        return best[:newline]
    return best


def _copy_grok_session_start(adapted: dict[str, object], event_name: str, host: str) -> None:
    """Grok reads SessionStart from systemMessage. SessionEnd uses the same channel for the report."""
    if host != "grok" or event_name not in {"SessionStart", "SessionEnd"} or "additionalContext" not in adapted:
        return
    context = adapted.get("additionalContext")
    if not isinstance(context, str):
        return
    if event_name == "SessionStart":
        context = _fit_grok_session_start(context)
        adapted["additionalContext"] = context
    adapted["systemMessage"] = context


@dataclass(frozen=True)
class _FactFlight:
    done: threading.Event


@dataclass
class HarnessSnapshot:
    providers: Mapping[str, Callable[[], object]] = field(default_factory=dict)
    wait_timeout: float = 0.1
    _cache: dict[str, object] = field(default_factory=dict, init=False, repr=False)
    _lock: threading.RLock = field(default_factory=threading.RLock, init=False, repr=False)
    _inflight: dict[str, _FactFlight] = field(default_factory=dict, init=False, repr=False)

    def __post_init__(self) -> None:
        """Freeze providers and validate the bounded wait."""
        self.providers = MappingProxyType(dict(self.providers))
        if self.wait_timeout < 0:
            raise ValueError("fact wait timeout must be non-negative")

    def _resolve(
        self, name: str, provider: Callable[[], object] | None, flight: _FactFlight
    ) -> None:
        value: object = "unknown"
        try:
            if provider is not None:
                value = provider()
        except (Exception, KeyboardInterrupt, SystemExit):
            # Provider failures are facts, not authority to break the lifecycle caller.
            pass
        finally:
            with self._lock:
                self._cache.setdefault(name, value)
                if self._inflight.get(name) is flight:
                    self._inflight.pop(name, None)
                flight.done.set()

    def fact(self, name: str) -> object:
        start_resolver = False
        with self._lock:
            if name in self._cache:
                return self._cache[name]
            flight = self._inflight.get(name)
            if flight is None:
                flight = _FactFlight(threading.Event())
                self._inflight[name] = flight
                provider = self.providers.get(name)
                start_resolver = True

        if start_resolver:
            try:
                threading.Thread(
                    target=self._resolve,
                    args=(name, provider, flight),
                    name=f"chaos-engine-fact-{name}",
                    daemon=True,
                ).start()
            except Exception:
                with self._lock:
                    self._cache.setdefault(name, "unknown")
                    if self._inflight.get(name) is flight:
                        self._inflight.pop(name, None)
                    flight.done.set()

        if not flight.done.wait(self.wait_timeout):
            with self._lock:
                self._cache.setdefault(name, "unknown")
                if self._inflight.get(name) is flight:
                    self._inflight.pop(name, None)
                flight.done.set()
        with self._lock:
            return self._cache.get(name, "unknown")

    @property
    def used_facts(self) -> tuple[str, ...]:
        with self._lock:
            return tuple(sorted(self._cache))


@dataclass(frozen=True)
class Rule:
    code: str
    event: str
    priority: int
    decision: str
    remedy: str | None
    terminal: bool
    predicate_code: str
    remedy_code: str | None = None


PREDICATE_CODES = frozenset(
    {
        "always",
        "cancelled",
        "timed_out",
        "missing_session",
        "missing_session_mutation",
        "stop_without_target",
    }
)
REMEDY_PREDICATES: Mapping[str, frozenset[str]] = {
    "retry_with_session": frozenset({"missing_session", "missing_session_mutation"})
}


def _predicate_matches(code: str, event: HookEvent) -> bool:
    if code == "always":
        return True
    if code == "missing_session":
        return not event.session_id
    if code == "missing_session_mutation":
        return not event.session_id and event.stateful_mutation
    if code == "cancelled":
        return event.cancelled
    if code == "timed_out":
        return event.timed_out
    if code == "stop_without_target":
        return event.name == "Stop" and not event.target_phase
    return False


@dataclass(frozen=True)
class Effect:
    session_id: str
    event: str
    tool_call_id: str
    rule: str
    effect: str
    payload: Mapping[str, object] = field(default_factory=dict)
    phase: str = ""

    def __post_init__(self) -> None:
        """Reject effects that cannot be scoped to a session."""
        if not self.session_id.strip():
            raise ValueError("effect requires a non-empty session identity")

    @property
    def key(self) -> str:
        rendered = json.dumps(
            [
                self.session_id,
                self.event,
                self.tool_call_id,
                self.rule,
                self.effect,
                self.phase,
            ],
            ensure_ascii=False,
            separators=(",", ":"),
        )
        return hashlib.sha256(rendered.encode("utf-8")).hexdigest()

    def to_record(self) -> dict[str, object]:
        record = {
            "schemaVersion": STATE_SCHEMA_VERSION,
            "identity": CANONICAL_IDENTITY,
            "idempotencyKey": self.key,
            "sessionId": self.session_id,
            "event": self.event,
            "toolCallId": self.tool_call_id,
            "rule": self.rule,
            "effect": self.effect,
            "payloadDigest": hashlib.sha256(
                json.dumps(
                    {"payload": self.payload, "phase": self.phase},
                    sort_keys=True,
                    default=str,
                    separators=(",", ":"),
                ).encode("utf-8")
            ).hexdigest(),
            "phase": self.phase,
        }
        if self.phase:
            if self.phase not in LIFECYCLE_TRANSITIONS:
                raise ValueError("effect lifecycle phase is invalid")
        return record


@dataclass(frozen=True)
class EvaluationReport:
    host: str
    event: str
    phase: str
    decision: str
    diagnostic_code: str
    reason: str
    remedy: str | None
    terminal_reason: str | None
    facts_used: tuple[str, ...] = ()
    effects: tuple[Effect, ...] = ()

    def to_dict(self) -> dict[str, object]:
        return {
            "schemaVersion": SCHEMA_VERSION,
            "identity": CANONICAL_IDENTITY,
            "host": self.host,
            "event": self.event,
            "phase": self.phase,
            "decision": self.decision,
            "diagnosticCode": self.diagnostic_code,
            "reason": self.reason,
            "remedy": self.remedy,
            "factsUsed": list(self.facts_used),
            "effects": [effect.to_record() for effect in self.effects],
            "terminalReason": self.terminal_reason,
        }


RULES = (
    Rule(
        code="CE_CANCELLED",
        event="*",
        priority=300,
        decision="deny",
        remedy=None,
        terminal=True,
        predicate_code="cancelled",
    ),
    Rule(
        code="CE_TIMEOUT",
        event="*",
        priority=200,
        decision="deny",
        remedy=None,
        terminal=True,
        predicate_code="timed_out",
    ),
    Rule(
        code="CE_SESSION_REQUIRED",
        event="PreToolUse",
        priority=100,
        decision="deny",
        remedy="Retry from a host event carrying a unique session identity.",
        terminal=False,
        predicate_code="missing_session_mutation",
        remedy_code="retry_with_session",
    ),
    Rule(
        code="CE_SESSION_MISSING_STOP",
        event="Stop",
        priority=100,
        decision="allow",
        remedy="Configure the host adapter to provide session identity for stateful enforcement.",
        terminal=True,
        predicate_code="missing_session",
    ),
    Rule(
        code="CE_STOP_COMPLETE",
        event="Stop",
        priority=10,
        decision="allow",
        remedy=None,
        terminal=True,
        predicate_code="stop_without_target",
    ),
)


def validate_rules(rules: tuple[Rule, ...]) -> list[str]:
    errors: list[str] = []
    codes: set[str] = set()
    known_events = {
        event
        for capability in HOST_CAPABILITIES.values()
        for event in capability.supported_events
    }
    for index, rule in enumerate(rules):
        if rule.code in codes:
            errors.append(f"duplicate rule code: {rule.code}")
        codes.add(rule.code)
        if rule.predicate_code not in PREDICATE_CODES:
            errors.append(f"unknown predicate code: {rule.code}")
        if rule.event != "*" and rule.event not in known_events:
            errors.append(f"unknown rule event: {rule.code}")
        for prior in rules[:index]:
            events_overlap = rule.event == prior.event or "*" in {rule.event, prior.event}
            if events_overlap and rule.priority == prior.priority:
                scope = "wildcard overlap" if "*" in {rule.event, prior.event} else rule.event
                errors.append(
                    f"conflicting rule semantics at {scope} priority {rule.priority}"
                )
        if rule.decision == "deny" and not rule.terminal:
            if not rule.remedy:
                errors.append(f"nonterminal denial lacks remedy: {rule.code}")
            compatible_predicates = REMEDY_PREDICATES.get(rule.remedy_code or "")
            if compatible_predicates is None:
                errors.append(f"nonterminal denial lacks satisfiable remedy: {rule.code}")
            elif rule.predicate_code not in compatible_predicates:
                errors.append(f"nonterminal denial fails structural remedy: {rule.code}")
    return errors


def validate_lifecycle(
    transitions: Mapping[str, tuple[str, ...]] | None = None,
) -> list[str]:
    transitions = LIFECYCLE_TRANSITIONS if transitions is None else transitions
    errors: list[str] = []
    phases = set(transitions)
    for phase, targets in transitions.items():
        missing = set(targets) - phases
        if missing:
            errors.append(f"{phase} targets unknown phases: {sorted(missing)}")
        if phase in TERMINAL_PHASES and targets:
            errors.append(f"terminal phase has outgoing transitions: {phase}")
        frontier = [phase]
        visited: set[str] = set()
        while frontier:
            current = frontier.pop()
            if current in visited:
                continue
            visited.add(current)
            frontier.extend(transitions.get(current, ()))
        if phase not in TERMINAL_PHASES and not visited.intersection(TERMINAL_PHASES):
            errors.append(f"phase has no terminal path: {phase}")
    colors: dict[str, int] = {}

    def visits_cycle(phase: str) -> bool:
        colors[phase] = 1
        for target in transitions.get(phase, ()):
            if target in TERMINAL_PHASES:
                continue
            if colors.get(target) == 1 or (colors.get(target, 0) == 0 and visits_cycle(target)):
                return True
        colors[phase] = 2
        return False

    for phase in phases - TERMINAL_PHASES:
        if colors.get(phase, 0) == 0 and visits_cycle(phase):
            errors.append("lifecycle contains a nonterminal cycle")
            break
    return errors


def evaluate(
    event: HookEvent, snapshot: HarnessSnapshot | None = None,
    rules: tuple[Rule, ...] = RULES,
) -> EvaluationReport:
    if event.session_id and event.name in {"PreToolUse", "PostToolUse", "PostToolUseFailure"}:
        import importlib.util
        import sys

        module = sys.modules.get("session_token_usage")
        if module is None or not hasattr(module, "note_tool_boundary"):
            overlay = Path(__file__).resolve().parents[1]
            nested = overlay / "runtime" / "session_token_usage.py"
            source = nested if nested.is_file() else overlay / "session_token_usage.py"
            specification = importlib.util.spec_from_file_location("session_token_usage", source)
            if specification is None or specification.loader is None:
                raise RuntimeError("session_token_usage is unavailable")
            module = importlib.util.module_from_spec(specification)
            sys.modules["session_token_usage"] = module
            specification.loader.exec_module(module)
        module.note_tool_boundary(
            event.session_id,
            event.name,
            event.tool_call_id,
            event.tool_name,
        )
    observed = snapshot or HarnessSnapshot()
    current_phase = event.phase
    rule_errors = validate_rules(rules)
    if rule_errors:
        return EvaluationReport(
            host=event.host,
            event=event.name,
            phase=current_phase,
            decision="deny",
            diagnostic_code="CE_INVALID_RULESET",
            reason="Rule registry failed closed validation.",
            remedy="Use only declared events, predicates, and structural remedies.",
            terminal_reason=None,
        )
    if current_phase not in LIFECYCLE_TRANSITIONS:
        return EvaluationReport(
            host=event.host,
            event=event.name,
            phase="ReadOnly",
            decision="deny",
            diagnostic_code="CE_UNKNOWN_PHASE",
            reason=f"Unknown lifecycle phase: {current_phase}",
            remedy="Retry with a phase declared by the lifecycle registry.",
            terminal_reason=None,
        )
    if current_phase in TERMINAL_PHASES:
        return EvaluationReport(
            host=event.host,
            event=event.name,
            phase=current_phase,
            decision="allow" if current_phase == "Complete" else "deny",
            diagnostic_code="CE_TERMINAL_REPLAY",
            reason="Repeated event preserved the existing terminal outcome.",
            remedy=None,
            terminal_reason=current_phase.casefold(),
        )
    known_events = {
        name
        for capability in HOST_CAPABILITIES.values()
        for name in capability.supported_events
    }
    if event.name not in known_events:
        return EvaluationReport(
            host=event.host,
            event=event.name,
            phase="Blocked",
            decision="deny",
            diagnostic_code="CE_UNKNOWN_EVENT",
            reason="Event is missing or is not declared by a supported host capability.",
            remedy=None,
            terminal_reason="blocked",
        )
    applicable = sorted(
        (rule for rule in rules if rule.event in {event.name, "*"}),
        key=lambda rule: (-rule.priority, rule.code),
    )
    for rule in applicable:
        if _predicate_matches(rule.predicate_code, event):
            diagnostic_code = rule.code
            decision = rule.decision
            reason = {
                "CE_CANCELLED": "Lifecycle evaluation was cancelled.",
                "CE_TIMEOUT": "Lifecycle evaluation reached its bounded timeout.",
                "CE_SESSION_REQUIRED": "Stateful lifecycle enforcement requires a unique session identity.",
                "CE_SESSION_MISSING_STOP": "Stop allowed without state lookup because host omitted session identity.",
                "CE_STOP_COMPLETE": "Stop reached a bounded terminal outcome.",
            }.get(rule.code, rule.code)
            next_phase = (
                "Blocked"
                if rule.terminal and rule.decision == "deny"
                else "Complete"
                if rule.terminal and rule.decision == "allow"
                else current_phase
            )
            if (
                rule.code in {"CE_SESSION_MISSING_STOP", "CE_STOP_COMPLETE"}
                and next_phase == "Complete"
                and next_phase not in LIFECYCLE_TRANSITIONS[current_phase]
            ):
                next_phase = "Blocked"
                decision = "deny"
                diagnostic_code = "CE_STOP_INCOMPLETE"
                reason = "Stop reached a bounded blocked outcome before lifecycle completion."
            if (
                next_phase != current_phase
                and next_phase not in LIFECYCLE_TRANSITIONS[current_phase]
            ):
                return EvaluationReport(
                    host=event.host,
                    event=event.name,
                    phase=current_phase,
                    decision="deny",
                    diagnostic_code="CE_INVALID_TRANSITION",
                    reason=(
                        f"Lifecycle transition {current_phase} to {next_phase} is not declared."
                    ),
                    remedy="Request one declared transition from the current phase.",
                    terminal_reason=None,
                    facts_used=observed.used_facts,
                )
            return EvaluationReport(
                host=event.host,
                event=event.name,
                phase=next_phase,
                decision=decision,
                diagnostic_code=diagnostic_code,
                reason=reason,
                remedy=rule.remedy,
                terminal_reason=(
                    "blocked"
                    if rule.terminal and decision == "deny"
                    else "complete"
                    if rule.terminal and decision == "allow"
                    else None
                ),
                facts_used=observed.used_facts,
            )
    next_phase = event.target_phase or current_phase
    if next_phase != current_phase and next_phase not in LIFECYCLE_TRANSITIONS[current_phase]:
        return EvaluationReport(
            host=event.host,
            event=event.name,
            phase=current_phase,
            decision="deny",
            diagnostic_code="CE_INVALID_TRANSITION",
            reason=f"Lifecycle transition {current_phase} to {next_phase} is not declared.",
            remedy="Request one declared transition from the current phase.",
            terminal_reason=None,
            facts_used=observed.used_facts,
        )
    return EvaluationReport(
        host=event.host,
        event=event.name,
        phase=next_phase,
        decision="allow",
        diagnostic_code="CE_OK",
        reason="No lifecycle rule blocked this event.",
        remedy=None,
        terminal_reason=(
            "complete" if next_phase == "Complete" else "blocked" if next_phase == "Blocked" else None
        ),
        facts_used=observed.used_facts,
    )


class JournalCorruptionError(ValueError):
    pass


_EFFECT_FIELDS_V1 = ("sessionId", "event", "toolCallId", "rule", "effect")
_EFFECT_FIELDS = (*_EFFECT_FIELDS_V1, "phase")
_CONTROL_CHARACTER = re.compile(r"[\x00-\x1f\x7f]")


def _v2_effect_key(values: tuple[str, ...]) -> str:
    rendered = json.dumps(list(values), ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(rendered.encode("utf-8")).hexdigest()


def _v1_effect_key(values: tuple[str, ...]) -> str:
    return hashlib.sha256("\0".join(values).encode("utf-8")).hexdigest()


class EffectJournal:
    def __init__(self, path: Path, lock_timeout: float = 5.0):
        """Create a bounded, process-safe journal for one local path."""
        self.path = path
        self.lock_path = path.with_suffix(path.suffix + ".lock")
        self.lock_timeout = lock_timeout

    @staticmethod
    def _try_lock(handle) -> bool:
        try:
            if os.name == "nt":
                import msvcrt

                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl

                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            return True
        except (BlockingIOError, OSError):
            return False

    @staticmethod
    def _unlock(handle) -> None:
        handle.seek(0)
        if os.name == "nt":
            import msvcrt

            msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
        else:
            import fcntl

            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)

    @contextlib.contextmanager
    def _lock(self):
        self.lock_path.parent.mkdir(parents=True, exist_ok=True)
        with self.lock_path.open("a+b") as handle:
            handle.seek(0, os.SEEK_END)
            if handle.tell() == 0:
                handle.write(b"0")
                handle.flush()
            handle.seek(0)
            deadline = time.monotonic() + self.lock_timeout
            while not self._try_lock(handle):
                if time.monotonic() >= deadline:
                    raise TimeoutError(f"effect journal lock timed out after {self.lock_timeout}s")
                time.sleep(min(0.01, max(0.0, deadline - time.monotonic())))
            try:
                yield
            finally:
                self._unlock(handle)

    def _records_unlocked(self, session_id: str) -> list[dict[str, object]]:
        if not self.path.is_file():
            return []
        records: list[dict[str, object]] = []
        for line_number, line in enumerate(
            self.path.read_text(encoding="utf-8").splitlines(), start=1
        ):
            try:
                item = json.loads(line)
            except (json.JSONDecodeError, ValueError) as error:
                raise JournalCorruptionError(
                    f"invalid effect journal JSON at line {line_number}"
                ) from error
            schema_version = item.get("schemaVersion") if isinstance(item, dict) else None
            if not isinstance(item, dict) or not isinstance(schema_version, int) or isinstance(schema_version, bool):
                raise JournalCorruptionError(
                    f"invalid effect journal record at line {line_number}"
                )
            if item["schemaVersion"] not in {1, 2, 3}:
                raise JournalCorruptionError(
                    f"invalid effect journal record at line {line_number}"
                )
            required_strings = [
                "identity",
                "idempotencyKey",
                "sessionId",
                "event",
                "toolCallId",
                "rule",
                "effect",
                "payloadDigest",
            ]
            if item["schemaVersion"] == 3:
                required_strings.append("phase")
            if any(not isinstance(item.get(field), str) for field in required_strings):
                raise JournalCorruptionError(
                    f"invalid effect journal record at line {line_number}"
                )
            fields = (
                _EFFECT_FIELDS if item["schemaVersion"] == 3 else _EFFECT_FIELDS_V1
            )
            effect_values = tuple(str(item[field]) for field in fields)
            if item["schemaVersion"] == 1:
                if any(_CONTROL_CHARACTER.search(value) for value in effect_values):
                    raise JournalCorruptionError(
                        f"invalid effect journal record at line {line_number}"
                    )
                expected_key = _v1_effect_key(effect_values)
            else:
                expected_key = _v2_effect_key(effect_values)
            digest = str(item["payloadDigest"])
            if (
                not _accepted_journal_identity(item["identity"], item["schemaVersion"])
                or not str(item["sessionId"]).strip()
                or item["idempotencyKey"] != expected_key
                or re.fullmatch(r"[0-9a-f]{64}", digest) is None
            ):
                raise JournalCorruptionError(
                    f"invalid effect journal record at line {line_number}"
                )
            phase = item.get("phase", "")
            if phase and phase not in LIFECYCLE_TRANSITIONS:
                raise JournalCorruptionError(
                    f"invalid effect journal record at line {line_number}"
                )
            if item.get("sessionId") == session_id:
                records.append(item)
        return records

    def records(self, session_id: str) -> list[dict[str, object]]:
        if not session_id.strip():
            raise ValueError("journal read requires a non-empty session identity")
        with self._lock():
            return self._records_unlocked(session_id)

    def _append_unlocked(self, effect: Effect) -> bool:
        effect_values = tuple(str(effect.to_record()[field]) for field in _EFFECT_FIELDS)
        if any(
            item.get("idempotencyKey") == effect.key
            or (
                item.get("schemaVersion") == 3
                and tuple(str(item[field]) for field in _EFFECT_FIELDS) == effect_values
            )
            or (
                item.get("schemaVersion") in {1, 2}
                and effect.effect != "lifecycle-phase"
                and tuple(str(item[field]) for field in _EFFECT_FIELDS_V1)
                == effect_values[:-1]
            )
            for item in self._records_unlocked(effect.session_id)
        ):
            return False
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8", newline="\n") as handle:
            handle.write(json.dumps(effect.to_record(), sort_keys=True, separators=(",", ":")))
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        return True

    def append(self, effect: Effect) -> bool:
        with self._lock():
            return self._append_unlocked(effect)


def evaluate_session(
    event: HookEvent,
    journal: EffectJournal,
    snapshot: HarnessSnapshot | None = None,
    rules: tuple[Rule, ...] = RULES,
) -> EvaluationReport:
    """Evaluate and persist one session transition under the journal lock."""
    if not event.session_id:
        return evaluate(event, snapshot, rules)
    with journal._lock():
        records = journal._records_unlocked(event.session_id)
        current_phase = next(
            (
                str(record["phase"])
                for record in reversed(records)
                if record.get("schemaVersion") == 3
                and record.get("effect") == "lifecycle-phase"
                and "phase" in record
            ),
            "ReadOnly",
        )
        report = evaluate(replace(event, phase=current_phase), snapshot, rules)
        if report.phase != current_phase:
            journal._append_unlocked(
                Effect(
                    event.session_id,
                    event.name,
                    event.tool_call_id or event.name,
                    "CE_LIFECYCLE_STATE",
                    "lifecycle-phase",
                    phase=report.phase,
                )
            )
        return report
