"""Offline host-doc layout and docs-drift checks.

Reads a fixture tree and pinned hashes. Does not start a vendor CLI and does
not call a model API. A withheld network or HTTP 5xx is an error or a
skip-with-warning, never a pass. Live multi-model runs stay future.
"""

from __future__ import annotations

import hashlib
import json
import re
import sys
import tomllib
from pathlib import Path
from typing import Callable

FIXTURE = Path(__file__).resolve().parents[1] / "evals" / "host-doc-conformance.json"
GOLDEN_CORPUS = Path(__file__).resolve().parents[1] / "evals" / "golden-tasks" / "corpus.json"
TOOL_IDS = ("claude", "codex", "gemini", "cursor", "grok")
EXAMPLE_BLOCK = re.compile(r"<!--\s*host-doc-example:\s*(\S+)\s*(.*?)-->", re.DOTALL)
Fetch = Callable[[str], tuple[int, bytes]]


def load_fixture(path: Path | None = None) -> dict:
    """Load the committed host-doc fixture."""
    return json.loads((path or FIXTURE).read_text(encoding="utf-8"))


def excerpt_hash(excerpt: str) -> str:
    """SHA-256 of a recorded pin excerpt. Not a live page fetch."""
    return hashlib.sha256(excerpt.encode("utf-8")).hexdigest()


_INSTRUCTION_CONFLICT_IDS = (
    "IC-01",
    "IC-02",
    "IC-03",
    "IC-04",
    "IC-05",
    "IC-06",
    "IC-07",
    "IC-10",
)
_INSTRUCTION_REQUIRED_GLOBS = (".claude/settings.json",)


def check_instruction_catalog(
    tree: Path,
    marker_policy_files: tuple[str, ...] | list[str],
) -> list[str]:
    """Fail when host marker paths drift out of the instruction inventory.

    ``marker_policy_files`` is the host module's marker list. Both instruction
    JSON files must exist. A host path that is not a class I glob fails CI.
    """
    root = Path(tree)
    errors: list[str] = []
    inventory_path = root / "references" / "instruction-inventory.json"
    conflicts_path = root / "references" / "instruction-conflicts.json"
    if not inventory_path.is_file():
        errors.append("missing required path references/instruction-inventory.json")
    if not conflicts_path.is_file():
        errors.append("missing required path references/instruction-conflicts.json")
    if errors:
        return errors
    try:
        inventory = json.loads(inventory_path.read_text(encoding="utf-8"))
        conflicts = json.loads(conflicts_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        return [f"unreadable instruction catalog ({exc})"]
    globs = {
        str(row.get("glob"))
        for row in inventory.get("class_i", [])
        if isinstance(row, dict)
    }
    for relative in tuple(marker_policy_files) + _INSTRUCTION_REQUIRED_GLOBS:
        if relative not in globs:
            errors.append(f"instruction inventory missing class_i glob {relative}")
    ids = {
        str(row.get("id"))
        for row in conflicts.get("rules", [])
        if isinstance(row, dict)
    }
    for required in _INSTRUCTION_CONFLICT_IDS:
        if required not in ids:
            errors.append(f"instruction conflicts missing {required}")
    return errors


def check_layout(tree: Path, fixture: dict | None = None) -> list[str]:
    """Fail a wrong filename, a missing required path, or a disallowed config key."""
    spec = fixture if fixture is not None else load_fixture()
    root = Path(tree)
    errors: list[str] = []
    for relative in spec.get("required_paths", []):
        if not (root / relative).is_file():
            errors.append(f"missing required path {relative}")
    for relative in spec.get("forbidden_filenames", []):
        if (root / relative).exists():
            errors.append(f"policy at disallowed filename {relative}")
    for relative, limit in spec.get("max_lines", {}).items():
        path = root / relative
        if path.is_file() and len(path.read_text(encoding="utf-8").splitlines()) > int(limit):
            errors.append(f"{relative} exceeds {limit} lines")
    for relative, limit in spec.get("max_bytes", {}).items():
        path = root / relative
        if path.is_file() and path.stat().st_size > int(limit):
            errors.append(f"{relative} exceeds {limit} bytes")
    for relative, allowed in spec.get("config_files", {}).items():
        path = root / relative
        if not path.is_file():
            continue
        try:
            keys = _config_keys(path)
        except (OSError, UnicodeDecodeError, json.JSONDecodeError, tomllib.TOMLDecodeError, ValueError) as exc:
            errors.append(f"{relative}: unreadable config ({exc})")
            continue
        allowed_keys = set(allowed.get("keys", []))
        for key in sorted(keys - allowed_keys):
            errors.append(f"disallowed config key {key} in {relative}")
        nested = _context_keys(path)
        if nested is not None:
            allowed_context = set(allowed.get("context_keys", []))
            for key in sorted(nested - allowed_context):
                errors.append(f"disallowed config key context.{key} in {relative}")
    rules_dir = spec.get("cursor_rules_dir")
    if rules_dir:
        rules = root / rules_dir
        if rules.is_dir():
            for path in sorted(rules.iterdir()):
                if path.is_file() and path.suffix == ".md":
                    errors.append(f"cursor: plain markdown rule is ignored: {path.name}")
    return errors


def _config_keys(path: Path) -> set[str]:
    data = _load_config(path)
    if not isinstance(data, dict):
        raise ValueError("config is not an object")
    return {str(key) for key in data}


def _context_keys(path: Path) -> set[str] | None:
    data = _load_config(path)
    if not isinstance(data, dict):
        return None
    context = data.get("context")
    if not isinstance(context, dict):
        return None
    return {str(key) for key in context}


def _load_config(path: Path) -> object:
    text = path.read_text(encoding="utf-8")
    if path.suffix == ".json":
        return json.loads(text)
    if path.suffix == ".toml":
        return tomllib.loads(text)
    raise ValueError(f"unsupported config type {path.suffix}")


def check_docs_drift(pins: list[dict], fetch: Fetch) -> list[dict]:
    """Compare each pin to fetch(url). Fetch failure is never a pass.

    status is pass, fail, error, or skip-with-warning.
    HTTP 5xx is skip-with-warning. A connection failure is error.
    A hash mismatch fails and names the pin.
    """
    results: list[dict] = []
    if not pins:
        return [{"pin": "", "status": "error", "detail": "no pins to check"}]
    for pin in pins:
        results.append(_one_pin(pin, fetch))
    return results


def _drift_classification(status: str) -> str:
    """Map a pin result to unchanged, changed, or fetch-failed.

    A withheld network or an HTTP error is fetch-failed. It is never unchanged.
    """
    if status == "pass":
        return "unchanged"
    if status == "fail":
        return "changed"
    return "fetch-failed"


def _drift_row(label: str, status: str, detail: str) -> dict:
    return {
        "pin": label,
        "status": status,
        "classification": _drift_classification(status),
        "detail": detail,
    }


def _one_pin(pin: dict, fetch: Fetch) -> dict:
    url = str(pin.get("url") or "")
    expected = str(pin.get("content_sha256") or "")
    label = url or str(pin.get("id") or "pin")
    if not url or not expected:
        return _drift_row(label, "error", f"incomplete pin {label}")
    try:
        status, body = fetch(url)
    except Exception as exc:
        return _drift_row(label, "error", f"withheld network for {label}: {exc}")
    if status is None:
        return _drift_row(label, "error", f"withheld network for {label}")
    if int(status) >= 500:
        return _drift_row(
            label,
            "skip-with-warning",
            f"HTTP {status} for {label}; update is unknown, not a pass",
        )
    if int(status) != 200:
        return _drift_row(label, "error", f"HTTP {status} for {label}")
    actual = hashlib.sha256(body).hexdigest()
    if actual != expected:
        return _drift_row(label, "fail", f"docs drift for {label}: update the fixture")
    return _drift_row(label, "pass", f"unchanged {label}")


def check_tool_layouts(tree: Path, fixture: dict | None = None) -> dict[str, list[str]]:
    """Layout errors for Claude Code, Codex, Gemini CLI, Cursor, and Grok."""
    spec = fixture if fixture is not None else load_fixture()
    tools = spec.get("tools") or {}
    found: dict[str, list[str]] = {}
    for tool in TOOL_IDS:
        tool_spec = tools.get(tool)
        if not isinstance(tool_spec, dict):
            found[tool] = [f"missing pin for {tool}"]
            continue
        found[tool] = check_layout(tree, tool_spec)
    return found


def _example_fields(body: str) -> dict[str, str]:
    fields: dict[str, str] = {}
    for line in body.splitlines():
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        fields[key.strip()] = value.strip()
    return fields


def published_example_findings(pages_dir: Path, fixture: dict | None = None) -> list[str]:
    """Fail or warn when a tool-page example disagrees with its pin.

    A wrong entry filename fails. A config key the pin does not allow warns.
    """
    spec = fixture if fixture is not None else load_fixture()
    findings: list[str] = []
    pages = Path(pages_dir)
    for tool in TOOL_IDS:
        page = pages / f"{tool}.md"
        if not page.is_file():
            findings.append(f"fail: missing tool page {tool}.md")
            continue
        text = page.read_text(encoding="utf-8")
        match = EXAMPLE_BLOCK.search(text)
        if match is None or match.group(1) != tool:
            findings.append(f"fail: {tool}.md has no host-doc example")
            continue
        fields = _example_fields(match.group(2))
        tool_spec = spec.get("tools", {}).get(tool) or {}
        forbidden = set(spec.get("forbidden_filenames", [])) | set(tool_spec.get("forbidden_filenames", []))
        required = list(tool_spec.get("required_paths", []))
        entry = fields.get("entry", "")
        if not entry or entry in forbidden or (required and entry not in required):
            findings.append(f"fail: {tool}.md example entry {entry or '(blank)'} disagrees with the pin")
        for relative in [item.strip() for item in fields.get("paths", "").split(",") if item.strip()]:
            if relative in forbidden or Path(relative).name in forbidden:
                findings.append(f"fail: {tool}.md example path {relative} disagrees with the pin")
        allowed: set[str] = set()
        for cfg in (tool_spec.get("config_files") or {}).values():
            if isinstance(cfg, dict):
                allowed.update(str(key) for key in cfg.get("keys", []))
                allowed.update(f"context.{key}" for key in cfg.get("context_keys", []))
        for key in [item.strip() for item in fields.get("config_keys", "").split(",") if item.strip()]:
            if key not in allowed:
                findings.append(f"warn: {tool}.md example config key {key} is not in the pin")
    return findings


def ledger_check_status(check: dict) -> str:
    """Pass only a check that ran and was measured. Otherwise skipped or unknown."""
    if not isinstance(check, dict):
        return "unknown"
    if check.get("ran") is False or str(check.get("status") or "").casefold() in {"skipped", "skip"}:
        return "skipped"
    if check.get("measured") is not True or check.get("ran") is not True:
        return "unknown"
    outcome = str(check.get("status") or "").casefold()
    if outcome == "pass" or check.get("ok") is True:
        return "pass"
    if outcome == "fail" or check.get("ok") is False:
        return "fail"
    return "unknown"


def score_golden_ledger(checks: list[dict]) -> dict:
    """Overall status. An unmeasured or skipped check cannot make the ledger a pass."""
    rows = [
        {"id": str(check.get("id") or ""), "status": ledger_check_status(check)}
        for check in checks
    ]
    statuses = [row["status"] for row in rows]
    if not statuses or any(item == "unknown" for item in statuses):
        overall = "unknown"
    elif any(item == "fail" for item in statuses):
        overall = "fail"
    elif any(item == "skipped" for item in statuses):
        overall = "skipped"
    else:
        overall = "pass"
    return {"checks": rows, "overall": overall}


def load_golden_corpus(path: Path | None = None) -> dict:
    return json.loads((path or GOLDEN_CORPUS).read_text(encoding="utf-8"))


def run_golden_task(task: dict) -> dict:
    """Score one corpus task from its recorded checks. No model and no vendor CLI."""
    checks = task.get("checks") if isinstance(task, dict) else None
    return score_golden_ledger(list(checks or []))


# Event tokens a live page may add. A hit that is not in the pin is
# `drift: review` and is never written back into the fixture.
_HOOKISH = re.compile(
    r"(?<![A-Za-z0-9_.])("
    r"tool\.execute\.before|tool\.execute\.after|execute\.before|execute\.after|"
    r"session\.created|session\.idle|"
    r"PostToolUseFailure|PostToolUse|PreToolUse|UserPromptSubmit|"
    r"SubagentStart|SubagentStop|SessionStart|SessionEnd|"
    r"PreCompact|PostCompact|PermissionRequest|ElicitationResult|Elicitation|"
    r"PreModelRequest|PostModelRequest|Interrupt|Notification|"
    r"StopFailure|StopCancelled|workspaceOpen|updatedToolOutput|"
    r"BeforeTool|AfterTool|BeforeAgent|AfterAgent|PreCompress|"
    r"PreInvocation|PostInvocation|"
    r"beforeSubmitPrompt|userPromptSubmitted|postToolUseFailure|postToolUse|"
    r"preToolUse|subagentStart|subagentStop|sessionStart|sessionEnd|"
    r"agentStop|preCompact|"
    r"post_tool_use_failure|user_prompt_submit|pre_tool_use|post_tool_use|"
    r"subagent_stop|session_start|session_end|"
    r"Stop|stop"
    r")(?![A-Za-z0-9_.])"
)


def _hook_pin_map(pins: list[dict]) -> dict[str, dict]:
    found: dict[str, dict] = {}
    for pin in pins:
        host = str(pin.get("host") or "")
        if host:
            found[host] = pin
    return found


def production_hook_registry() -> dict[str, set[str]]:
    """Native names ChaosEngine registers or aliases, read from the shipped code."""
    root = str(Path(__file__).resolve().parents[1])
    if root not in sys.path:
        sys.path.insert(0, root)
    from hooks.kernel import HOST_CAPABILITIES
    from runtime.hook_surfaces import (
        OPENCODE_NATIVE_EVENTS,
        antigravity_hook_events,
        antigravity_hooks_document,
        cursor_hooks_document,
    )
    from runtime.hosts import copilot_hooks_document, gemini_hooks_document, lifecycle_hooks_document

    documents = {
        "claude": set(json.loads(lifecycle_hooks_document("claude"))["hooks"]),
        "codex": set(json.loads(lifecycle_hooks_document("codex"))["hooks"]),
        "grok": set(json.loads(lifecycle_hooks_document("grok"))["hooks"]),
        "gemini": set(json.loads(gemini_hooks_document())["hooks"]),
        "copilot": set(json.loads(copilot_hooks_document())["hooks"]),
        "cursor": set(cursor_hooks_document()["hooks"]),
        "opencode": set(OPENCODE_NATIVE_EVENTS),
        "antigravity": antigravity_hook_events(antigravity_hooks_document()),
    }
    registry: dict[str, set[str]] = {}
    for host, names in documents.items():
        capability = HOST_CAPABILITIES.get(host)
        aliases = set(capability.event_aliases) if capability is not None else set()
        registry[host] = set(names) | aliases
    return registry


NINE_HOST_LABELS = (
    ("claude", "Claude"),
    ("codex", "Codex"),
    ("grok", "Grok"),
    ("gemini", "Gemini"),
    ("copilot", "Copilot"),
    ("opencode", "OpenCode"),
    ("cursor", "Cursor"),
    ("antigravity", "Antigravity"),
    ("grok-bot", "Grok Bot"),
)


def host_parity_score(tree: Path | None = None) -> tuple[int, int]:
    """(ready, 9). Each host needs a guide and a matrix label.

    grok-bot stays out of production_hook_registry. CLAUDE.md and GEMINI.md,
    when present, must stay a single @AGENTS.md pointer.
    """
    root = Path(tree) if tree is not None else Path(__file__).resolve().parents[1]
    guides = root / "guides" / "tools"
    matrix_path = root / "references" / "host-parity-matrix.md"
    try:
        matrix_text = matrix_path.read_text(encoding="utf-8")
    except OSError:
        matrix_text = ""
    ready = 0
    for host, label in NINE_HOST_LABELS:
        guide = guides / f"{host}.md"
        try:
            text = guide.read_text(encoding="utf-8")
        except OSError:
            continue
        if host not in text:
            continue
        if label not in matrix_text and host not in matrix_text:
            continue
        ready += 1
    pointers_ok = True
    for name in ("CLAUDE.md", "GEMINI.md"):
        path = root / name
        if not path.is_file():
            continue
        try:
            body = path.read_text(encoding="utf-8").replace("\r\n", "\n").strip()
        except OSError:
            pointers_ok = False
            continue
        if body != "@AGENTS.md":
            pointers_ok = False
    if not pointers_ok:
        ready = max(0, ready - 1)
    return ready, len(NINE_HOST_LABELS)


def check_host_guide_events(registry: dict[str, set[str]], guides: Path | None = None) -> list[str]:
    """Fail when a kernel-registered event name is absent from guides/tools/<host>.md."""
    guide_dir = guides if guides is not None else Path(__file__).resolve().parents[1] / "guides" / "tools"
    errors: list[str] = []
    for host, names in sorted(registry.items()):
        path = Path(guide_dir) / f"{host}.md"
        if not path.is_file():
            errors.append(f"{host}: guide missing registered events {', '.join(sorted(names))}")
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except OSError:
            errors.append(f"{host}: guide unreadable")
            continue
        for event in sorted(names):
            if event not in text:
                errors.append(f"{host}: guide omits event {event}")
    return errors


def check_hook_event_registry(registry: dict[str, set[str]], pins: list[dict]) -> list[str]:
    """Fail when a registered name or alias key is absent from that host's pin.

    The message names the host, the event, and the pin URL.
    """
    by_host = _hook_pin_map(pins)
    errors: list[str] = []
    for host, names in sorted(registry.items()):
        pin = by_host.get(host)
        if pin is None:
            errors.append(f"{host}: event registry has no pin")
            continue
        url = str(pin.get("url") or "")
        native = {str(event) for event in pin.get("native_events") or []}
        for event in sorted(names):
            if event not in native:
                errors.append(f"{host}: event {event} is not in pin {url}")
    return errors


def check_hook_event_drift(pins: list[dict], fetch: Fetch) -> list[dict]:
    """Live refresh. A new upstream event is drift: review and is not adopted.

    A failed fetch is error or skip-with-warning, never a pass.
    """
    results: list[dict] = []
    if not pins:
        return [{"pin": "", "status": "error", "classification": "fetch-failed", "detail": "no hook pins", "adopted": False}]
    for pin in pins:
        results.append(_one_hook_pin(pin, fetch))
    return results


def _one_hook_pin(pin: dict, fetch: Fetch) -> dict:
    url = str(pin.get("url") or "")
    host = str(pin.get("host") or url or "hook")
    label = url or host
    native = [str(event) for event in pin.get("native_events") or []]
    if not url or not native:
        return {
            "pin": label,
            "host": host,
            "status": "error",
            "classification": "fetch-failed",
            "detail": f"incomplete hook pin {label}",
            "adopted": False,
        }
    try:
        status, body = fetch(url)
    except Exception as exc:
        return {
            "pin": label,
            "host": host,
            "status": "error",
            "classification": "fetch-failed",
            "detail": f"withheld network for {label}: {exc}",
            "adopted": False,
        }
    if status is None:
        return {
            "pin": label,
            "host": host,
            "status": "error",
            "classification": "fetch-failed",
            "detail": f"withheld network for {label}",
            "adopted": False,
        }
    if int(status) >= 500:
        return {
            "pin": label,
            "host": host,
            "status": "skip-with-warning",
            "classification": "fetch-failed",
            "detail": f"HTTP {status} for {label}; update is unknown, not a pass",
            "adopted": False,
        }
    if int(status) != 200:
        return {
            "pin": label,
            "host": host,
            "status": "error",
            "classification": "fetch-failed",
            "detail": f"HTTP {status} for {label}",
            "adopted": False,
        }
    text = body.decode("utf-8", "replace")
    found = set(_HOOKISH.findall(text))
    extras = sorted(found - set(native))
    if extras:
        return {
            "pin": label,
            "host": host,
            "status": "drift: review",
            "classification": "drift: review",
            "detail": f"new upstream events for {host} not adopted: {', '.join(extras)}",
            "adopted": False,
        }
    excerpt = str(pin.get("recorded_excerpt") or "")
    if excerpt and excerpt not in text:
        return {
            "pin": label,
            "host": host,
            "status": "drift: review",
            "classification": "drift: review",
            "detail": f"excerpt absent for {host}; not adopted",
            "adopted": False,
        }
    missing = [event for event in native if event not in text]
    if missing:
        return {
            "pin": label,
            "host": host,
            "status": "drift: review",
            "classification": "drift: review",
            "detail": f"pinned events absent for {host}: {', '.join(missing)}; not adopted",
            "adopted": False,
        }
    return {
        "pin": label,
        "host": host,
        "status": "pass",
        "classification": "unchanged",
        "detail": f"unchanged {label}",
        "adopted": False,
    }


def _urlopen_fetch(url: str) -> tuple[int, bytes]:
    import urllib.error
    import urllib.request

    try:
        with urllib.request.urlopen(url, timeout=10) as response:  # nosec B310 - pinned docs URL
            status = getattr(response, "status", 200)
            return int(status), response.read()
    except urllib.error.HTTPError as exc:
        payload = exc.read() if exc.fp else b""
        return int(exc.code), payload
    except urllib.error.URLError as exc:
        raise ConnectionError(str(exc.reason)) from exc


_CITED_TOKEN = re.compile(r"`([^`\n]+)`|\[[^\]]+\]\(([^)]+)\)")


def check_stale_generated_paths(tree: Path, relatives: list[str]) -> list[str]:
    """Every concrete path cited by a generated file must exist in the tree.

    Globs and bare tools are not paths. A missing cited file is ``stale-path``.
    """
    root = Path(tree)
    errors: list[str] = []
    for relative in relatives:
        path = root / relative
        if not path.is_file():
            errors.append(f"stale-path: {relative} missing")
            continue
        text = path.read_text(encoding="utf-8")
        for match in _CITED_TOKEN.finditer(text):
            raw = match.group(1) or match.group(2) or ""
            for token in raw.split():
                cleaned = token.strip("`\"'").rstrip(".,)")
                if not cleaned or cleaned.startswith(("http://", "https://", "-", "*")):
                    continue
                if any(ch in cleaned for ch in "*?[]"):
                    continue
                if "/" not in cleaned and not cleaned.endswith((".py", ".md", ".sh", ".java", ".yml")):
                    continue
                if cleaned.startswith("../"):
                    continue
                if not (root / cleaned).exists():
                    errors.append(f"stale-path: {cleaned}")
    return errors


def main(argv: list[str] | None = None) -> int:
    """Opt-in docs drift fetch. Exit 0 only when every pin passes."""
    args = list(sys.argv[1:] if argv is None else argv)
    if "--check-docs-drift" not in args:
        print("usage: python3 conformance.py --check-docs-drift", file=sys.stderr)
        return 2
    fixture = load_fixture()
    results = check_docs_drift(list(fixture.get("pins", [])), _urlopen_fetch)
    results.extend(check_hook_event_drift(list(fixture.get("hook_events", [])), _urlopen_fetch))
    for item in results:
        print(f"{item['status']}: {item['pin']}: {item['detail']}")
    if results and all(item["status"] == "pass" for item in results):
        return 0
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
