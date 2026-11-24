"""One canonical sentence for host entry files.

Policy prose stays in hosts.instruction_block(). This module checks that the
generated files still share that sentence. It does not write host files.
"""

from __future__ import annotations

import re
import sys
from collections.abc import Callable, Iterable
from pathlib import Path

_DIR = str(Path(__file__).resolve().parent)
if _DIR not in sys.path:
    sys.path.insert(0, _DIR)

GENERATED_ENTRY_FILES = (
    "AGENTS.md",
    "CLAUDE.md",
    "GEMINI.md",
    ".github/copilot-instructions.md",
    ".codex/config.toml",
    ".codex/hooks.json",
    ".grok/hooks/lifecycle.json",
)
POINTER_FILES = frozenset({"CLAUDE.md", "GEMINI.md"})
POLICY_FILES = frozenset({"AGENTS.md", ".github/copilot-instructions.md"})
MECHANICAL_FILES = frozenset({
    ".codex/config.toml",
    ".codex/hooks.json",
    ".grok/hooks/lifecycle.json",
})
_POLICY_SENTENCE = "Before every task, follow the canonical"
_LIST_LINE = re.compile(r"- `([^`]+)`")


def router_skill_path() -> str:
    """The installed router path named by the canonical sentence."""
    return ".chaos-engine/skills/chaos-engine/SKILL.md"


def entry_writers() -> dict[str, Callable[[], str]]:
    """Generators for the published set. Values call hosts; they do not restate policy."""
    import hosts

    return {
        "AGENTS.md": hosts.instruction_block,
        "CLAUDE.md": lambda: hosts.claude_pointer_bytes().decode("utf-8"),
        "GEMINI.md": lambda: hosts.import_pointer_instruction(None, relative="GEMINI.md").decode("utf-8"),
        ".github/copilot-instructions.md": hosts.copilot_instruction_block,
        ".codex/config.toml": lambda: hosts.codex_content(None, with_mcp=False).decode("utf-8"),
        ".codex/hooks.json": lambda: hosts.lifecycle_hooks_document("codex").decode("utf-8"),
        ".grok/hooks/lifecycle.json": lambda: hosts.lifecycle_hooks_document("grok").decode("utf-8"),
    }


def generated_entry_bodies() -> dict[str, str]:
    """Fresh bodies for every published entry file."""
    writers = entry_writers()
    return {name: writers[name]() for name in GENERATED_ENTRY_FILES if name in writers}


def documented_generated_set(path: Path) -> tuple[str, ...]:
    """Paths listed under the Generated set heading, in order."""
    found: list[str] = []
    in_set = False
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        if line.startswith("## Generated set"):
            in_set = True
            continue
        if in_set and line.startswith("## "):
            break
        if not in_set:
            continue
        match = _LIST_LINE.fullmatch(line.strip())
        if match:
            found.append(match.group(1))
    return tuple(found)


def unlisted_entry_files(paths: Iterable[str]) -> list[str]:
    """Entry paths that are not in the published generated set."""
    known = set(GENERATED_ENTRY_FILES)
    return sorted(path for path in paths if path not in known)


def policy_drift(files: dict[str, str] | None = None) -> list[str]:
    """Differences from the one live policy sentence.

    Import pointers must stay `@AGENTS.md`. Marker files must match
    hosts.normalize_marker_policy(instruction_block()). Mechanical Codex and
    Grok files must not carry a second copy of that sentence.

    With no file map, read the checkout root. AGENTS.md is required. Other
    entry files count only when that path exists on disk.
    """
    import hosts

    supplied = files is not None
    if files is None:
        root = Path(__file__).resolve().parents[1]
        files = {}
        for relative in GENERATED_ENTRY_FILES:
            path = root / relative
            if path.is_file():
                files[relative] = path.read_text(encoding="utf-8")
    expected = hosts.normalize_marker_policy(hosts.instruction_block())
    router = router_skill_path()
    errors: list[str] = []
    required = GENERATED_ENTRY_FILES if supplied else ("AGENTS.md",)
    for relative in required:
        if relative not in files:
            errors.append(f"{relative}: missing from generated set")
    for relative, text in files.items():
        if relative not in GENERATED_ENTRY_FILES:
            errors.append(f"{relative}: not in the generated entry set")
            continue
        if relative in POINTER_FILES:
            first = text.strip().splitlines()[0] if text.strip() else ""
            if first != "@AGENTS.md":
                errors.append(f"{relative}: not a thin @AGENTS.md pointer")
            if _POLICY_SENTENCE in text and hosts.normalize_marker_policy(text) != expected:
                errors.append(f"{relative}: policy sentence drifted")
        elif relative in POLICY_FILES:
            if hosts.normalize_marker_policy(text) != expected:
                errors.append(f"{relative}: policy sentence drifted")
            if router not in text:
                errors.append(f"{relative}: missing router skill path")
        elif relative in MECHANICAL_FILES and _POLICY_SENTENCE in text:
            errors.append(f"{relative}: copied policy sentence")
    return errors
