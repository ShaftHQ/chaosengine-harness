#!/usr/bin/env python3
"""Shared lifecycle context, dispatch, and protocol for every launcher."""

from __future__ import annotations

import contextlib
import inspect
import os
import io
import json
import re
import sys
from collections.abc import Callable, Mapping
from pathlib import Path


def _overlay_module(name: str) -> Path:
    """Prefer runtime/<name> at the tree root; fall back to a flat file."""
    tree = Path(__file__).resolve().parents[1]
    nested = tree / "runtime" / name
    return nested if nested.is_file() else tree / name



COMPANION_NAMES = ("caveman", "ponytail")
ADVISORY_COMPANION_NAMES = ("icm-architect",)
# Hard budget for SessionStart additionalContext (#5580).
# Companions and skills stay locators. Identity inlines Truth and Principles.
SESSION_START_MAX_BYTES = 4096
# Parity smoke in test_builder_stays_under_byte_budget_and_omits_skill_bodies:
# len(context) // 4 <= 512. Compact the identity body before crossing it.
_SESSION_START_SOFT_TOKENS = 512
_IDENTITY_RELATIVES = ("identity.md", ".chaos-engine/identity.md", "chaos-engine/identity.md")
_IDENTITY_SECTIONS = frozenset({"truth", "principles"})
_LINK_TARGET = re.compile(r"\[([^\]]+)\]\([^)]*\)")
_HTML_COMMENT = re.compile(r"<!--.*?-->", re.DOTALL)
TOKEN_BUDGET_DEFAULT = "balanced"
TOKEN_BUDGET_MODES = {
    "ultra-lean": {
        "read_line_budget": 80,
        "guidance": (
            "Token budget ultra-lean: ≤80-line excerpts; one search; script-first. "
            "Details: chaos-engine/references/token-budget-modes.md"
        ),
    },
    "balanced": {
        "read_line_budget": 200,
        "guidance": (
            "Token budget balanced (default): ≤200-line excerpts; narrow once after "
            "truncation; prefer path+excerpt over dumps; script-first when multi-hop. "
            "Details: chaos-engine/references/token-budget-modes.md"
        ),
    },
    "deep": {
        "read_line_budget": 400,
        "guidance": (
            "Token budget deep: ≤400-line excerpts; allow a second discriminating pass "
            "before deciding; spill large tool output to disk; still prefer script-first "
            "for mechanical transforms; keep safety and negation intact. "
            "Details: chaos-engine/references/token-budget-modes.md"
        ),
    },
}


def resolve_token_budget_mode(environ: Mapping[str, str] | None = None) -> str:
    """Return the owner-selected token budget mode (default balanced)."""
    env = environ if environ is not None else os.environ
    raw = str(env.get("CHAOS_ENGINE_TOKEN_BUDGET") or TOKEN_BUDGET_DEFAULT).strip().casefold()
    # Accept common aliases
    aliases = {"lean": "ultra-lean", "ultra_lean": "ultra-lean", "default": "balanced"}
    raw = aliases.get(raw, raw)
    if raw not in TOKEN_BUDGET_MODES:
        return TOKEN_BUDGET_DEFAULT
    return raw


def token_budget_guidance(mode: str | None = None) -> str:
    """Return the compact guidance string for a mode (fixture + SessionStart)."""
    selected = mode or TOKEN_BUDGET_DEFAULT
    if selected not in TOKEN_BUDGET_MODES:
        selected = TOKEN_BUDGET_DEFAULT
    return str(TOKEN_BUDGET_MODES[selected]["guidance"])


# Triage (blast radius) → default token budget when env unset (#5621).
# Env CHAOS_ENGINE_TOKEN_BUDGET remains the owner override.
TRIAGE_TO_TOKEN_BUDGET = {
    "one-file": "ultra-lean",
    "one-module": "balanced",
    "module": "balanced",
    "public-contract": "deep",
}



def triage_token_budget(triage: str | None) -> str:
    """Map triage blast-radius label to the default token budget mode."""
    raw = str(triage or "").strip().casefold().replace("_", "-").replace(" ", "-")
    aliases = {
        "onefile": "one-file",
        "file": "one-file",
        "onemodule": "one-module",
        "public": "public-contract",
        "contract": "public-contract",
        "hard-to-reverse": "public-contract",
    }
    raw = aliases.get(raw, raw)
    return TRIAGE_TO_TOKEN_BUDGET.get(raw, TOKEN_BUDGET_DEFAULT)


ULTRA_SELECTOR = (
    "ChaosEngine companion intensity: caveman=ultra; ponytail=ultra. "
    "Off only: stop caveman, stop ponytail, or normal mode."
)
LIFECYCLE_EVENTS = (
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
HOOK_PROTOCOL_ERROR = "Lifecycle hook produced invalid JSON output."


def _skill_relatives(name: str) -> tuple[str, ...]:
    return (
        f"vendor/{name}/skills/{name}/SKILL.md",
        f"plugins/{name}/skills/{name}/SKILL.md",
        f"{name}/skills/{name}/SKILL.md",
        f"chaos-engine/vendor/{name}/skills/{name}/SKILL.md",
    )


def _search_roots() -> list[Path]:
    here = Path(__file__).resolve().parent
    candidates = [here, *here.parents]
    try:
        cwd = Path.cwd().resolve()
    except OSError:
        cwd = None
    if cwd is not None:
        candidates.extend((cwd, *cwd.parents))
    return list(dict.fromkeys(candidates))


def _workspace_locator(path: Path) -> str:
    """Return a companion path resolvable from the active project root."""
    anchors = (
        Path(".agents/skills/chaos-engine/SKILL.md"),
        Path(".chaos-engine/skills/chaos-engine/SKILL.md"),
        Path("chaos-engine/skills/chaos-engine/SKILL.md"),
        Path("skills/chaos-engine/SKILL.md"),
    )
    # Source checkouts keep the skill at skills/chaos-engine/SKILL.md. The same
    # relative path also exists inside an installed .chaos-engine/ tree; that
    # directory is not the project root the agent resolves from.
    source_anchor = Path("skills/chaos-engine/SKILL.md")
    for root in _search_roots():
        matched = [anchor for anchor in anchors if (root / anchor).is_file()]
        if not matched:
            continue
        if matched == [source_anchor] and root.name == ".chaos-engine":
            continue
        try:
            return path.resolve().relative_to(root.resolve()).as_posix()
        except (OSError, ValueError):
            continue
    return path.as_posix()


SESSION_START_LEAN_MAX_BYTES = 600
TOOL_OUTPUT_LOCATOR = "tool-output: ready; python3 .chaos-engine/tool.py output-search QUERY"
COMPANION_CARDS = {
    "caveman": "companions/caveman-ultra.md",
    "ponytail": "companions/ponytail-ultra.md",
}


def _locate(relatives: tuple[str, ...]) -> str | None:
    for root in _search_roots():
        for relative in relatives:
            path = root / relative
            if path.is_file():
                return _workspace_locator(path)
    return None


def stopped_companion_names(text: str) -> frozenset[str]:
    """Ultra cards stay on until ``stop caveman``, ``stop ponytail``, or ``normal mode``."""
    folded = str(text or "").casefold()
    if "normal mode" in folded:
        return frozenset(COMPANION_CARDS)
    stopped = set()
    if "stop caveman" in folded:
        stopped.add("caveman")
    if "stop ponytail" in folded:
        stopped.add("ponytail")
    return frozenset(stopped)


def _companion_opt_out_path(session_id: str) -> Path:
    safe = "".join(character for character in str(session_id) if character.isalnum() or character in "-_")[:80]
    return Path.cwd() / ".chaos-engine-state" / "companion-opt-out" / (safe or "session")


def record_companion_opt_out(session_id: str, text: str) -> frozenset[str]:
    """Remember a stop phrase for this session. A later SessionStart reads it."""
    stopped = stopped_companion_names(text)
    if not stopped:
        return read_stopped_companions(session_id)
    path = _companion_opt_out_path(session_id)
    current = set(read_stopped_companions(session_id))
    current.update(stopped)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(" ".join(sorted(current)) + "\n", encoding="utf-8")
    return frozenset(current)


def read_stopped_companions(session_id: str) -> frozenset[str]:
    path = _companion_opt_out_path(session_id)
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return frozenset()
    return frozenset(part for part in text.split() if part in COMPANION_CARDS)


def stamp_cards_loaded(session_id: str = "") -> None:
    """CLI twin of `tool.py entry --full`: SessionStart re-injects the cards, so write the same load stamp."""
    installed = Path(__file__).resolve().parents[1]
    tool_path = installed / "tool.py"
    if installed.name != ".chaos-engine" or not tool_path.is_file():
        return
    import importlib.util

    spec = importlib.util.spec_from_file_location("_chaos_engine_tool_stamp", tool_path)
    if spec is None or spec.loader is None:
        return
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    stopped = read_stopped_companions(session_id)
    module.write_entry_stamp(installed, " ".join(f"stop {name}" for name in sorted(stopped)))


def _tool_output_store():
    cached = getattr(_tool_output_store, "module", None)
    if cached is not None:
        return cached
    path = _overlay_module("tool_output_store.py")
    if not path.is_file():
        return None
    import importlib.util

    spec = importlib.util.spec_from_file_location("ce_tool_output_store_locator", path)
    if spec is None or spec.loader is None:
        return None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    _tool_output_store.module = module
    return module


def _tool_output_locator() -> str:
    """One stable line when the project store has a row. Absent store adds nothing."""
    with contextlib.suppress(Exception):
        module = _tool_output_store()
        if module is not None and module.has_row(Path.cwd()):
            return TOOL_OUTPUT_LOCATOR
    return ""


def _identity_match() -> tuple[str, Path] | None:
    """Return the workspace locator and file for the first identity.md found."""
    for root in _search_roots():
        for relative in _IDENTITY_RELATIVES:
            path = root / relative
            try:
                if path.is_file():
                    return _workspace_locator(path), path
            except OSError:
                continue
    return None


def _read_identity(path: Path) -> str | None:
    try:
        return path.read_text(encoding="utf-8")
    except (OSError, UnicodeError):
        return None


def _identity_principle_lines(text: str, *, compact: bool) -> str:
    """Truth and Principles bullets. Wrapped continuations become one line each."""
    cleaned = _HTML_COMMENT.sub("", text)
    section = ""
    bullets: list[str] = []
    for raw in cleaned.splitlines():
        if raw.startswith("#"):
            section = raw.lstrip("#").strip().casefold() if raw.startswith("##") else ""
            continue
        stripped = raw.strip()
        if not stripped or stripped.startswith("Refine outside"):
            continue
        if section not in _IDENTITY_SECTIONS:
            continue
        if stripped.startswith("- "):
            bullets.append(stripped)
        elif bullets and raw[:1].isspace():
            bullets[-1] = f"{bullets[-1]} {stripped}"
    rendered = "\n".join(bullets)
    if compact:
        rendered = _LINK_TARGET.sub(r"\1", rendered)
    return rendered


def _identity_over_soft(rendered: str) -> bool:
    return len(rendered.encode("utf-8")) // 4 > _SESSION_START_SOFT_TOKENS


def _identity_over_hard(rendered: str) -> bool:
    return len(rendered.encode("utf-8")) > SESSION_START_MAX_BYTES


def _identity_context_block(base: str, suffix: str = "") -> str:
    """Identity body, or the path locator when the file is missing or too wide."""
    match = _identity_match()
    locator = match[0] if match else None
    fallback = f"Identity: `{locator or '.chaos-engine/identity.md'}`"
    if match is None:
        return fallback
    text = _read_identity(match[1])
    if not text:
        return fallback
    header = f"Identity (`{locator}`):"
    full_body = _identity_principle_lines(text, compact=False)
    compact_body = _identity_principle_lines(text, compact=True)
    for body in (full_body, compact_body):
        if not body:
            continue
        block = f"{header}\n{body}"
        rendered = f"{base}\n{block}"
        if suffix:
            rendered = f"{rendered}\n{suffix}"
        if _identity_over_hard(rendered):
            continue
        # Keep the link targets when the parity smoke still passes.
        if body is full_body and _identity_over_soft(rendered):
            continue
        return block
    return fallback


def _pinned_release_fetcher():
    """Env pin or feed. None when the check should use the network fetcher."""
    feed = os.environ.get("CHAOS_ENGINE_RELEASE_FEED", "").strip()
    pinned = os.environ.get("CHAOS_ENGINE_RELEASE_VERSION", "").strip()
    if not feed and not pinned:
        return None

    def fetcher():
        if feed:
            payload = Path(feed).read_text(encoding="utf-8")
            try:
                return json.loads(payload)
            except json.JSONDecodeError:
                return payload.strip()
        return pinned

    return fetcher


def _note_session_start_update() -> str:
    """Ask whether a newer release exists. Never block and never rewrite files.

    Pytest sets PYTEST_CURRENT_TEST. Skip the network then. A pin or feed
    still reports, so one call site covers both the session and the tests.
    """
    fetcher = _pinned_release_fetcher()
    if os.environ.get("PYTEST_CURRENT_TEST") and fetcher is None:
        return ""
    path = _overlay_module("update_check.py")
    if not path.is_file():
        return ""
    try:
        import importlib.util

        spec = importlib.util.spec_from_file_location("ce_update_check", path)
        if spec is None or spec.loader is None:
            return ""
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        confirm = os.environ.get("CHAOS_ENGINE_APPLY_UPDATE", "").strip() == "1"
        if fetcher is None:
            status = module.session_start_update_check()
        else:
            status = module.session_start_update_check(fetcher, confirm=confirm)
    except Exception:
        return ""
    if isinstance(status, str) and (
        status.startswith("update available:") or status.startswith("update confirmed:")
    ):
        return "ChaosEngine " + status
    return ""


def session_start_context(token: str | None, activation: str, session_id: str = "") -> str:
    """Return SessionStart context within SESSION_START_MAX_BYTES.

    Companions and skills stay locators. Identity is the Truth and Principles
    bullets, or the path locator when the file is missing, unreadable, or the
    body would exceed the byte budget.
    """
    update_note = _note_session_start_update()
    with contextlib.suppress(Exception):
        stamp_cards_loaded(session_id)
    parts = [f"ChaosEngine: {activation}"]
    if update_note:
        parts.append(update_note)
    if token:
        parts.append(f"Token (never track it): {token}")
    stopped = read_stopped_companions(session_id)
    cards = [
        _locate((card, f".chaos-engine/{card}", f"chaos-engine/{card}"))
        or f".chaos-engine/{card}"
        for name, card in COMPANION_CARDS.items()
        if name not in stopped
    ]
    parts.append(
        "Companions (caveman=ultra; ponytail=ultra; off only: stop caveman, stop ponytail, "
        "normal mode): " + ", ".join(f"`{card}`" for card in cards)
    )
    for name in ADVISORY_COMPANION_NAMES:
        path = next(
            (
                root / candidate
                for root in _search_roots()
                for candidate in _skill_relatives(name)
                if (root / candidate).is_file()
            ),
            None,
        )
        if path is not None:
            parts.append(
                "Advisory companion (design/structure): load "
                f"`{_workspace_locator(path).removeprefix('chaos-engine/')}`"
            )
    tail = [
        "Ethics: `companions/ethics-card.md`",
        f"Token budget: {resolve_token_budget_mode()}",
    ]
    base = "\n".join(parts)
    parts.append(_identity_context_block(base, "\n".join(tail)))
    parts.extend(tail)
    rendered = "\n".join(parts)
    locator = _tool_output_locator()
    if locator:
        candidate = f"{rendered}\n{locator}"
        # Omit the locator rather than cross the hard cap, and do not let it
        # push a fitting identity body over the parity smoke.
        within_hard = len(candidate.encode("utf-8")) <= SESSION_START_MAX_BYTES
        keeps_smoke = not _identity_over_soft(candidate) or _identity_over_soft(rendered)
        if within_hard and keeps_smoke:
            rendered = candidate
    with contextlib.suppress(Exception):
        counters_path = _overlay_module("learning_counters.py")
        if counters_path.is_file():
            import importlib.util as _ilu

            _spec = _ilu.spec_from_file_location("ce_learning_counters_ss", counters_path)
            if _spec is not None and _spec.loader is not None:
                _mod = _ilu.module_from_spec(_spec)
                _spec.loader.exec_module(_mod)
                _mod.record_session_start_bytes(len(rendered.encode("utf-8")))
    return rendered


def _reject_json_constant(value: str):
    raise ValueError(f"non-standard JSON constant: {value}")


def _strict_json_loads(rendered: str):
    return json.loads(rendered, parse_constant=_reject_json_constant)


def _write_json(output: dict, stream=None) -> None:
    target = sys.stdout if stream is None else stream
    target.write(json.dumps(output, separators=(",", ":"), allow_nan=False) + "\n")


def _native_event_name(raw_event: Mapping[str, object]) -> str:
    """Host event name before canonical aliases. SubagentStart must survive."""
    for key in ("hook_event_name", "hookEventName"):
        value = raw_event.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def _call_adapt(adapt_output, output: dict, event_name: str, host: str, native_event: str):
    """Pass native_event only when the adapter accepts that keyword."""
    try:
        parameters = inspect.signature(adapt_output).parameters
    except (TypeError, ValueError):
        return adapt_output(output, event_name, host)
    accepts_native = "native_event" in parameters or any(
        item.kind is inspect.Parameter.VAR_KEYWORD for item in parameters.values()
    )
    if accepts_native:
        return adapt_output(output, event_name, host, native_event=native_event)
    return adapt_output(output, event_name, host)


def run_hook_protocol(
    raw: str,
    callbacks: Mapping[str, Callable[[dict, str], int]],
    *,
    normalize: Callable[[dict], dict] = dict,
    host_for_input: Callable[[dict], str] = lambda _raw: "portable",
    prepare: Callable[[dict], None] = lambda _event: None,
    adapt_output: Callable[[dict, str, str], dict] = lambda output, _event, _host: output,
    fallback: Callable[[str, str], dict] = lambda event, _host: (
        {"decision": "block", "reason": HOOK_PROTOCOL_ERROR}
        if event in {"PreToolUse", "Stop", "SubagentStop"}
        else {}
    ),
) -> int:
    """Parse, dispatch, contain callback output, and emit one JSON object."""
    if not raw.strip():
        _write_json({})
        return 0
    try:
        raw_event = _strict_json_loads(raw)
    except (json.JSONDecodeError, ValueError, RecursionError):
        _write_json({})
        return 0
    if not isinstance(raw_event, dict):
        _write_json({})
        return 0
    event = normalize(raw_event)
    event_name = event.get("hook_event_name", "PreToolUse")
    if not isinstance(event_name, str) or event_name not in LIFECYCLE_EVENTS:
        _write_json({})
        return 0
    callback = callbacks.get(event_name)
    if callback is None:
        _write_json({})
        return 0
    host = host_for_input(raw_event)
    native_event = _native_event_name(raw_event)
    captured = io.StringIO()
    result = 0
    try:
        prepare(event)
        with contextlib.redirect_stdout(captured):
            result = callback(event, host)
        rendered = captured.getvalue().strip()
        output = {} if not rendered else _strict_json_loads(rendered)
        if not isinstance(output, dict):
            raise ValueError("hook output is not a JSON object")
        output = _call_adapt(adapt_output, output, event_name, host, native_event)
        if not isinstance(output, dict):
            raise ValueError("adapted hook output is not a JSON object")
        json.dumps(output, allow_nan=False)
    except (Exception, KeyboardInterrupt, SystemExit) as error:
        print(f"Hook protocol error: {error}", file=sys.stderr)
        try:
            output = _call_adapt(adapt_output, fallback(event_name, host), event_name, host, native_event)
            if not isinstance(output, dict):
                raise ValueError("adapted fallback output is not a JSON object")
            json.dumps(output, allow_nan=False)
        except (Exception, KeyboardInterrupt, SystemExit) as fallback_error:
            print(f"Hook fallback error: {fallback_error}", file=sys.stderr)
            output = {}
        result = 0
    _write_json(output, sys.stderr if host == "claude" and result == 2 else sys.stdout)
    return result
