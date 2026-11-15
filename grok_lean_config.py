"""Installer-owned lean Grok user config (#5802/#5803/#5805).

Merges ChaosEngine-owned spans into ``~/.grok/config.toml`` (or ``$GROK_HOME``)
without clobbering foreign keys. Uninstall removes only the CE marker span.
"""

from __future__ import annotations

import contextlib
import os
import re
import shutil
import tempfile
from pathlib import Path

try:  # Python 3.11+
    import tomllib as _toml
except ImportError:  # pragma: no cover - older interpreters
    try:
        import tomli as _toml  # type: ignore[no-redef]
    except ImportError:
        _toml = None  # type: ignore[assignment]

LEAN_START = "# CHAOSENGINE-GROK-LEAN:START"
LEAN_END = "# CHAOSENGINE-GROK-LEAN:END"
SKILLS_START = "# CHAOSENGINE-GROK-SKILLS:START"
SKILLS_END = "# CHAOSENGINE-GROK-SKILLS:END"
UI_START = "# CHAOSENGINE-GROK-UI:START"
UI_END = "# CHAOSENGINE-GROK-UI:END"
UI_ASSIGNMENTS = (
    ("show_thinking_blocks", "true"),
    ("group_tool_verbs", "false"),
)

COMPAT_FALSE_KEYS = (
    "hooks",
    "rules",
    "agents",
    "mcps",
    "skills",
    "sessions",
)

# First-pass lean skill disable set (#5805). Office/resume-* deferred.
LEAN_GROK_SKILL_DISABLE = (
    "game-animation-frames",
    "game-asset-core",
    "game-character-consistency",
    "game-tilesets",
    "game-ui-icons",
    "imagine",
)

_TABLE_HEADER = re.compile(r"^\[([^\]]+)\]\s*$")
_ANY_HEADER = re.compile(r"^\[\[[^\]]+\]\]\s*$|^\[[^\]]+\]\s*$")


def grok_home(home: Path | None = None) -> Path:
    """Return Grok home directory (``GROK_HOME`` or ``~/.grok``)."""
    env = os.environ.get("GROK_HOME")
    if env:
        return Path(env).expanduser()
    root = Path.home() if home is None else home
    return root / ".grok"


def grok_user_config_path(home: Path | None = None) -> Path:
    return grok_home(home) / "config.toml"


def grok_detected(*, which=shutil.which) -> bool:
    return which("grok") is not None


def project_has_grok_hooks(project: Path) -> bool:
    path = project / ".grok" / "hooks" / "lifecycle.json"
    return path.is_file()


def should_apply_grok_lean(project: Path, *, which=shutil.which) -> bool:
    """Apply lean compat when Grok CLI exists or project already has `.grok/hooks`."""
    return grok_detected(which=which) or project_has_grok_hooks(project)


def lean_compat_block() -> str:
    lines = [LEAN_START]
    for section in ("compat.claude", "compat.cursor"):
        lines.append(f"[{section}]")
        for key in COMPAT_FALSE_KEYS:
            lines.append(f"{key} = false")
        lines.append("")
    lines.append(LEAN_END)
    return "\n".join(lines).rstrip() + "\n"


def lean_skills_block(disabled: tuple[str, ...] = LEAN_GROK_SKILL_DISABLE) -> str:
    items = ", ".join(f'"{name}"' for name in disabled)
    return (
        f"{SKILLS_START}\n"
        f"[skills]\n"
        f"disabled = [{items}]\n"
        f"{SKILLS_END}\n"
    )


_ARRAY_HEADER = re.compile(r"^\[\[([^\]]+)\]\]\s*$")

# What each marker span owns. Anything else found between the markers (for
# example tables the Grok CLI appended before our END line) belongs to the user
# and survives every strip (#8070).
_SPAN_OWNERSHIP: dict[str, tuple[frozenset[str], frozenset[str]]] = {}


def _register_ownership() -> None:
    _SPAN_OWNERSHIP[LEAN_START] = (
        frozenset({"compat.claude", "compat.cursor"}), frozenset(COMPAT_FALSE_KEYS)
    )
    _SPAN_OWNERSHIP[SKILLS_START] = (frozenset({"skills"}), frozenset({"disabled"}))
    _SPAN_OWNERSHIP[UI_START] = (
        frozenset({"ui"}), frozenset(key for key, _value in UI_ASSIGNMENTS)
    )


def _foreign_lines(interior: list[str], start: str) -> list[str]:
    """Return the lines inside a span that ChaosEngine does not own, in order."""
    tables, keys = _SPAN_OWNERSHIP.get(start, (frozenset(), frozenset()))
    kept: list[str] = []
    current_owned = True  # assignments before any header belong to the host table
    pending_header: str | None = None
    for line in interior:
        stripped = line.strip()
        array = _ARRAY_HEADER.match(stripped)
        table = None if array else _TABLE_HEADER.match(stripped)
        if array is not None:
            current_owned = False
            pending_header = None
            kept.append(line)
            continue
        if table is not None:
            name = table.group(1).strip().strip('"')
            current_owned = name in tables
            pending_header = line if current_owned else None
            if not current_owned:
                kept.append(line)
            continue
        if not stripped or stripped.startswith("#"):
            if not current_owned:
                kept.append(line)
            continue
        key = _assignment_key(line)
        if current_owned and key in keys:
            continue
        if current_owned and pending_header is not None:
            kept.append(pending_header)
            pending_header = None
        kept.append(line)
    while kept and not kept[-1].strip():
        kept.pop()
    return kept


def _strip_marker_span(text: str, start: str, end: str) -> str:
    """Remove ChaosEngine-owned lines between paired markers; keep everything else.

    Only complete START/END pairs are touched. Foreign lines inside a span are
    kept in place, and a blank separator line the merge added before the span
    is dropped so repeated installs do not pile up blank lines.
    """
    if not _SPAN_OWNERSHIP:
        _register_ownership()
    lines = text.splitlines(keepends=True)
    out: list[str] = []
    index = 0
    while index < len(lines):
        if lines[index].strip() != start:
            out.append(lines[index])
            index += 1
            continue
        close = next(
            (j for j in range(index + 1, len(lines)) if lines[j].strip() == end), None
        )
        if close is None:
            out.extend(lines[index:])
            break
        at_eof = close + 1 >= len(lines)
        blank_after = not at_eof and not lines[close + 1].strip()
        if out and not out[-1].strip() and (blank_after or at_eof):
            out.pop()
        foreign = _foreign_lines(lines[index + 1 : close], start)
        if foreign and not foreign[-1].endswith("\n"):
            foreign[-1] += "\n"
        out.extend(foreign)
        index = close + 1
        if not out and blank_after:
            index += 1  # span opened the file: drop the separator after it
    result = "".join(out)
    if not result.strip():
        return ""
    return result


def _strip_toml_tables(text: str, tables: set[str]) -> str:
    """Remove whole ``[name]`` tables (not nested ``[name.x]`` beyond exact name)."""
    lines = text.splitlines(keepends=True)
    kept: list[str] = []
    skipping = False
    for line in lines:
        bare = line.splitlines()[0] if line else ""
        stripped = bare.strip()
        if stripped.startswith("[[") and _ANY_HEADER.match(stripped):
            # An array table ends the skipped table and is never ours (#8070).
            skipping = False
            kept.append(line)
            continue
        match = _TABLE_HEADER.match(stripped)
        if match is not None:
            name = match.group(1).strip().strip('"')
            skipping = name in tables
            if skipping:
                continue
            kept.append(line)
            continue
        if skipping:
            continue
        kept.append(line)
    return "".join(kept)


def _ensure_trailing_newline(text: str) -> str:
    if not text:
        return ""
    return text if text.endswith("\n") else text + "\n"


def merge_lean_compat(text: str) -> str:
    """Idempotently install lean ``[compat.*]`` inside the CE marker span."""
    body = _strip_marker_span(text, LEAN_START, LEAN_END)
    # Drop outside duplicate lean tables so TOML parsers do not see duplicates.
    body = _strip_toml_tables(body, {"compat.claude", "compat.cursor"})
    body = _ensure_trailing_newline(body.rstrip("\n") + "\n" if body.strip() else "")
    if body and not body.endswith("\n\n"):
        body = body.rstrip("\n") + "\n\n"
    return body + lean_compat_block()


def remove_lean_compat(text: str) -> str:
    """Remove only the CE lean-compat marker span."""
    return _strip_marker_span(text, LEAN_START, LEAN_END)


def lean_compat_applied(text: str) -> bool:
    if LEAN_START not in text or LEAN_END not in text:
        return False
    interior = text.split(LEAN_START, 1)[1].split(LEAN_END, 1)[0]
    for section in ("compat.claude", "compat.cursor"):
        if f"[{section}]" not in interior:
            return False
    for key in COMPAT_FALSE_KEYS:
        if f"{key} = false" not in interior and f"{key}=false" not in interior:
            return False
    return True



def grok_ui_block() -> str:
    """Owned ``[ui]`` span. Used only when the user has no ``[ui]`` table."""
    lines = [UI_START, "[ui]"]
    for key, value in UI_ASSIGNMENTS:
        lines.append(f"{key} = {value}")
    lines.append(UI_END)
    return "\n".join(lines) + "\n"


def _assignment_key(line: str) -> str | None:
    bare = line.split("#", 1)[0].strip()
    if not bare or bare.startswith("["):
        return None
    key, _sep, _value = bare.partition("=")
    key = key.strip()
    return key or None


def _ui_table_span(lines: list[str]) -> tuple[int, int] | None:
    """Return ``[start, end)`` covering a top-level ``[ui]`` table, header included."""
    start = None
    for index, line in enumerate(lines):
        stripped = line.strip()
        if _ANY_HEADER.match(stripped) is None:
            continue
        match = _TABLE_HEADER.match(stripped)
        # ``[[array]]`` headers end the [ui] table too (#8070 review).
        name = match.group(1).strip().strip('"') if match and not stripped.startswith("[[") else None
        if start is None:
            if name == "ui":
                start = index
            continue
        return start, index
    if start is None:
        return None
    return start, len(lines)


def _keys_in_ui(lines: list[str], start: int, end: int) -> set[str]:
    found: set[str] = set()
    for line in lines[start + 1 : end]:
        key = _assignment_key(line)
        if key:
            found.add(key)
    return found


def merge_grok_ui(text: str) -> str:
    """Pin thinking visibility without a second ``[ui]`` table or clobbering user keys."""
    body = _strip_marker_span(text, UI_START, UI_END)
    lines = body.splitlines()
    span = _ui_table_span(lines)
    if span is None:
        prefix = _ensure_trailing_newline(body)
        if prefix and not prefix.endswith("\n\n"):
            prefix = prefix.rstrip("\n") + "\n\n"
        return prefix + grok_ui_block()
    start, end = span
    present = _keys_in_ui(lines, start, end)
    missing = [(key, value) for key, value in UI_ASSIGNMENTS if key not in present]
    if not missing:
        return _ensure_trailing_newline(body)
    insertion = [UI_START]
    insertion.extend(f"{key} = {value}" for key, value in missing)
    insertion.append(UI_END)
    updated = lines[:end] + insertion + lines[end:]
    return _ensure_trailing_newline("\n".join(updated))


def remove_grok_ui(text: str) -> str:
    """Remove only the CE Grok UI marker span."""
    return _strip_marker_span(text, UI_START, UI_END)


def grok_ui_applied(text: str) -> bool:
    """True when both pins are set, either by the user or inside the CE span."""
    body = _strip_marker_span(text, UI_START, UI_END)
    lines = body.splitlines()
    span = _ui_table_span(lines)
    outside = _keys_in_ui(lines, *span) if span else set()
    interior = ""
    if UI_START in text and UI_END in text:
        interior = text.split(UI_START, 1)[1].split(UI_END, 1)[0]
    for key, _value in UI_ASSIGNMENTS:
        in_span = f"{key} =" in interior or f"{key}=" in interior
        if key not in outside and not in_span:
            return False
    return True


class GrokConfigWriteRefused(OSError):
    """Raised when a write would corrupt ``config.toml`` or touch a protected home.

    An ``OSError`` subtype so callers that already handle I/O failures (doctor
    heal paths catch ``OSError``) report a refused write instead of crashing.
    """


def _toml_problem(text: str) -> str | None:
    if _toml is None or not text.strip():
        return None
    try:
        _toml.loads(text)
    except Exception as error:  # noqa: BLE001 - any parser error refuses the write
        return str(error)
    return None


def _guard_protected_home(path: Path) -> None:
    """Test isolation tripwire: refuse writes under ``CHAOS_ENGINE_PROTECTED_GROK_HOME``."""
    protected = os.environ.get("CHAOS_ENGINE_PROTECTED_GROK_HOME", "").strip()
    if not protected:
        return
    root_raw = Path(protected).expanduser()
    roots = {Path(os.path.abspath(root_raw)), Path(os.path.realpath(root_raw))}
    targets = {Path(os.path.abspath(path)), Path(os.path.realpath(path))}
    target = Path(os.path.abspath(path))
    hit = next(
        (root for root in roots for item in targets if item == root or root in item.parents),
        None,
    )
    if hit is not None:
        root = hit
        log = os.environ.get("CHAOS_ENGINE_PROTECTED_GROK_HOME_LOG", "").strip()
        if log:
            with contextlib.suppress(OSError), open(log, "a", encoding="utf-8") as handle:
                handle.write(f"{target}\n")
        raise GrokConfigWriteRefused(
            f"refusing to write {target}: it is under the protected Grok home {root} "
            "(tests must sandbox GROK_HOME/HOME, #8070)"
        )


@contextlib.contextmanager
def _config_lock(path: Path):
    """Exclusive advisory lock beside ``path`` so ChaosEngine writers serialize."""
    lock_path = path.with_name(f".{path.name}.chaosengine.lock")
    handle = open(lock_path, "a+b")
    try:
        try:
            import fcntl

            fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        except ImportError:  # pragma: no cover - Windows
            import msvcrt

            handle.seek(0)
            while True:
                try:
                    msvcrt.locking(handle.fileno(), msvcrt.LK_LOCK, 1)
                    break
                except OSError:
                    continue
        yield
    finally:
        handle.close()


def _read_snapshot(path: Path) -> bytes | None:
    try:
        return path.read_bytes()
    except FileNotFoundError:
        return None


def _write_temp(path: Path, data: bytes) -> str:
    """Write ``data`` to a fsynced temp file beside ``path``; return its name."""
    mode = None
    with contextlib.suppress(FileNotFoundError):
        mode = path.stat().st_mode & 0o7777
    fd, tmp_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        # New files get the usual 0o644 rather than mkstemp's 0o600.
        os.chmod(tmp_name, mode if mode is not None else 0o644)
    except BaseException:
        with contextlib.suppress(FileNotFoundError):
            os.unlink(tmp_name)
        raise
    return tmp_name


def _commit_temp(tmp_name: str, path: Path) -> None:
    try:
        os.replace(tmp_name, path)
    except BaseException:
        with contextlib.suppress(FileNotFoundError):
            os.unlink(tmp_name)
        raise
    with contextlib.suppress(OSError, AttributeError):
        dir_fd = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(dir_fd)
        finally:
            os.close(dir_fd)


def update_config_file(
    path: Path,
    transform,
    *,
    dry_run: bool = False,
    attempts: int = 5,
    validate=None,
) -> tuple[str, str]:
    """Read-transform-write ``path`` safely (#8070); return ``(before, after)``.

    Under an exclusive lock: read, transform, refuse if the result does not parse
    as TOML, write to a temp file in the same directory and fsync it, then
    re-read the destination and replace it only if no other writer (for example
    the Grok CLI, which does not take our lock) changed it meanwhile; otherwise
    discard the temp file and retry. Without the other writer's cooperation a
    tiny window between that re-read and the rename remains.

    ``validate(text) -> str | None`` returns a problem description to refuse the
    write; it defaults to the TOML check. Other host configs (JSON) pass their own.
    """
    check = _toml_problem if validate is None else validate
    _guard_protected_home(path)
    # A symlinked config.toml (dotfile managers) is edited at its target so the
    # link survives; os.replace on the link itself would swap it for a file.
    path = Path(os.path.realpath(path))
    if dry_run:
        raw = _read_snapshot(path)
        before = "" if raw is None else raw.decode("utf-8")
        return before, transform(before)
    path.parent.mkdir(parents=True, exist_ok=True)
    with _config_lock(path):
        for _attempt in range(attempts):
            raw = _read_snapshot(path)
            before = "" if raw is None else raw.decode("utf-8")
            after = transform(before)
            if after == before:
                return before, after
            problem = check(after)
            if problem is not None:
                raise GrokConfigWriteRefused(
                    f"refusing to write {path}: result does not parse ({problem}); file left unchanged"
                )
            tmp_name = _write_temp(path, after.encode("utf-8"))
            if _read_snapshot(path) != raw:
                with contextlib.suppress(FileNotFoundError):
                    os.unlink(tmp_name)
                continue
            _commit_temp(tmp_name, path)
            return before, after
    raise GrokConfigWriteRefused(
        f"refusing to write {path}: another writer kept changing it; file left unchanged"
    )


def apply_grok_ui_file(path: Path, *, dry_run: bool = False) -> dict[str, object]:
    result: dict[str, object] = {"path": str(path), "changed": False, "status": "healthy"}
    before, after = update_config_file(path, lambda text: merge_grok_ui(text), dry_run=dry_run)
    if after == before:
        result["detail"] = "grok-ui-already-applied"
        return result
    result["changed"] = True
    result["detail"] = "grok-ui-applied"
    return result


def remove_grok_ui_file(path: Path, *, dry_run: bool = False) -> dict[str, object]:
    result: dict[str, object] = {"path": str(path), "changed": False, "status": "healthy"}
    if not path.is_file():
        result["detail"] = "missing"
        return result
    before, after = update_config_file(path, lambda text: remove_grok_ui(text), dry_run=dry_run)
    if after == before:
        result["detail"] = "grok-ui-absent"
        return result
    result["changed"] = True
    result["detail"] = "grok-ui-removed"
    return result


def merge_lean_skills(
    text: str, disabled: tuple[str, ...] = LEAN_GROK_SKILL_DISABLE
) -> str:
    """Idempotently install ``[skills] disabled = [...]`` inside CE skills span."""
    body = _strip_marker_span(text, SKILLS_START, SKILLS_END)
    body = _ensure_trailing_newline(body.rstrip("\n") + "\n" if body.strip() else "")
    if body and not body.endswith("\n\n"):
        body = body.rstrip("\n") + "\n\n"
    return body + lean_skills_block(disabled)


def remove_lean_skills(text: str) -> str:
    return _strip_marker_span(text, SKILLS_START, SKILLS_END)


def lean_skills_applied(
    text: str, disabled: tuple[str, ...] = LEAN_GROK_SKILL_DISABLE
) -> bool:
    if SKILLS_START not in text or SKILLS_END not in text:
        return False
    interior = text.split(SKILLS_START, 1)[1].split(SKILLS_END, 1)[0]
    if "[skills]" not in interior:
        return False
    return all(name in interior for name in disabled)


def lean_skills_flag_enabled(
    *,
    cli_flag: bool | None = None,
    env: dict[str, str] | None = None,
) -> bool:
    """Return True when ``--lean-grok-skills`` or ``CHAOS_ENGINE_LEAN_GROK_SKILLS=1``."""
    if cli_flag is True:
        return True
    if cli_flag is False:
        return False
    source = os.environ if env is None else env
    return str(source.get("CHAOS_ENGINE_LEAN_GROK_SKILLS", "")).strip() in {
        "1",
        "true",
        "True",
        "yes",
        "YES",
    }


def apply_lean_compat_file(
    path: Path,
    *,
    dry_run: bool = False,
) -> dict[str, object]:
    """Write lean compat into ``path``; create parent dirs as needed."""
    result: dict[str, object] = {
        "path": str(path),
        "changed": False,
        "status": "healthy",
    }
    before, after = update_config_file(path, lambda text: merge_lean_compat(text), dry_run=dry_run)
    if after == before:
        result["detail"] = "lean-compat-already-applied"
        return result
    result["changed"] = True
    result["detail"] = "lean-compat-applied"
    return result


def remove_lean_compat_file(path: Path, *, dry_run: bool = False) -> dict[str, object]:
    result: dict[str, object] = {
        "path": str(path),
        "changed": False,
        "status": "healthy",
    }
    if not path.is_file():
        result["detail"] = "missing"
        return result
    before, after = update_config_file(path, lambda text: remove_lean_compat(text), dry_run=dry_run)
    if after == before:
        result["detail"] = "lean-compat-absent"
        return result
    result["changed"] = True
    result["detail"] = "lean-compat-removed"
    return result


def apply_lean_skills_file(
    path: Path,
    *,
    dry_run: bool = False,
    disabled: tuple[str, ...] = LEAN_GROK_SKILL_DISABLE,
) -> dict[str, object]:
    result: dict[str, object] = {
        "path": str(path),
        "changed": False,
        "status": "healthy",
    }
    before, after = update_config_file(path, lambda text: merge_lean_skills(text, disabled), dry_run=dry_run)
    if after == before:
        result["detail"] = "lean-skills-already-applied"
        return result
    result["changed"] = True
    result["detail"] = "lean-skills-applied"
    return result


def remove_lean_skills_file(path: Path, *, dry_run: bool = False) -> dict[str, object]:
    result: dict[str, object] = {
        "path": str(path),
        "changed": False,
        "status": "healthy",
    }
    if not path.is_file():
        result["detail"] = "missing"
        return result
    before, after = update_config_file(path, lambda text: remove_lean_skills(text), dry_run=dry_run)
    if after == before:
        result["detail"] = "lean-skills-absent"
        return result
    result["changed"] = True
    result["detail"] = "lean-skills-removed"
    return result


def sync_project_grok_lean(
    project: Path,
    *,
    home: Path | None = None,
    which=shutil.which,
    lean_skills: bool = False,
    uninstall: bool = False,
) -> dict[str, object]:
    """Apply or remove lean Grok user config for one project activation."""
    report: dict[str, object] = {
        "status": "skipped",
        "reason": "grok-not-detected",
    }
    if uninstall:
        path = grok_user_config_path(home)
        compat = remove_lean_compat_file(path)
        skills = remove_lean_skills_file(path)
        ui = remove_grok_ui_file(path)
        report = {
            "status": "healthy",
            "compat": compat,
            "skills": skills,
            "ui": ui,
            "path": str(path),
        }
        return report
    if not should_apply_grok_lean(project, which=which):
        return report
    path = grok_user_config_path(home)
    compat = apply_lean_compat_file(path)
    ui = apply_grok_ui_file(path)
    skills_result: dict[str, object] = {"status": "skipped", "detail": "flag-off"}
    if lean_skills:
        skills_result = apply_lean_skills_file(path)
    report = {
        "status": "healthy",
        "compat": compat,
        "skills": skills_result,
        "ui": ui,
        "path": str(path),
    }
    return report


def doctor_lean_compat(
    project: Path,
    *,
    home: Path | None = None,
    which=shutil.which,
    heal: bool = True,
) -> dict[str, object]:
    """Heal lean compat when Grok is in play; else sync-advisory (never recovery-required)."""
    if not should_apply_grok_lean(project, which=which):
        return {"status": "skipped", "detail": "grok-not-in-play"}
    path = grok_user_config_path(home)
    text = path.read_text(encoding="utf-8") if path.is_file() else ""
    ui_text = path.read_text(encoding="utf-8") if path.is_file() else ""
    if not grok_ui_applied(ui_text):
        if heal:
            try:
                apply_grok_ui_file(path)
            except OSError as error:
                return {
                    "status": "sync-advisory",
                    "detail": f"grok-ui-heal-failed: {error}",
                    "path": str(path),
                    "fixNext": f"Ensure write access to {path}, then rerun doctor.",
                }
        else:
            return {
                "status": "sync-advisory",
                "detail": "grok-ui-missing",
                "path": str(path),
                "fixNext": f"Rerun doctor to merge the Grok UI span into {path}.",
            }
    if lean_compat_applied(text):
        return {
            "status": "healthy",
            "detail": "lean-compat-ok",
            "path": str(path),
            "ui": "grok-ui-ok",
        }
    if heal:
        try:
            applied = apply_lean_compat_file(path)
            return {
                "status": "healthy",
                "detail": "lean-compat-healed",
                "path": str(path),
                "changed": applied.get("changed"),
            }
        except OSError as error:
            return {
                "status": "sync-advisory",
                "detail": f"lean-compat-heal-failed: {error}",
                "path": str(path),
                "fixNext": (
                    f"Ensure write access to {path}, then rerun doctor "
                    "or re-run install/activate so ChaosEngine can merge lean "
                    "[compat.claude]/[compat.cursor]."
                ),
            }
    return {
        "status": "sync-advisory",
        "detail": "lean-compat-missing",
        "path": str(path),
        "fixNext": (
            "Rerun install/activate or doctor to merge lean Grok compat "
            f"into {path}."
        ),
    }


def doctor_lean_skills_tip(
    project: Path,
    *,
    home: Path | None = None,
    which=shutil.which,
    env: dict[str, str] | None = None,
) -> dict[str, object]:
    """Sync-advisory tip when Grok is present and lean skills flag unused."""
    if not should_apply_grok_lean(project, which=which):
        return {"status": "skipped", "detail": "grok-not-in-play"}
    if lean_skills_flag_enabled(env=env):
        path = grok_user_config_path(home)
        text = path.read_text(encoding="utf-8") if path.is_file() else ""
        if lean_skills_applied(text):
            return {"status": "healthy", "detail": "lean-skills-ok", "path": str(path)}
        return {
            "status": "sync-advisory",
            "detail": "lean-skills-flag-set-but-not-applied",
            "fixNext": (
                "Rerun install with --lean-grok-skills or set "
                "CHAOS_ENGINE_LEAN_GROK_SKILLS=1 during activate."
            ),
        }
    return {
        "status": "sync-advisory",
        "detail": "lean-skills-recommended",
        "fixNext": (
            "Recommended for ChaosEngine: reinstall/activate with "
            "--lean-grok-skills (or CHAOS_ENGINE_LEAN_GROK_SKILLS=1) to disable "
            "game-* and imagine bundled skills. Undo by removing the "
            f"{SKILLS_START} span from ~/.grok/config.toml."
        ),
    }


def duplicate_chaos_engine_skills_from_inspect(
    payload: object,
) -> list[str]:
    """Best-effort: list duplicate chaos-engine skill paths from ``grok inspect`` JSON."""
    if not isinstance(payload, dict):
        return []
    skills = payload.get("skills")
    paths: list[str] = []
    if isinstance(skills, list):
        for item in skills:
            if not isinstance(item, dict):
                continue
            name = str(item.get("name") or item.get("id") or "").casefold()
            if name not in {"chaos-engine", "chaosengine"}:
                # Also accept path-based detection.
                target = str(item.get("path") or item.get("source") or item.get("target") or "")
                if "chaos-engine" not in target.replace("\\", "/").casefold():
                    continue
            target = str(
                item.get("path")
                or item.get("source")
                or item.get("target")
                or item.get("location")
                or name
            )
            paths.append(target)
    # Alternate shapes: skills.entries / bundledSkills
    if not paths:
        for key in ("bundledSkills", "projectSkills", "skillEntries"):
            entries = payload.get(key)
            if not isinstance(entries, list):
                continue
            for item in entries:
                if not isinstance(item, dict):
                    continue
                blob = str(item).casefold()
                if "chaos-engine" in blob:
                    paths.append(
                        str(
                            item.get("path")
                            or item.get("name")
                            or item.get("id")
                            or "chaos-engine"
                        )
                    )
    # Deduplicate while preserving order; report only when 2+ distinct.
    seen: list[str] = []
    for path in paths:
        normalized = path.replace("\\", "/")
        if normalized not in seen:
            seen.append(normalized)
    return seen if len(seen) >= 2 else []


def expected_chaos_engine_pointer_pair(paths: list[str]) -> bool:
    """True when grok lists only the repo `.agents` + `plugins/` pointer stubs."""
    if len(paths) != 2:
        return False
    norms = [path.replace("\\", "/").casefold() for path in paths]
    has_agents = any(".agents/skills/chaos-engine" in path for path in norms)
    has_plugin = any("plugins/chaos-engine/skills/chaos-engine" in path for path in norms)
    return has_agents and has_plugin


def doctor_grok_skill_dedupe(
    project: Path,
    *,
    executable: str | None = None,
    runner=None,
) -> dict[str, object]:
    """Sync-advisory when grok inspect shows duplicate chaos-engine skills."""
    import json
    import subprocess

    command = executable or shutil.which("grok")
    if not command:
        return {"status": "skipped", "detail": "grok-not-detected"}
    if not project_has_grok_hooks(project) and executable is None:
        # Still probe when CLI exists; cheap advisory.
        pass
    run = subprocess.run if runner is None else runner
    try:
        completed = run(
            [command, "inspect", "--json"],
            cwd=project.resolve(),
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
        payload = json.loads(completed.stdout or "{}") if completed.returncode == 0 else {}
    except (OSError, subprocess.SubprocessError, ValueError):
        return {"status": "skipped", "detail": "grok-inspect-unavailable"}
    dupes = duplicate_chaos_engine_skills_from_inspect(payload)
    if not dupes:
        return {"status": "healthy", "detail": "no-duplicate-chaos-engine-skills"}
    if expected_chaos_engine_pointer_pair(dupes):
        return {
            "status": "healthy",
            "detail": "expected-pointer-adapters",
            "paths": dupes,
        }
    return {
        "status": "sync-advisory",
        "detail": "duplicate-chaos-engine-skills",
        "paths": dupes,
        "fixNext": (
            "Grok listed multiple chaos-engine skills. Prefer AGENTS.md + "
            ".grok/hooks and pointer adapters (.agents/skills + plugins skill "
            "stubs). Ensure lean [compat.claude] skills=false so Claude-compat "
            "does not load a second full body."
        ),
    }
