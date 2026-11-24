#!/usr/bin/env python3
"""Owner-curated L0/L1 wake pack — MemPalace may draft only (#5624)."""

from __future__ import annotations

import argparse
import json
import os
import platform
import re
from collections.abc import Iterable, Mapping
from pathlib import Path

WAKE_RELATIVE = Path(".chaos-engine-state") / "wake-pack.md"
# ~120 tokens ≈ 480 chars soft budget for SessionStart-safe packs.
MAX_CHARS = 480
DRAFT_RELATIVE = Path(".chaos-engine-state") / "wake-pack.mempalace-draft.md"
_GENERIC_SHELLS = frozenset({"bash", "sh", "dash", "ash", "ksh"})
_NAMED_SHELLS = frozenset(
    {"zsh", "fish", "pwsh", "powershell", "cygwin", "msys", "mingw", "nu", "nushell", "tcsh", "csh"}
)
_ENV_MEMORY_HEADER = "Env memory (open first):"


def project_root(start: Path | None = None) -> Path:
    here = (start or Path.cwd()).resolve()
    for candidate in (here, *here.parents):
        if (candidate / ".chaos-engine" / "install.py").is_file() or (
            candidate / "chaos-engine" / "install.py"
        ).is_file():
            return candidate
    return here


def wake_path(project: Path | None = None) -> Path:
    return project_root(project) / WAKE_RELATIVE


def draft_path(project: Path | None = None) -> Path:
    return project_root(project) / DRAFT_RELATIVE


def read_wake_pack(project: Path | None = None) -> str | None:
    path = wake_path(project)
    if not path.is_file():
        return None
    try:
        text = path.read_text(encoding="utf-8").strip()
    except OSError:
        return None
    return text or None


def write_wake_pack(
    text: str,
    *,
    project: Path | None = None,
    force: bool = False,
    source: str = "owner",
) -> dict[str, object]:
    """Write owner wake pack. MemPalace drafts never silently overwrite."""
    path = wake_path(project)
    path.parent.mkdir(parents=True, exist_ok=True)
    cleaned = " ".join(str(text).split())
    if len(cleaned) > MAX_CHARS:
        raise ValueError(f"wake pack exceeds {MAX_CHARS} characters (~120 tokens)")
    if source != "owner" and path.is_file() and not force:
        draft = draft_path(project)
        draft.write_text(cleaned + "\n", encoding="utf-8")
        return {
            "status": "drafted",
            "path": str(draft.relative_to(project_root(project))),
            "chars": len(cleaned),
            "note": "MemPalace draft only; owner must promote (never silent overwrite).",
        }
    path.write_text(cleaned + "\n", encoding="utf-8")
    return {
        "status": "written",
        "path": str(path.relative_to(project_root(project))),
        "chars": len(cleaned),
        "source": source,
    }


def session_start_locator(project: Path | None = None) -> str:
    """Locator only — never inject wake pack prose into SessionStart."""
    if read_wake_pack(project) is None:
        return ""
    return "Wake pack: .chaos-engine-state/wake-pack.md (owner-curated; no prose dump)."


def detect_env_tokens(
    env: Mapping[str, str] | None = None,
    *,
    system_name: str | None = None,
    tools: Iterable[str] | str = (),
) -> list[str]:
    """Extract current OS, non-generic shell, and requested tool keywords (#205).

    Bare generic shell names like ``bash`` or ``sh`` are intentionally omitted so
    standard Linux sessions never match Windows/Git Bash memory entries.
    """
    environ = os.environ if env is None else env
    tokens: list[str] = []

    def add(value: str) -> None:
        cleaned = " ".join(str(value or "").strip().casefold().split())
        if len(cleaned) >= 2 and cleaned not in tokens:
            tokens.append(cleaned)

    raw_os = str(environ.get("OS") or "").strip()
    if system_name is not None:
        os_values = [str(system_name).strip()]
        if env is not None and raw_os:
            os_values.append(raw_os)
    else:
        os_values = [raw_os] if raw_os else [str(platform.system() or "").strip()]

    for os_value in os_values:
        low = os_value.casefold()
        if not low:
            continue
        if low.startswith("win"):
            add("windows")
            if low != "windows":
                add(low)
        elif low.startswith(("mingw", "msys")):
            add("windows")
            add("msys")
            add("git bash")
            if "mingw" in low:
                add("mingw")
            add(low)
        elif low.startswith("cygwin"):
            add("windows")
            add("cygwin")
        elif low.startswith("darwin") or low == "macos":
            add("darwin")
            add("macos")
        else:
            add(low)

    msystem = str(environ.get("MSYSTEM") or "").strip()
    if msystem:
        low_msys = msystem.casefold()
        add(low_msys)
        add("msys")
        add("git bash")
        if "mingw" in low_msys:
            add("mingw")

    if str(environ.get("MINGW_PREFIX") or environ.get("MINGW_CHOST") or "").strip():
        add("mingw")
        add("msys")
        add("git bash")

    raw_shell = str(environ.get("SHELL") or "").strip()
    if raw_shell:
        norm_shell = raw_shell.replace("\\", "/")
        base = Path(norm_shell).name.casefold().removesuffix(".exe")
        if base in _NAMED_SHELLS and base not in _GENERIC_SHELLS:
            add(base)
            if base == "pwsh":
                add("powershell")
        folded_shell = norm_shell.casefold()
        if "git" in folded_shell and "bash" in folded_shell:
            add("git bash")
            add("msys")

    if str(
        environ.get("POWERSHELL_DISTRIBUTION_CHANNEL")
        or environ.get("PSExecutionPolicyPreference")
        or ""
    ).strip():
        add("powershell")
        add("pwsh")

    if str(environ.get("WSL_DISTRO_NAME") or environ.get("WSL_INTEROP") or "").strip():
        add("wsl")

    if str(environ.get("CYGWIN") or "").strip():
        add("cygwin")

    ostype = str(environ.get("OSTYPE") or "").strip().casefold()
    if "msys" in ostype:
        add("msys")
        add("git bash")
    elif "cygwin" in ostype:
        add("cygwin")
    elif ostype.startswith("darwin"):
        add("darwin")
        add("macos")

    raw_tools = [tools] if isinstance(tools, str) else list(tools)
    for item in raw_tools:
        for piece in str(item or "").split(","):
            add(piece)

    return tokens


def find_memory_index_files(
    project: Path,
    *,
    env: Mapping[str, str] | None = None,
) -> list[Path]:
    """Locate MEMORY.md index files from $MEMORY_DIR, project .memory/, and Claude home."""
    environ = os.environ if env is None else env
    root = Path(project).resolve()
    candidates: list[Path] = []

    raw_memory_dir = str(environ.get("MEMORY_DIR") or "").strip()
    if raw_memory_dir:
        mem_path = Path(raw_memory_dir)
        candidates.append(mem_path if mem_path.is_file() else mem_path / "MEMORY.md")

    candidates.append(root / ".memory" / "MEMORY.md")
    candidates.append(root / ".claude" / "memory" / "MEMORY.md")

    raw_home = str(environ.get("HOME") or environ.get("USERPROFILE") or "").strip()
    if not raw_home and env is None:
        # env is the process environment here. A passed mapping that omits
        # HOME and USERPROFILE must not fall through to the real account.
        expanded = os.path.expanduser("~")
        if expanded and not expanded.startswith("~"):
            raw_home = expanded
    if raw_home:
        home = Path(raw_home)
        encoded_variants = dict.fromkeys(
            (
                re.sub(r"[^A-Za-z0-9-]", "-", str(root)),
                str(root).replace("\\", "-").replace("/", "-").replace(":", "-"),
            )
        )
        for encoded in encoded_variants:
            candidates.append(home / ".claude" / "projects" / encoded / "memory" / "MEMORY.md")

    found: list[Path] = []
    seen: set[Path] = set()
    for candidate in candidates:
        try:
            if not candidate.is_file():
                continue
            resolved = candidate.resolve()
        except OSError:
            continue
        if resolved not in seen:
            seen.add(resolved)
            found.append(resolved)
    return found


def _token_pattern(tokens: Iterable[str]) -> re.Pattern[str] | None:
    parts: list[str] = []
    for token in tokens:
        cleaned = " ".join(str(token or "").split())
        if len(cleaned) < 2:
            continue
        parts.append(r"\s+".join(re.escape(piece) for piece in cleaned.split()))
    if not parts:
        return None
    return re.compile(r"(?<![a-z0-9])(?:" + "|".join(parts) + r")(?![a-z0-9])", re.IGNORECASE)


def _is_skippable_index_line(stripped: str) -> bool:
    if not stripped or stripped.startswith("#") or stripped.startswith("<!--"):
        return True
    if len(stripped) >= 3 and set(stripped) <= {"-", "*", "_", " "}:
        return True
    return False


def _truncate_utf8(text: str, limit: int) -> str:
    if limit <= 0:
        return ""
    encoded = text.encode("utf-8")
    if len(encoded) <= limit:
        return text
    if limit <= 3:
        return encoded[:limit].decode("utf-8", errors="ignore")
    clipped = encoded[: limit - 3].decode("utf-8", errors="ignore").rstrip()
    return clipped + "..."


def env_memory_hints(
    project: Path,
    *,
    env: Mapping[str, str] | None = None,
    system_name: str | None = None,
    tools: Iterable[str] | str = (),
    max_lines: int = 8,
    max_bytes: int = 480,
) -> str:
    """Return compact MEMORY.md lines matching current OS/shell/tools, or '' when skipped (#205)."""
    if max_lines <= 0 or max_bytes <= 0:
        return ""
    files = find_memory_index_files(project, env=env)
    if not files:
        return ""
    tokens = detect_env_tokens(env=env, system_name=system_name, tools=tools)
    pattern = _token_pattern(tokens)
    if pattern is None:
        return ""

    matched: list[str] = []
    seen_lines: set[str] = set()
    for index_file in files:
        try:
            content = index_file.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        for raw_line in content.splitlines():
            stripped = raw_line.strip()
            if _is_skippable_index_line(stripped):
                continue
            if stripped in seen_lines:
                continue
            if pattern.search(stripped):
                seen_lines.add(stripped)
                matched.append(stripped)
                if len(matched) >= max_lines:
                    break
        if len(matched) >= max_lines:
            break

    if not matched:
        return ""

    header = _ENV_MEMORY_HEADER
    used = len(header.encode("utf-8"))
    if used + 8 > max_bytes:
        return ""

    lines = [header]
    for entry in matched:
        formatted = entry if entry.startswith(("- ", "* ")) else f"- {entry}"
        needed = 1 + len(formatted.encode("utf-8"))
        if used + needed <= max_bytes:
            lines.append(formatted)
            used += needed
        elif len(lines) == 1:
            remaining = max_bytes - used - 1
            if remaining >= 8:
                lines.append(_truncate_utf8(formatted, remaining))
            break
        else:
            break

    if len(lines) == 1:
        return ""
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    show = sub.add_parser("show")
    show.add_argument("--project", type=Path, default=None)
    write = sub.add_parser("write")
    write.add_argument("--text", required=True)
    write.add_argument("--project", type=Path, default=None)
    write.add_argument("--force", action="store_true")
    write.add_argument("--source", choices=("owner", "mempalace"), default="owner")
    loc = sub.add_parser("locator")
    loc.add_argument("--project", type=Path, default=None)
    args = parser.parse_args(argv)
    if args.command == "show":
        text = read_wake_pack(args.project)
        print(text or "")
        return 0 if text else 1
    if args.command == "write":
        result = write_wake_pack(
            args.text, project=args.project, force=args.force, source=args.source
        )
        print(json.dumps(result, sort_keys=True))
        return 0
    print(session_start_locator(args.project))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
