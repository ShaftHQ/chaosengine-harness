#!/usr/bin/env python3
"""Resolve and install the latest portable ChaosEngine from a GitHub branch."""

from __future__ import annotations

import argparse
from collections import deque
from concurrent.futures import ThreadPoolExecutor, as_completed
from contextlib import contextmanager
import email.utils
import hashlib
import importlib.util
import io
import json
import os
import platform
import socket
import fnmatch
import re
import shlex
import runpy
import shutil
import ssl
import subprocess  # nosec B404 - fixed `gh auth token` argv, never a shell.
import sys
import tarfile
import tempfile
import textwrap
import threading
import time
import traceback
import types
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path, PurePosixPath


def installed_host_probes(project: Path) -> dict[str, dict]:
    """Grok trust and Codex hook state for the install card. Empty when core is absent."""
    path = runtime_module(project / ".chaos-engine", "hosts.py")
    if not path.is_file():
        return {}
    import importlib.util

    spec = importlib.util.spec_from_file_location("ce_install_host_probes", path)
    if spec is None or spec.loader is None:
        return {}
    module = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(module)
    except (OSError, SyntaxError, ImportError):
        return {}
    probes: dict[str, dict] = {}
    try:
        grok = module.grok_runtime_status(project)
    except (OSError, RuntimeError, ValueError, TypeError):
        grok = None
    if isinstance(grok, dict) and grok.get("status") not in {None, "not-detected"}:
        probes["grok"] = grok
    texts: list[str] = []
    candidates = [project / ".codex" / "config.toml"]
    home = os.environ.get("CODEX_HOME")
    candidates.append((Path(home) if home else Path.home() / ".codex") / "config.toml")
    for candidate in candidates:
        if not candidate.is_file():
            continue
        try:
            texts.append(candidate.read_text(encoding="utf-8"))
        except (OSError, UnicodeError):
            continue
    try:
        codex = module.codex_hook_status(project, config_texts=tuple(texts))
    except (OSError, RuntimeError, ValueError, TypeError):
        codex = None
    if isinstance(codex, dict) and codex.get("status") not in {None, "absent"}:
        probes["codex"] = codex
    return probes


def runtime_module(root: Path, name: str) -> Path:
    """Prefer runtime/<name>; fall back to a flat file from an older tree."""
    nested = root / "runtime" / name
    if nested.is_file():
        return nested
    return root / name


def _tree_parts(path: Path) -> tuple[str, ...]:
    """Same comparison install.py uses. Inlined: curl|bash runs this file alone."""
    try:
        resolved = path.resolve()
    except OSError:
        resolved = path.absolute()
    text = os.fspath(resolved)
    if text.startswith("\\\\?\\") or text.startswith("//?/"):
        text = text[4:]
    parts = tuple(part for part in re.split(r"[\\/]", text) if part not in {"", "."})
    if os.name == "nt":
        parts = tuple(part.casefold() for part in parts)
    return parts


def _path_is_inside(child: Path, parent: Path) -> bool:
    left = _tree_parts(child)
    right = _tree_parts(parent)
    return left == right or (len(left) > len(right) and left[: len(right)] == right)


def disjoint_download_parent(project: Path) -> Path:
    """
    Directory for the portable source download, never inside ``project``.

    Windows TEMP lives under the user profile. Installing into that profile, or
    any project that contains TEMP, used to fail with
    "ChaosEngine source and project trees must be disjoint" (#6868).
    """
    project = project.resolve()
    candidates = [Path(tempfile.gettempdir())]
    if project.parent != project:
        candidates.append(project.parent)
    local = os.environ.get("LOCALAPPDATA")
    if local:
        candidates.append(Path(local))
    candidates.append(Path.home() / ".cache")
    for candidate in candidates:
        try:
            candidate.mkdir(parents=True, exist_ok=True)
            resolved = candidate.resolve()
        except OSError:
            continue
        if _path_is_inside(resolved, project):
            continue
        return resolved
    raise ValueError("ChaosEngine source and project trees must be disjoint")


REPOSITORY = re.compile(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+")
GITHUB_URL = re.compile(r"https://github\.com/([A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+?)(?:\.git)?/?")
COMMIT = re.compile(r"[0-9a-f]{40}")
MAX_RESPONSE_BYTES = 10 * 1024 * 1024
MAX_SOURCE_BYTES = 10 * 1024 * 1024
MAX_FILE_BYTES = 2 * 1024 * 1024
# Whole-repo source tarball (compressed). Extract still keeps only chaos-engine/
# and still enforces MAX_SOURCE_BYTES / MAX_FILES on that subset.
MAX_TARBALL_BYTES = 80 * 1024 * 1024
MAX_TARBALL_MEMBERS = 100_000
MAX_FILES = 2000
DOWNLOAD_WORKERS = 8
MAX_READ_ATTEMPTS = 4
MAX_RETRY_AFTER_SECONDS = 60.0
RETRY_BASE_SECONDS = 1.0
TRANSIENT_HTTP_STATUS = frozenset({408, 425, 429, 500, 502, 503, 504})
# Orchestrator 2026-10-31: SSL UNEXPECTED_EOF mid raw.githubusercontent download (~590 files).
TRANSIENT_SSL_MARKERS = (
    "UNEXPECTED_EOF_WHILE_READING",
    "UNEXPECTED_EOF",
    "GNUTLS",
    "TLS CONNECTION WAS NON-PROPERLY TERMINATED",
    "SSLV3_ALERT",
    "BAD_RECORD_MAC",
    "DECRYPTION_FAILED",
    "CONNECTION RESET BY PEER",
)
LOCAL_CLONE_ENV = "CHAOS_ENGINE_LOCAL_CLONE"
CYBERNETIC_RED = "\x1b[38;2;255;59;77m"
ION_BLUE = "\x1b[38;2;47;125;255m"
OPTICAL_WHITE = "\x1b[38;2;242;247;255m"
BRAND_ASCII = (
    "  ,-----.    |       ---+",
    "  |          |          |",
    "  |  *       |       ---+",
    "  |          |          |",
    "  `-----'    |       ---+",
    "         ChaosEngine",
)
BRAND_UNICODE = (
    "  █▀▀▀▀▀▄    │       ───┐",
    "  █          │          │",
    "  █   ◆      │       ───┤",
    "  █          │          │",
    "  █▄▄▄▄▄▀    │       ───┘",
    "          ChaosEngine",
)
BRAND_NARROW = (
    "  C|*|E",
    "  ChaosEngine",
)
TRACE_LIMIT = 12 if (
    os.environ.get("CI")
    or os.environ.get("CHAOS_ENGINE_QUIET") == "1"
) else 40
STALL_SECONDS = 8.0
HEARTBEAT_SECONDS = 15.0
LIVE_TRACE_CONCISE = 4
SPINNER_UNICODE = "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏"
SPINNER_ASCII = "-\\|/"
# (unicode, ascii) pairs. Meaning never rides on color alone: every glyph has a
# distinct ASCII fallback and a word (STATUS_WORDS) next to it where it matters.
STATUS_GLYPHS = {
    "ok": ("✓", "+"),
    "fail": ("✗", "x"),
    "warn": ("!", "!"),
    "info": ("i", "i"),
    "pending": ("·", " "),
    "running": ("◉", "*"),
}
STATUS_WORDS = {
    "ok": "done",
    "fail": "failed",
    "warn": "warning",
    "info": "info",
    "pending": "pending",
    "running": "running",
}
UNHEALTHY_DOCTOR_STATUSES = frozenset(
    {"degraded", "recovery-required", "broken", "failed", "unhealthy"}
)
UNICODE_PROBE = "✓✗◉·…█▀▄┬├┴╱◆⠋"


def status_glyph(kind: str, *, unicode: bool) -> str:
    """Return one status glyph with its ASCII fallback (#6325)."""
    fancy, plain = STATUS_GLYPHS[kind]
    return fancy if unicode else plain


def ascii_forced(environ=None) -> bool:
    """`CHAOS_ENGINE_ASCII=1` forces ASCII glyphs even on a UTF-8 terminal."""
    environ = os.environ if environ is None else environ
    return environ.get("CHAOS_ENGINE_ASCII") == "1"


def verbose_enabled(environ=None) -> bool:
    """`CHAOS_ENGINE_VERBOSE=1` (or `--verbose`) streams every trace line."""
    environ = os.environ if environ is None else environ
    return environ.get("CHAOS_ENGINE_VERBOSE") == "1"


def stream_supports_unicode(stream) -> bool:
    """True when the stream can encode the installer glyph set and ASCII is not forced."""
    if ascii_forced():
        return False
    try:
        UNICODE_PROBE.encode(getattr(stream, "encoding", None) or "utf-8")
    except (LookupError, UnicodeEncodeError):
        return False
    return True


def stream_is_tty(stream) -> bool:
    if os.environ.get("TERM") == "dumb":
        return False
    isatty = getattr(stream, "isatty", None)
    try:
        return bool(isatty()) if callable(isatty) else False
    except (OSError, ValueError):
        return False


def harden_stream_encoding(stream) -> None:
    """Windows legacy consoles (cp1252/cp437) must never crash on a glyph or path."""
    reconfigure = getattr(stream, "reconfigure", None)
    if not callable(reconfigure):
        return
    try:
        UNICODE_PROBE.encode(getattr(stream, "encoding", None) or "utf-8")
        return
    except (LookupError, UnicodeEncodeError):
        pass
    try:
        reconfigure(errors="replace")
    except (AttributeError, OSError, ValueError):
        return
MAX_ISSUE_URL_CHARS = 7800
MAX_ISSUE_BODY_CHARS = 60000
HEAL_HANDOFF_RELATIVE = ".chaos-engine-state/heal-handoff.md"
ISSUE_FORM_FIELD_IDS = (
    "error_code",
    "cause",
    "failed_phase",
    "unhealthy",
    "platform",
    "os_name",
    "os_version",
    "architecture",
    "python_version",
    "machine",
    "doctor_details",
    "hosts_receipt",
    "core_dir",
    "install_py",
    "install_trace",
    "install_trace_snippet",
    "console_log",
    "doctor_json",
    "status_command",
    "doctor_command",
    "additional",
)
REQUIRED_ISSUE_FORM_FIELDS = (
    "error_code",
    "cause",
    "failed_phase",
    "unhealthy",
    "platform",
    "os_name",
    "os_version",
    "architecture",
    "python_version",
    "machine",
    "doctor_details",
    "hosts_receipt",
    "core_dir",
    "install_py",
    "install_trace",
    "status_command",
    "doctor_command",
)
OPTIONAL_ISSUE_FORM_FIELDS = (
    "install_trace_snippet",
    "console_log",
    "doctor_json",
    "additional",
)
ISSUE_FORM_LABELS = {
    "error_code": "Error code",
    "cause": "Cause",
    "failed_phase": "Failed phase",
    "unhealthy": "Unhealthy components",
    "platform": "Platform",
    "os_name": "OS name",
    "os_version": "OS version",
    "architecture": "Architecture",
    "python_version": "Python version",
    "machine": "Machine",
    "doctor_details": "Doctor details",
    "hosts_receipt": "Hosts receipt",
    "core_dir": "Core dir",
    "install_py": "install.py",
    "install_trace": "Install trace (repo-relative)",
    "install_trace_snippet": "Install trace snippet",
    "console_log": "Full console log",
    "doctor_json": "Full doctor JSON",
    "status_command": "Status command",
    "doctor_command": "Doctor command",
    "additional": "Additional context",
}


def install_trace_path(project: Path) -> Path:
    return Path(project) / ".chaos-engine-state/install-trace.json"


def write_install_trace(project: Path, result: dict[str, object], traces: list[tuple[float, str]]) -> Path:
    path = install_trace_path(project)
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        payload = {
            "result": _redact_obj(result, root=project),
            "trace": _redact_obj(traces, root=project),
        }
    except Exception:
        text = "redaction failed; artifact withheld\n"
    else:
        text = json.dumps(payload, sort_keys=True) + "\n"
    path.write_text(text, encoding="utf-8")
    return path


# REQ-ERR-02. Environment facts may enter an issue URL only through this list.
TELEMETRY_ALLOWLIST_KEYS = (
    "os_name",
    "os_version",
    "kernel",
    "architecture",
    "windows_kind",
    "shell",
    "python_version",
    "node_version",
    "uv_version",
    "version",
    "commit",
    "flags",
    "failing_step",
    "exit_code",
    "doctor_code",
    "trace_tail",
)


def telemetry_allowlist(facts: dict[str, str]) -> dict[str, str]:
    """Return only non-sensitive telemetry. Every other key is dropped."""
    kept: dict[str, str] = {}
    for key in TELEMETRY_ALLOWLIST_KEYS:
        value = facts.get(key, "")
        if not isinstance(value, str):
            continue
        value = value.strip()
        if value:
            kept[key] = value
    return kept


def _telemetry_facts() -> dict[str, str]:
    kernel = platform.release()[:40]
    windows_kind = (
        "wsl"
        if os.environ.get("WSL_DISTRO_NAME") or "microsoft" in kernel.casefold()
        else "native"
    )
    shell = os.environ.get("SHELL") or os.environ.get("ComSpec") or ""
    flags = ",".join(
        name
        for name in ("CI", "NO_COLOR", "CHAOS_ENGINE_JSON", "CHAOS_ENGINE_QUIET")
        if os.environ.get(name)
    )
    return {
        "os_name": platform.system()[:40],
        "os_version": platform.release()[:40],
        "kernel": kernel,
        "architecture": platform.machine()[:40] or "unknown",
        "windows_kind": windows_kind,
        "shell": Path(shell).name if shell else "",
        "python_version": sys.version.split()[0][:32],
        "version": product_version(),
        "flags": flags,
    }


def runtime_environment() -> dict[str, str]:
    """Bounded OS/Python facts for installer failure reports (#5703).

    Values come from ``telemetry_allowlist``. ``machine`` is the CPU
    architecture, not ``platform.platform()``, which can embed a hostname.
    """
    facts = telemetry_allowlist(_telemetry_facts())
    architecture = facts.get("architecture") or "unknown"
    return {
        "os_name": facts.get("os_name") or "unknown",
        "os_version": facts.get("os_version") or "unknown",
        "architecture": architecture,
        "python_version": facts.get("python_version") or "unknown",
        "machine": architecture,
    }


def doctor_failure_payload(error: BaseException) -> dict[str, object]:
    """Keep status/code/detail/fix-next only; never persist paths or secrets."""
    doctor = getattr(error, "doctor", None)
    if not isinstance(doctor, dict):
        return {}
    components: dict[str, object] = {}
    raw = doctor.get("components")
    if isinstance(raw, dict):
        for name, item in raw.items():
            if not isinstance(name, str) or not isinstance(item, dict):
                continue
            trimmed = {
                key: item[key]
                for key in ("status", "taskImpact", "detail", "code", "fixNext")
                if isinstance(item.get(key), str)
            }
            if trimmed:
                components[name] = trimmed
    commit = doctor.get("commit")
    return {
        "status": doctor.get("status") if isinstance(doctor.get("status"), str) else "unknown",
        "commit": commit if isinstance(commit, str) else None,
        "components": components,
    }


FAILURE_ARTIFACT_NAMES = (
    "heal-handoff.md",
    "official-self-heal-handoff.md",
    "install-trace.json",
    "install-console.log",
    "doctor-failure.json",
)


def present_state_artifacts(project: Path) -> list[str]:
    """Return repo-relative failure artifacts that currently exist on disk."""
    state = Path(project) / ".chaos-engine-state"
    present: list[str] = []
    for name in FAILURE_ARTIFACT_NAMES:
        path = state / name
        if path.is_file() and not path.is_symlink():
            present.append(f".chaos-engine-state/{name}")
    return present


def _bounded_evidence(text: str, limit: int) -> str:
    """Keep the start and the end. The failure is usually the last lines."""
    if len(text) <= limit:
        return text
    marker = "\n…truncated…\n"
    tail = max(0, limit - 4000 - len(marker))
    return text[:4000] + marker + text[-tail:]


def _exception_chain(error: BaseException) -> str:
    lines: list[str] = []
    current: object = error
    for _ in range(6):
        if not isinstance(current, BaseException):
            break
        lines.append(
            redact_report_text(
                f"{type(current).__name__}: {' '.join(str(current).split())}"
            )
        )
        cause = getattr(current, "__cause__", None)
        reason = getattr(current, "reason", None)
        nxt = cause if isinstance(cause, BaseException) else reason
        if not isinstance(nxt, BaseException) or nxt is current:
            break
        current = nxt
    return "\n".join(lines)


def _ssl_report_facts(error: BaseException) -> str:
    """Non-secret TLS facts when the issuer could not be verified."""
    if "CERTIFICATE_VERIFY_FAILED" not in _exception_chain(error):
        return ""
    paths = ssl.get_default_verify_paths()
    rows = [
        f"openssl: {ssl.OPENSSL_VERSION}",
        f"cafile: {redact_report_text(str(paths.cafile or ''))}",
        f"capath: {redact_report_text(str(paths.capath or ''))}",
        f"openssl_cafile: {redact_report_text(str(paths.openssl_cafile or ''))}",
    ]
    return "\n".join(rows)


def write_failure_artifacts(
    project: Path,
    reporter: InstallReporter | None,
    error: BaseException,
) -> tuple[str, str]:
    """Write console and doctor copies under .chaos-engine-state/.

    The filed issue already contains the redacted text. These files are the
    local copy, not something the operator has to attach.
    """
    state = Path(project) / ".chaos-engine-state"
    state.mkdir(parents=True, exist_ok=True)
    traces: list[str] = []
    if reporter is not None:
        traces = [f"[+{ended:.3f}] {message}" for ended, message in reporter.traces]
    try:
        if traces:
            console_body = "\n".join(redact(line, root=project) for line in traces) + "\n"
        else:
            console_body = "no installer console traces\n"
    except Exception:
        console_body = "redaction failed; artifact withheld\n"
    (state / "install-console.log").write_text(console_body, encoding="utf-8")
    payload = doctor_failure_payload(error)
    if not payload:
        payload = {
            "status": "failed",
            "commit": None,
            "components": {},
            "cause": one_line_cause(error),
        }
    try:
        safe_payload = _redact_obj(payload, root=project)
    except Exception:
        doctor_body = "redaction failed; artifact withheld\n"
    else:
        doctor_body = json.dumps(safe_payload, indent=2, sort_keys=True) + "\n"
    (state / "doctor-failure.json").write_text(doctor_body, encoding="utf-8")
    return (
        ".chaos-engine-state/install-console.log",
        ".chaos-engine-state/doctor-failure.json",
    )


# >>> generated: ce_ui
"""Stdlib installer UI: capabilities, mode, redaction, URL layout, captured commands.

Stage-1 inlines this file into bootstrap.py. Keep it import-safe mid-file.
"""

import importlib.util
import os
import platform
import re
import shutil
import socket
import subprocess
import sys
import textwrap
import urllib.parse
from pathlib import Path


_UNICODE_PROBE = "✓✗◉·…█▀▄┬├┴╱◆⠋"
_HYPERLINK_PROGRAMS = frozenset({"iTerm.app", "vscode", "WezTerm", "ghostty"})
_URL_RE = re.compile(r"https?://\S+")


class Capabilities:
    """What this stream can show. Cursor is not colour."""

    __slots__ = ("tty", "cursor", "color", "unicode", "hyperlinks", "width")

    def __init__(
        self,
        *,
        tty: bool,
        cursor: bool,
        color: str,
        unicode: bool,
        hyperlinks: bool,
        width: int,
    ) -> None:
        self.tty = tty
        self.cursor = cursor
        self.color = color
        self.unicode = unicode
        self.hyperlinks = hyperlinks
        self.width = width


def _environ(environ):
    return os.environ if environ is None else environ


def _stream_is_tty(stream, environ=None) -> bool:
    environ = _environ(environ)
    if environ.get("TERM") == "dumb":
        return False
    isatty = getattr(stream, "isatty", None)
    try:
        return bool(isatty()) if callable(isatty) else False
    except (OSError, ValueError):
        return False


def terminal_color_enabled(*, tty: bool, environ=None) -> bool:
    """Colour follows no-color.org. ``NO_COLOR`` wins. ``FORCE_COLOR`` never implies a TTY."""
    environ = _environ(environ)
    if environ.get("TERM") == "dumb":
        return False
    if environ.get("NO_COLOR"):
        return False
    if environ.get("CHAOS_ENGINE_COLOR") == "never":
        return False
    if environ.get("CHAOS_ENGINE_COLOR") == "always":
        return True
    force = environ.get("FORCE_COLOR")
    if force not in (None, "", "0"):
        return True
    return bool(tty)


def color_level(environ=None, *, enabled: bool) -> str:
    """``none``, ``16``, ``256``, or ``truecolor``."""
    if not enabled:
        return "none"
    environ = _environ(environ)
    if (environ.get("COLORTERM") or "").casefold() in {"truecolor", "24bit"}:
        return "truecolor"
    if "256color" in (environ.get("TERM") or ""):
        return "256"
    return "16"


def cursor_enabled(*, tty: bool, environ=None, vt_ok: bool = True) -> bool:
    """Cursor addressing follows the TTY, not ``NO_COLOR`` or ``FORCE_COLOR``."""
    environ = _environ(environ)
    if not tty or not vt_ok:
        return False
    if environ.get("TERM") == "dumb":
        return False
    return True


def unicode_enabled(stream, environ=None) -> bool:
    environ = _environ(environ)
    if environ.get("CHAOS_ENGINE_ASCII") == "1":
        return False
    encoding = getattr(stream, "encoding", None) or "utf-8"
    try:
        _UNICODE_PROBE.encode(encoding)
    except (LookupError, UnicodeEncodeError):
        return False
    return True


def terminal_width() -> int:
    return max(20, shutil.get_terminal_size(fallback=(80, 24)).columns)


def select_mode(stream=None, *, tty: bool | None = None, environ=None) -> str:
    """``--json`` / ``CHAOS_ENGINE_JSON=1`` beats quiet, tty, and log."""
    environ = _environ(environ)
    if environ.get("CHAOS_ENGINE_JSON") == "1":
        return "json"
    if environ.get("CHAOS_ENGINE_QUIET") == "1":
        return "quiet"
    if tty is None:
        tty = _stream_is_tty(sys.stderr if stream is None else stream, environ)
    ci = bool(environ.get("CI")) or environ.get("GITHUB_ACTIONS") == "true"
    if tty and not ci and environ.get("TERM") != "dumb":
        return "tty"
    return "log"


def enable_windows_vt() -> bool:
    """Enable VT on a Windows console. Failure means plain text and no ESC bytes."""
    if os.name != "nt":
        return True
    try:
        import ctypes

        kernel = ctypes.windll.kernel32
        handle = kernel.GetStdHandle(-12)
        mode = ctypes.c_uint()
        if not kernel.GetConsoleMode(handle, ctypes.byref(mode)):
            return False
        if not kernel.SetConsoleMode(handle, mode.value | 0x0004):
            return False
        return True
    except (AttributeError, OSError, ValueError):
        return False


def _tmux_supports_hyperlinks(environ) -> bool:
    term = environ.get("TERM") or ""
    if not environ.get("TMUX") and not term.startswith("tmux"):
        return False
    try:
        done = subprocess.run(
            ["tmux", "-V"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=2,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return False
    match = re.search(r"(\d+)\.(\d+)", f"{done.stdout or ''}{done.stderr or ''}")
    if match is None:
        return False
    return (int(match.group(1)), int(match.group(2))) >= (3, 4)


def hyperlinks_allowed(environ=None) -> bool:
    """Allowlist, unless ``CHAOS_ENGINE_HYPERLINKS`` is ``0`` or ``1``."""
    environ = _environ(environ)
    override = environ.get("CHAOS_ENGINE_HYPERLINKS")
    if override == "0":
        return False
    if override == "1":
        return True
    if environ.get("WT_SESSION"):
        return True
    if environ.get("TERM_PROGRAM") in _HYPERLINK_PROGRAMS:
        return True
    if environ.get("KITTY_WINDOW_ID"):
        return True
    vte = environ.get("VTE_VERSION") or ""
    if vte.isdigit() and int(vte) >= 5000:
        return True
    return _tmux_supports_hyperlinks(environ)


def detect_capabilities(stream=None, environ=None, *, vt=None) -> Capabilities:
    """Detect once. A failed Windows VT enable stays plain: no cursor, colour, or links."""
    stream = sys.stderr if stream is None else stream
    environ = _environ(environ)
    tty = _stream_is_tty(stream, environ)
    vt_ok = True
    if tty and os.name == "nt":
        checker = vt if vt is not None else enable_windows_vt
        try:
            vt_ok = bool(checker())
        except (AttributeError, OSError, ValueError):
            vt_ok = False
    plain = bool(tty and os.name == "nt" and not vt_ok)
    enabled = False if plain else terminal_color_enabled(tty=tty, environ=environ)
    return Capabilities(
        tty=tty,
        cursor=False if plain else cursor_enabled(tty=tty, environ=environ, vt_ok=vt_ok),
        color="none" if plain else color_level(environ, enabled=enabled),
        unicode=unicode_enabled(stream, environ),
        hyperlinks=False if plain else hyperlinks_allowed(environ),
        width=terminal_width(),
    )


def link_label(url: str) -> str:
    host = urllib.parse.urlparse(url).hostname
    return host or "link"


def osc8(url: str, label: str) -> str:
    """OSC 8 hyperlink. Callers emit this only when hyperlinks are on and mode is tty."""
    shown = label or "link"
    return f"\x1b]8;;{url}\x1b\\{shown}\x1b]8;;\x1b\\"


def layout_lines(text: str, width: int, *, hyperlinks: bool = False) -> list[str]:
    """Wrap ``text``. A URL is never split at ``://``. It is its own line, or an OSC 8 label."""
    width = max(1, int(width))
    raw = strip_controls(text)
    parts = re.split(r"(https?://\S+)", raw)
    lines: list[str] = []
    pending = ""

    def flush() -> None:
        nonlocal pending
        if pending == "":
            return
        wrapped = textwrap.wrap(
            pending,
            width=width,
            break_long_words=True,
            break_on_hyphens=False,
        )
        if not wrapped:
            lines.append(pending[:width])
        else:
            lines.extend(wrapped)
        pending = ""

    for part in parts:
        if not part:
            continue
        if _URL_RE.fullmatch(part):
            flush()
            if hyperlinks:
                lines.append(osc8(part, link_label(part)))
            else:
                lines.append(part)
            continue
        pending += part
    flush()
    return lines or [""]


def line_may_exceed_width(line: str) -> bool:
    """True when the line is only an unbreakable URL or an OSC 8 label that holds one."""
    if "\x1b]8;;" in line:
        return True
    return _URL_RE.fullmatch(line.strip()) is not None


def run_captured(argv, runner=None, *, trace=None, **kwargs):
    """Run ``argv`` with stdout and stderr captured. The child does not inherit this process's stderr.

    The completed process grows a ``trace`` list of ``{argv, returncode, stdout, stderr}``.
    ``argv`` is passed through unchanged so callers can compare the original object.
    """
    run = subprocess.run if runner is None else runner
    options = dict(kwargs)
    options.pop("capture_output", None)
    options["stdout"] = subprocess.PIPE
    options["stderr"] = subprocess.PIPE
    options.setdefault("text", True)
    done = run(argv, **options)
    stdout = getattr(done, "stdout", "") or ""
    stderr = getattr(done, "stderr", "") or ""
    if isinstance(stdout, bytes):
        stdout = stdout.decode("utf-8", "replace")
    if isinstance(stderr, bytes):
        stderr = stderr.decode("utf-8", "replace")
    record = {
        "argv": argv,
        "returncode": getattr(done, "returncode", None),
        "stdout": stdout,
        "stderr": stderr,
    }
    bucket = [] if trace is None else trace
    bucket.append(record)
    try:
        done.trace = bucket
    except (AttributeError, TypeError):
        pass
    return done

_REDACTION_FAILED = "redaction failed; artifact withheld"
_CLIENT_SCRUB_MODULE: object = None
_TOKEN_PATTERNS = (
    ("github-token", re.compile(r"github_pat_[A-Za-z0-9_]{16,}")),
    ("github-token", re.compile(r"gh[pous]_[A-Za-z0-9_]{16,}")),
    ("gitlab-token", re.compile(r"glpat-[A-Za-z0-9_\-]{16,}")),
    ("openai-token", re.compile(r"\bsk-[A-Za-z0-9_\-]{16,}")),
    ("xai-token", re.compile(r"\bxai-[A-Za-z0-9_\-]{16,}")),
    ("google-api-key", re.compile(r"\bAIza[0-9A-Za-z_\-]{20,}")),
    ("aws-access-key", re.compile(r"\bAKIA[A-Z0-9]{16}\b")),
)
# Stop before JSON quotes and brackets so a serialized trace stays valid.
_SECRET_VALUE = r"[^\s\"'`<>\[\]{},;]+"
_BEARER = re.compile(
    rf"(?i)\b((?:authorization\s*[:=]\s*)?bearer)\s+{_SECRET_VALUE}"
)
_USER_PASS = re.compile(r"(?i)\b[A-Za-z0-9._%+\-]{1,64}:[^@\s/:]{1,256}@")
_ENV_ASSIGN = re.compile(
    rf"(?i)\b([A-Za-z_][A-Za-z0-9_]*(?:_TOKEN|_KEY|_SECRET|_PASSWORD))\s*=\s*{_SECRET_VALUE}"
)
_LEGACY_ASSIGN = re.compile(
    rf"(?i)\b(token|secret|password|api_key)\s*=\s*{_SECRET_VALUE}"
)
_ENV_NAME = re.compile(r"(?i).*(_TOKEN|_KEY|_SECRET|_PASSWORD)$")
_HOME_PATTERNS = (
    re.compile(r"(?<![:\w])/mnt/[a-z]/Users/[^/\s]+", re.IGNORECASE),
    re.compile(r"(?<![:\w])[A-Za-z]:[\\/]Users[\\/][^\\/\s]+"),
    re.compile(r"(?<![:\w])/Users/[^/\s]+"),
    re.compile(r"(?<![:\w])/home/[^/\s]+"),
    re.compile(
        r"(?<![:\w])\\\\wsl(?:\$|\.localhost)\\[^\\]+\\(?:home|Users)\\[^\\\s]+",
        re.IGNORECASE,
    ),
)
_OTHER_ABS = re.compile(
    rf"(?<![:\w])(?:[A-Za-z]:[\\/]|\\\\[^\s\"'`<>\[\]{{}},;\\/]+[\\/]|/(?:media|mnt|Volumes|tmp|var|private)/){_SECRET_VALUE}"
)
_CONTROLS = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f-\x9f]")


def strip_controls(text: str) -> str:
    """Drop C0/C1 and ESC from an external value. Keep tab, LF, and CR."""
    return _CONTROLS.sub("", text)


def _scrub_module():
    """Load ``client_name_scrub`` when this tree has it. Stage-1 may not."""
    global _CLIENT_SCRUB_MODULE
    if _CLIENT_SCRUB_MODULE is not None:
        return _CLIENT_SCRUB_MODULE or None
    here = Path(__file__).resolve().parent
    nested = here / "runtime" / "client_name_scrub.py"
    path = nested if nested.is_file() else here / "client_name_scrub.py"
    if not path.is_file():
        _CLIENT_SCRUB_MODULE = False
        return None
    spec = importlib.util.spec_from_file_location("ce_client_name_scrub_redact", path)
    if spec is None or spec.loader is None:
        _CLIENT_SCRUB_MODULE = False
        return None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    _CLIENT_SCRUB_MODULE = module
    return module


def _denylist_tokens(root: Path | None) -> tuple[str, ...]:
    """Same tokens as ``client_name_scrub.load_denylist``."""
    module = _scrub_module()
    if module is not None:
        return tuple(module.load_denylist(root))
    tokens: list[str] = []
    raw = (os.environ.get("CHAOS_ENGINE_CLIENT_NAME_DENYLIST") or "").strip()
    if raw:
        tokens.extend(part.strip() for part in raw.split(","))
    if root is not None:
        path = Path(root) / ".chaos-engine-state" / "client-name-denylist.txt"
        if path.is_file():
            for line in path.read_text(encoding="utf-8").splitlines():
                stripped = line.strip()
                if stripped and not stripped.startswith("#"):
                    tokens.append(stripped)
    cleaned: list[str] = []
    seen: set[str] = set()
    for token in tokens:
        if len(token) < 3:
            continue
        key = token.casefold()
        if key in seen:
            continue
        seen.add(key)
        cleaned.append(token)
    return tuple(cleaned)


def _replace_env_values(text: str) -> str:
    values: list[str] = []
    for name, value in os.environ.items():
        if not isinstance(value, str) or not _ENV_NAME.fullmatch(name):
            continue
        # Every matching value, including short ones. Empty values cannot leak.
        stripped = value.strip()
        if stripped:
            values.append(stripped)
        if value and value != stripped:
            values.append(value)
    for value in sorted(set(values), key=len, reverse=True):
        text = re.sub(
            rf"(?<![A-Za-z0-9]){re.escape(value)}(?![A-Za-z0-9])",
            "<redacted:env>",
            text,
        )
    return text


def _replace_hostname(text: str) -> str:
    names: list[str] = []
    for candidate in (
        socket.gethostname(),
        platform.node(),
        os.environ.get("HOSTNAME", ""),
        os.environ.get("COMPUTERNAME", ""),
    ):
        candidate = (candidate or "").strip().strip(".")
        if len(candidate) < 3:
            continue
        if candidate.casefold() in {"localhost", "localhost.localdomain"}:
            continue
        names.append(candidate)
        short = candidate.split(".")[0]
        if short and short != candidate and len(short) >= 3:
            names.append(short)
    for name in sorted(set(names), key=len, reverse=True):
        text = re.sub(
            rf"(?i)(?<![A-Za-z0-9._-]){re.escape(name)}(?![A-Za-z0-9._-])",
            "<host>",
            text,
        )
    return text


def redact(text: str, root: Path | None = None) -> str:
    """Mask secrets and home paths. Same contract S3 will move to ``ce_ui.redact``.

    Placeholders keep the surrounding structure (``<home>/…``,
    ``<redacted:github-token>``). A raise at a sink writes
    ``redaction failed; artifact withheld`` instead of the original text.
    """
    if not isinstance(text, str):
        text = str(text)
    text = strip_controls(text)
    for label, pattern in _TOKEN_PATTERNS:
        text = pattern.sub(f"<redacted:{label}>", text)
    text = _BEARER.sub(lambda match: f"{match.group(1)} <redacted:bearer>", text)
    text = _USER_PASS.sub("<redacted:user-pass>@", text)
    text = _ENV_ASSIGN.sub(lambda match: f"{match.group(1)}=<redacted:env>", text)
    text = _replace_env_values(text)
    for token in sorted(_denylist_tokens(root), key=len, reverse=True):
        text = re.sub(re.escape(token), "<redacted:client-name>", text, flags=re.IGNORECASE)
    for pattern in _HOME_PATTERNS:
        text = pattern.sub("<home>", text)
    text = _OTHER_ABS.sub("[path]", text)
    text = _replace_hostname(text)
    text = _LEGACY_ASSIGN.sub(lambda match: f"{match.group(1)}=<redacted>", text)
    return text


def redact_report_text(text: str, root: Path | None = None) -> str:
    """Redact paths and secrets in installer reports. ``redact`` is the contract."""
    return redact(text, root=root)


# <<< generated: ce_ui

def github_auth_token() -> str | None:
    for key in ("GH_TOKEN", "GITHUB_TOKEN"):
        value = os.environ.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def resolve_issue_token(explicit: str | None) -> str | None:
    """API filing is opt-in and never uses GitHub Actions GITHUB_TOKEN."""
    if explicit is not None:
        return explicit.strip() or None
    if os.environ.get("GITHUB_ACTIONS") == "true":
        return None
    if os.environ.get("CHAOS_ENGINE_FILE_ISSUE") != "1":
        return None
    return github_auth_token()


def upgrade_query_extras(error: BaseException) -> dict[str, str]:
    extras: dict[str, str] = {}
    commit = getattr(error, "observed_upgrade_commit", None)
    if isinstance(commit, str) and COMMIT.fullmatch(commit):
        extras["observed_commit"] = commit
    components = getattr(error, "observed_upgrade_components", ())
    labels: list[str] = []
    if isinstance(components, tuple):
        for component in components[:32]:
            if not isinstance(component, tuple) or len(component) != 2:
                continue
            name, status = component
            if (
                isinstance(name, str)
                and isinstance(status, str)
                and re.fullmatch(r"[a-z][a-z0-9-]{0,63}", name)
                and re.fullmatch(r"[a-z][a-z0-9-]{0,63}", status)
            ):
                labels.append(f"{name}:{status}")
    if labels:
        extras["candidate_components"] = ",".join(labels)
    details = getattr(error, "observed_upgrade_component_details", ())
    detail_labels: list[str] = []
    if isinstance(details, tuple):
        for component in details[:32]:
            if not isinstance(component, tuple) or len(component) != 2:
                continue
            name, detail = component
            if (
                isinstance(name, str)
                and isinstance(detail, str)
                and re.fullmatch(r"[a-z][a-z0-9-]{0,63}", name)
                and re.fullmatch(r"[a-z][a-z0-9-]{0,63}", detail)
            ):
                detail_labels.append(f"{name}:{detail}")
    if detail_labels:
        extras["candidate_component_details"] = ",".join(detail_labels)
    return extras


def encode_issue_form_url(
    repository: str,
    title: str,
    fields: dict[str, str],
    extra: dict[str, str] | None = None,
    root: Path | None = None,
) -> str:
    """Pack required fields first; optional logs only while under the URL cap."""
    repository = normalize_repository(repository)  # never github.com/https://... (#6234)
    try:
        title = redact(title, root=root)
        fields = {
            key: redact(value, root=root) if isinstance(value, str) else value
            for key, value in fields.items()
        }
        if extra:
            extra = {
                key: redact(value, root=root) if isinstance(value, str) else value
                for key, value in extra.items()
            }
    except Exception:
        return (
            f"https://github.com/{repository}/issues/new?"
            + urllib.parse.urlencode(
                {
                    "template": "chaos-engine-installer.yml",
                    "title": _REDACTION_FAILED,
                }
            )
        )
    packed = {
        key: fields[key]
        for key in REQUIRED_ISSUE_FORM_FIELDS
        if isinstance(fields.get(key), str) and fields[key]
    }
    if extra:
        packed.update({key: value for key, value in extra.items() if value})
    optional = {
        key: fields[key]
        for key in OPTIONAL_ISSUE_FORM_FIELDS
        if isinstance(fields.get(key), str) and fields[key]
    }

    def render(current: dict[str, str]) -> str:
        query = {"template": "chaos-engine-installer.yml", "title": title, **current}
        return f"https://github.com/{repository}/issues/new?{urllib.parse.urlencode(query)}"

    url = render(packed)
    for key, value in optional.items():
        candidate = dict(packed)
        candidate[key] = value
        encoded = render(candidate)
        if len(encoded) <= MAX_ISSUE_URL_CHARS:
            packed = candidate
            url = encoded
            continue
        shrink = value
        while len(shrink) > 64:
            shrink = shrink[: len(shrink) // 2] + "\n…truncated…"
            candidate[key] = shrink
            encoded = render(candidate)
            if len(encoded) <= MAX_ISSUE_URL_CHARS:
                packed = candidate
                url = encoded
                break
    return url


def _render_issue_sections(fields: dict[str, str]) -> str:
    sections: list[str] = []
    for key in ISSUE_FORM_FIELD_IDS:
        value = fields.get(key, "")
        if not isinstance(value, str) or not value.strip():
            continue
        label = ISSUE_FORM_LABELS.get(key, key)
        fence = "json" if key == "doctor_json" else ""
        if key in {"console_log", "doctor_json", "install_trace_snippet"}:
            sections.append(f"### {label}\n\n```{fence}\n{value.rstrip()}\n```\n")
        else:
            sections.append(f"### {label}\n\n{value.strip()}\n")
    return "\n".join(sections).strip() + "\n"


def issue_form_markdown(fields: dict[str, str], root: Path | None = None) -> str:
    """Full redacted evidence. Shrink the trace before the console or doctor."""
    try:
        fields = {
            key: redact(value, root=root) if isinstance(value, str) else value
            for key, value in fields.items()
        }
    except Exception:
        return _REDACTION_FAILED + "\n"
    current = dict(fields)
    body = _render_issue_sections(current)
    snippet = current.get("install_trace_snippet") or ""
    while len(body) > MAX_ISSUE_BODY_CHARS and len(snippet) > 1000:
        snippet = _bounded_evidence(snippet, max(1000, len(snippet) // 2))
        current["install_trace_snippet"] = snippet
        body = _render_issue_sections(current)
    if len(body) > MAX_ISSUE_BODY_CHARS:
        body = body[: MAX_ISSUE_BODY_CHARS - 20] + "\n…truncated…\n"
    return body


def create_installer_github_issue(
    repository: str,
    title: str,
    body: str,
    token: str,
    opener=urllib.request.urlopen,
) -> str | None:
    payload = json.dumps({"title": title, "body": body}).encode("utf-8")
    request_obj = urllib.request.Request(
        f"https://api.github.com/repos/{repository}/issues",
        data=payload,
        method="POST",
        headers={
            "Accept": "application/vnd.github+json",
            "User-Agent": "ChaosEngine-bootstrap",
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        },
    )
    try:
        with opener(request_obj, timeout=30) as response:
            document = response.read(MAX_RESPONSE_BYTES)
    except (OSError, TimeoutError, urllib.error.URLError, urllib.error.HTTPError):
        return None
    try:
        value = json.loads(document.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return None
    html = value.get("html_url") if isinstance(value, dict) else None
    if isinstance(html, str) and html.startswith("https://github.com/"):
        return html
    return None


def core_install_py(project: Path) -> bool:
    return (Path(project) / ".chaos-engine" / "install.py").is_file()


def heal_issue_reference(issue_url: str) -> str:
    """Prefer a short issue locator inside copy-paste agent prompts."""
    if not issue_url or "issues/new?" in issue_url:
        return "the GitHub issue URL printed above"
    return issue_url


def _artifact_read_clause(artifacts: list[str] | None) -> str:
    """Name only the artifacts the caller proved exist (or the legacy trio)."""
    if artifacts is None:
        return (
            ".chaos-engine-state/heal-handoff.md and the local install-trace.json, "
            "install-console.log, and doctor-failure.json"
        )
    if not artifacts:
        return "any local installer artifacts under .chaos-engine-state/"
    if len(artifacts) == 1:
        return artifacts[0]
    if len(artifacts) == 2:
        return f"{artifacts[0]} and {artifacts[1]}"
    return ", ".join(artifacts[:-1]) + f", and {artifacts[-1]}"


ASK_BEFORE_UPSTREAM = (
    "Ask the user before opening or updating an upstream issue or PR, or pushing."
)


def heal_handoff_prompt(
    doctor_command: str,
    issue_url: str,
    *,
    artifacts: list[str] | None = None,
) -> str:
    cli = "py -3" if os.name == "nt" else "python3"
    issue_ref = heal_issue_reference(issue_url)
    read_clause = _artifact_read_clause(artifacts)
    shim = (
        "That source is the publishing repository, not a consumer chaos-engine/ forwarding shim."
    )
    if doctor_command == "not available":
        restore = (
            "Restore the portable core with the documented ChaosEngine install one-liner"
        )
        if artifacts:
            restore += f", then read {read_clause}"
        elif artifacts is None:
            restore += ", then read .chaos-engine-state/heal-handoff.md"
        return (
            "Continue ChaosEngine install in this folder. Load ChaosEngine if present. "
            f"{restore}. "
            "Diagnose and fix the install failure locally (auto-provision missing JDK/mvn/"
            "JAVA_HOME/PATH when possible). "
            "After the core is present, run doctor --json until required components are healthy. "
            f"The report link is {issue_ref}. {shim} {ASK_BEFORE_UPSTREAM}"
        )
    return (
        "Continue ChaosEngine install in this folder. Load ChaosEngine. "
        f"Read {read_clause}. "
        "Do not rerun the install one-liner unless the portable core is missing. "
        "If a fix-next says to rerun that one-liner while .chaos-engine/install.py is present, "
        "do not rerun it. "
        "Diagnose and fix the install failure locally (auto-provision missing JDK/mvn/"
        "JAVA_HOME/PATH only when those tools are actually missing). "
        "Continue unhealthy components with "
        f"{cli} .chaos-engine/install.py repair --project . --component <name> "
        f"and {doctor_command} until doctor --json reports required components healthy. "
        f"The report link is {issue_ref}. {shim} {ASK_BEFORE_UPSTREAM}"
    )


def _is_reparse(path: Path) -> bool:
    """True for a symlink or a Windows reparse point. Does not follow links."""
    try:
        if path.is_symlink():
            return True
        attributes = getattr(os.lstat(path), "st_file_attributes", 0)
    except OSError:
        return False
    return bool(attributes & 0x400)


def _regular_file_bytes(path: Path) -> bytes | None:
    """Return file bytes only when the path itself is a regular file."""
    try:
        if _is_reparse(path) or not path.is_file():
            return None
        return path.read_bytes()
    except OSError:
        return None


def clear_stale_install_failure_artifacts(project: Path) -> None:
    """Drop a previous run's failure handoff after this install is healthy."""
    state = Path(project) / ".chaos-engine-state"
    if _is_reparse(state):
        return
    try:
        if not state.is_dir():
            return
    except OSError:
        return
    for name in (
        "heal-handoff.md",
        "doctor-failure.json",
        "install-console.log",
        "install-rollback.json",
    ):
        path = state / name
        try:
            if _is_reparse(path) or not path.is_file():
                continue
            path.unlink()
        except OSError:
            continue


INSTALL_ROLLBACK_RELATIVE = ".chaos-engine-state/install-rollback.json"


def installed_core_commit(project: Path) -> str | None:
    """Read the installed core commit straight from `.chaos-engine/manifest.json`."""
    raw = _regular_file_bytes(Path(project) / ".chaos-engine" / "manifest.json")
    if raw is None:
        return None
    try:
        manifest = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return None
    source = manifest.get("source") if isinstance(manifest, dict) else None
    commit = source.get("commit") if isinstance(source, dict) else None
    return commit if isinstance(commit, str) and COMMIT.fullmatch(commit) else None


def record_install_rollback(project: Path, requested: str, restored: str) -> None:
    """Persist a verify-failure rollback so status/doctor can name it (#6338)."""
    target = Path(project) / INSTALL_ROLLBACK_RELATIVE
    try:
        if _is_reparse(target.parent) or _is_reparse(target):
            return
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(
            json.dumps(
                {
                    "schemaVersion": 1,
                    "status": "rolled-back",
                    "requestedCommit": requested,
                    "restoredCommit": restored,
                },
                sort_keys=True,
            )
            + "\n",
            encoding="utf-8",
        )
    except OSError:
        # Best-effort evidence; the failure output still names the rollback.
        return


def install_rollback_summary(error: BaseException) -> str | None:
    """One line saying a failed install rolled the core back, and to which commit."""
    restored = getattr(error, "rolled_back_to", None)
    if not isinstance(restored, str) or COMMIT.fullmatch(restored) is None:
        return None
    requested = getattr(error, "rolled_back_from", None)
    requested_text = (
        f"requested core {requested[:12]}"
        if isinstance(requested, str) and COMMIT.fullmatch(requested)
        else "the new core"
    )
    return (
        f"Rolled back: {requested_text} was not kept; the previous core "
        f"{restored[:12]} is installed again, so status/doctor report {restored[:12]}."
    )


def _inexact_prior_rollback(error: BaseException) -> bool:
    """True when rollback cannot restore an exact prior receipt."""
    return isinstance(error, ValueError) and "no exact prior" in str(error)


def write_heal_handoff(project: Path, fields: dict[str, str], issue_url: str) -> Path:
    target = Path(project) / HEAL_HANDOFF_RELATIVE
    target.parent.mkdir(parents=True, exist_ok=True)
    existing = [
        rel
        for rel in present_state_artifacts(project)
        if rel != HEAL_HANDOFF_RELATIVE
    ]
    listed = [HEAL_HANDOFF_RELATIVE, *existing]
    cause = str(fields.get("cause") or "").strip()
    fix_next = str(fields.get("fix_next") or "").strip()
    lines = [
        "# Heal handoff",
        "",
        "The portable core is installed. Continue with one agent step.",
        "",
        f"Issue: {issue_url}",
        "",
        f"Error code: {fields.get('error_code', '')}",
        f"Failed phase: {fields.get('failed_phase', '')}",
        f"Unhealthy: {fields.get('unhealthy', '')}",
        f"Doctor details: {fields.get('doctor_details', '')}",
        f"Doctor: `{fields.get('doctor_command', '')}`",
    ]
    if cause:
        lines.extend(["", f"Cause: {cause}"])
    if fix_next:
        lines.extend(["", f"Fix-next: {fix_next}"])
    lines.extend(
        [
            "",
            "Local artifacts:",
            "",
            *[f"- `{rel}`" for rel in listed],
            "",
            "Do not rerun the install one-liner unless `.chaos-engine/install.py` is missing.",
            "",
            ASK_BEFORE_UPSTREAM,
            "",
        ]
    )
    try:
        text = redact("\n".join(lines), root=project)
    except Exception:
        text = "redaction failed; artifact withheld"
    if not text.endswith("\n"):
        text += "\n"
    target.write_text(text, encoding="utf-8")
    return target


def source_tree_url(repository: str, commit: str, *, root_layout: bool) -> str:
    """Source link printed after layout resolution. Root layout has no ``/chaos-engine`` segment."""
    url = f"https://github.com/{repository}/tree/{commit}"
    if not root_layout:
        url = f"{url}/chaos-engine"
    return url


def product_version() -> str:
    """Version string shipped beside this bootstrap. Empty when VERSION is absent."""
    path = Path(__file__).resolve().parent / "VERSION"
    try:
        return path.read_text(encoding="utf-8").strip()
    except OSError:
        return ""


def brand_lockup() -> str:
    """One lockup line. Armor stays the terminal default; the core is colored separately."""
    version = product_version()
    return f"ChaosEngine  chaosengine-harness {version}".rstrip()


def brand_lines(*, width: int = 80, color: bool = False, unicode: bool = False, lockup: bool = True) -> list[str]:
    if width < 28:
        templates = BRAND_NARROW
        glyph = "*"
    elif unicode and width >= 48:
        templates = BRAND_UNICODE
        glyph = "◆"
    else:
        templates = BRAND_ASCII
        glyph = "*"
    core = f"{CYBERNETIC_RED}{glyph}\x1b[0m" if color else glyph
    painted = []
    for template in templates:
        line = template.replace(glyph, core, 1) if glyph in template else template
        painted.append(line)
    label = brand_lockup()
    if lockup and label and len(label) <= width and (not painted or painted[-1] != label):
        if painted and painted[-1].strip() == "ChaosEngine":
            painted[-1] = label
        else:
            painted.append(label)
    return painted


def _component_blocks_health(value: object) -> bool:
    if not isinstance(value, dict):
        return False
    status = value.get("status")
    if status == "healthy":
        return False
    # Memory default-branch desync is advisory for required mcps during install verify (#5630).
    if status in {"compatible-legacy", "degraded", "sync-advisory"}:
        return False
    if value.get("taskImpact") == "optional" and status == "absent":
        return False
    return value.get("taskImpact") == "required"


def observed_blocking_components(components: object) -> tuple[tuple[str, str], ...]:
    """Keep only bounded, path-free status labels for a failed upgrade report."""
    if not isinstance(components, dict):
        return ()
    result: list[tuple[str, str]] = []
    for name, value in components.items():
        status = value.get("status") if isinstance(value, dict) else None
        if (
            not isinstance(name, str)
            or not isinstance(status, str)
            or re.fullmatch(r"[a-z][a-z0-9-]{0,63}", name) is None
            or re.fullmatch(r"[a-z][a-z0-9-]{0,63}", status) is None
            or not _component_blocks_health(value)
        ):
            continue
        result.append((name, status))
        if len(result) == 32:
            break
    return tuple(sorted(result))


def observed_blocking_component_details(components: object) -> tuple[tuple[str, str], ...]:
    """Keep only fixed outcome codes for required failed upgrade components."""
    if not isinstance(components, dict):
        return ()
    result: list[tuple[str, str]] = []
    for name, value in components.items():
        detail = value.get("detail") if isinstance(value, dict) else None
        if (
            not isinstance(name, str)
            or not isinstance(detail, str)
            or re.fullmatch(r"[a-z][a-z0-9-]{0,63}", name) is None
            or re.fullmatch(r"[a-z][a-z0-9-]{0,63}", detail) is None
            or not _component_blocks_health(value)
        ):
            continue
        result.append((name, detail))
        if len(result) == 32:
            break
    return tuple(sorted(result))


def _required_install_unhealthy(doctor: dict[str, object]) -> bool:
    components = doctor.get("components")
    if isinstance(components, dict) and any(
        _component_blocks_health(value) for value in components.values()
    ):
        return True
    for key in ("kernel", "hosts", "dependencies"):
        item = doctor.get(key)
        if isinstance(item, dict) and item.get("status") not in {None, "healthy", "absent"}:
            return True
    return False


def wants_maven_tools(project: Path, *, skip_tools: bool, requested: bool) -> bool:
    if skip_tools:
        return False
    return requested or (Path(project) / "pom.xml").is_file()


class InstallCancelled(RuntimeError):
    """Raised before an operation when interactive confirmation is declined."""


class InstallHealthError(RuntimeError):
    """Preserve bounded doctor context for recovery output."""

    def __init__(self, phase: str, doctor: dict[str, object]):
        """Capture the failed phase and names of unhealthy components."""
        components = doctor.get("components", {})
        unhealthy = tuple(
            name
            for name, value in components.items()
            if _component_blocks_health(value)
        ) if isinstance(components, dict) else ()
        cli = "py -3" if os.name == "nt" else "python3"
        if unhealthy:
            detail = ", ".join(unhealthy)
            super().__init__(
                f"ChaosEngine doctor did not report a healthy installation "
                f"(unhealthy: {detail}). Run: {cli} .chaos-engine/install.py doctor "
                f"--project . --json"
            )
        else:
            super().__init__(
                "ChaosEngine doctor did not report a healthy installation. "
                f"Run: {cli} .chaos-engine/install.py doctor --project . --json"
            )
        self.phase = phase
        self.unhealthy = unhealthy
        commit = doctor.get("commit")
        self.observed_commit = commit if isinstance(commit, str) and COMMIT.fullmatch(commit) else None
        self.observed_components = observed_blocking_components(components)
        self.observed_component_details = observed_blocking_component_details(components)
        self.doctor = doctor if isinstance(doctor, dict) else {}



def safe_command_trace(command: list[str] | tuple[str, ...]) -> str:
    """Format a command for installer traces without leaking secret-looking values."""
    redacted: list[str] = []
    secret = re.compile(
        r"(?i)(token|secret|password|passwd|api[_-]?key|authorization|bearer)\s*[=:]\s*\S+"
    )
    hexish = re.compile(r"^[0-9a-fA-F]{32,}$")
    for part in command:
        value = str(part)
        if secret.search(value):
            value = secret.sub(
                lambda match: match.group(0).split("=", 1)[0].split(":", 1)[0] + "=***",
                value,
            )
        elif hexish.fullmatch(value):
            value = "***"
        redacted.append(value)
    return " ".join(shlex.quote(item) for item in redacted)


class InstallReporter:
    """Dependency-free installer status renderer; UX always goes to stderr."""

    def __init__(self, *, stream=None, clock=time.monotonic, environ=None):
        """Initialize reporting against the supplied output stream and clock."""
        self.stream = sys.stderr if stream is None else stream
        self._env = os.environ if environ is None else environ
        self.clock = clock
        self.started = clock()
        self.completed_operations: list[str] = []
        self.remaining_operations: tuple[str, ...] = ()
        self.current_operation: str | None = None
        self._in_flight: list[str] = []
        self._elapsed_as_current: dict[str, float] = {}
        self._completed_elapsed: dict[str, float] = {}
        self.history: list[tuple[float, str, str, float]] = []
        self.traces: list[tuple[float, str]] = []
        self.trace_count = 0
        self._current_started: float | None = None
        self.project_root: str | None = None
        self.trace_path: Path | None = None
        self.source_label: str | None = None
        self._download_total: int | None = None
        self._downloaded = 0
        self._download_samples = deque(maxlen=30)
        self.detail: str | None = None
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._lines = 0
        self._caps = detect_capabilities(self.stream, self._env, vt=self._enable_windows_vt)
        self.mode = select_mode(tty=self._caps.tty, environ=self._env)
        self._tty = self.mode == "tty"
        # Auto colour follows tty mode. always and FORCE_COLOR also paint a pipe.
        # A failed Windows VT enable stays in _caps.color. JSON stays plain.
        # Cursor stays on a TTY, including when colour is off.
        self._color = (
            self.mode != "json"
            and self._caps.color != "none"
            and (self._tty or terminal_color_enabled(tty=False, environ=self._env))
        )
        self.cursor = self._tty and self._caps.cursor
        self._unicode = self._caps.unicode
        self._hyperlinks = self._tty and self._caps.hyperlinks
        self._verbose = verbose_enabled(self._env)
        self._frame = 0
        self._last_heartbeat: float | None = None
        self.failed_operation: str | None = None
        self.commit_label: str | None = None
        self.commit_full: str | None = None
        self._commit_logged = False
        if (
            self._env.get("CHAOS_ENGINE_BRAND_SHOWN") != "1"
            and self.mode != "quiet"
        ):
            lines = brand_lines(
                width=self._width(),
                color=self._color,
                unicode=self._tty and self._unicode,
                lockup=self._tty,
            )
            for line in lines:
                self.stream.write(line + "\n")
            self.stream.flush()

    def _stderr_is_tty(self) -> bool:
        if self._env.get("TERM") == "dumb":
            return False
        isatty = getattr(self.stream, "isatty", None)
        if callable(isatty):
            return bool(isatty())
        try:
            return self.stream is sys.stderr and os.isatty(2)
        except (AttributeError, OSError, ValueError):
            return False

    def announce(self, project: Path, repository: str, branch: str) -> None:
        self.project_root = str(Path(project).resolve())
        self.trace_path = install_trace_path(Path(project).resolve())
        self.source_label = f"{repository}@{branch}"
        if self._env.get("CHAOS_ENGINE_QUIET") == "1":
            return
        if self._tty:
            with self._lock:
                self._render_locked()
        else:
            self.stream.write(
                self._truncate(_align_report("Project", self.project_root)) + "\n"
            )
            self.stream.write(
                self._truncate(_align_report("Source", self.source_label)) + "\n"
            )
            self.stream.flush()

    def trace(self, message: str) -> None:
        with self._lock:
            self.traces.append((self.clock() - self.started, message))
            self.trace_count += 1
            if self._env.get("CHAOS_ENGINE_QUIET") == "1":
                return
            if self._tty:
                self._render_locked()
            elif self._verbose:
                self.stream.write(self._truncate(f"  {message}") + "\n")
                self.stream.flush()

    def _enable_windows_vt(self) -> bool:
        return enable_windows_vt()

    def _encodable(self, value: str) -> bool:
        try:
            value.encode(getattr(self.stream, "encoding", None) or "utf-8")
            return True
        except (LookupError, UnicodeEncodeError):
            return False

    def _width(self) -> int:
        return max(20, shutil.get_terminal_size(fallback=(80, 24)).columns)

    def _truncate(self, value: str) -> str:
        width = self._width()
        if len(value) <= width:
            return value
        suffix = "…" if self._unicode else "..."
        return value[: max(0, width - len(suffix))] + suffix

    def _aligned_live_row(self, label: str, value: str) -> str:
        plain = self._truncate(_align_report(label, value))
        prefix = f"  {label:<10} "
        if not plain.startswith(prefix):
            return plain
        return _align_report(label, plain[len(prefix) :], color=self._color)

    def _wrap(self, value: str) -> list[str]:
        return layout_lines(value, self._width(), hyperlinks=self._hyperlinks)

    def _paint(self, value: str, color: str) -> str:
        if not self._color:
            return value
        if color.startswith("\x1b"):
            return f"{color}{value}\x1b[0m"
        return f"\x1b[{color}m{value}\x1b[0m"

    def _duration(self, seconds: float) -> str:
        seconds = max(0, round(seconds))
        minutes, seconds = divmod(seconds, 60)
        return f"{minutes:02d}:{seconds:02d}"

    def _pause_current(self, now: float) -> None:
        if self.current_operation is None or self._current_started is None:
            return
        name = self.current_operation
        self._elapsed_as_current[name] = self._elapsed_as_current.get(name, 0.0) + max(
            0.0, now - self._current_started
        )
        self._current_started = None

    def start(
        self, operation: str, *, remaining: tuple[str, ...] | None = None,
        detail: str | None = None,
    ) -> None:
        with self._lock:
            now = self.clock()
            self._pause_current(now)
            if operation not in {
                "Download source",
                "Provision dependencies",
                "Install Maven Tools",
            }:
                self._download_total = None
                self._downloaded = 0
                self._download_samples.clear()
            if remaining is not None:
                kept = tuple(
                    item
                    for item in self._in_flight
                    if item not in remaining
                    and item != operation
                    and item not in self.completed_operations
                )
                self.remaining_operations = kept + tuple(
                    item for item in remaining if item != operation
                )
            self.current_operation = operation
            if operation not in self._in_flight:
                self._in_flight.append(operation)
            self._current_started = now
            self.detail = detail
            if self._env.get("CHAOS_ENGINE_QUIET") == "1":
                return
            if self._tty:
                self._render_locked()
                if self._thread is None:
                    self._thread = threading.Thread(
                        target=self._ticker, name="chaos-engine-installer", daemon=True
                    )
                    self._thread.start()

    def complete(self, operation: str, *, remaining: tuple[str, ...] = ()) -> None:
        with self._lock:
            now = self.clock()
            if self.current_operation == operation:
                self._pause_current(now)
                self.current_operation = None
            if operation in self._in_flight:
                self._in_flight.remove(operation)
            if operation not in self.completed_operations:
                self.completed_operations.append(operation)
            self._completed_elapsed[operation] = self._elapsed_as_current.get(operation, 0.0)
            duration = self._completed_elapsed[operation]
            self.history.append((now - self.started, "PASS", operation, duration))
            self.traces.append((now - self.started, f"PASS {operation} ({self._duration(duration)})"))
            self.trace_count += 1
            self.remaining_operations = remaining
            self.detail = None
            if self._env.get("CHAOS_ENGINE_QUIET") == "1":
                return
            if self._tty:
                self._render_locked()
            else:
                self.stream.write(f"{self._step_label(operation)}DONE  {operation}\n")
                self.stream.flush()

    @property
    def color_enabled(self) -> bool:
        """Whether this reporter paints ANSI color. Cursor is a separate TTY decision."""
        return self._color

    def enable_verbose(self) -> None:
        """Stream every trace line (`--verbose`)."""
        self._verbose = True

    def fail(self) -> None:
        """Mark the running step failed so the last frame never says `running` (#6325)."""
        with self._lock:
            operation = self.current_operation or (self._in_flight[-1] if self._in_flight else None)
            if operation is None:
                return
            self._pause_current(self.clock())
            self.failed_operation = operation
            self.history.append((self.clock() - self.started, "FAIL", operation, 0.0))
            self.traces.append((self.clock() - self.started, f"FAIL {operation}"))
            self.trace_count += 1
            if self._env.get("CHAOS_ENGINE_QUIET") == "1":
                self.stream.write(f"FAIL  {operation}\n")
                self.stream.flush()
                return
            if self._tty:
                self._render_locked()
            else:
                self.stream.write(f"{self._step_label(operation)}FAIL  {operation}\n")
                self.stream.flush()

    def begin_download(self, total: int | None, *, detail: str | None = None) -> None:
        with self._lock:
            now = self.clock()
            self._download_total = total if isinstance(total, int) and total > 0 else None
            self._downloaded = 0
            self._download_samples.clear()
            self._download_samples.append((now, 0))
            if detail:
                self.detail = detail
            if self._tty:
                self._render_locked()
            elif (
                self._download_total is not None
                and self._env.get("CHAOS_ENGINE_QUIET") != "1"
            ):
                # A pipe has no live frame. One line, not a tick per chunk (#67).
                self.stream.write(
                    self._truncate(f"  ... download {self._download_total} bytes") + "\n"
                )
                self.stream.flush()
            if self._thread is None:
                self._thread = threading.Thread(
                    target=self._ticker, name="chaos-engine-installer", daemon=True
                )
                self._thread.start()

    def downloaded(self, count: int) -> None:
        if count <= 0:
            return
        with self._lock:
            now = self.clock()
            self._downloaded += count
            self._download_samples.append((now, self._downloaded))
            while (
                len(self._download_samples) > 2
                and now - self._download_samples[0][0] > 8.0
            ):
                self._download_samples.popleft()
            if self._tty:
                self._render_locked()

    def _ticker(self) -> None:
        while not self._stop.wait(1.0):
            with self._lock:
                self._frame += 1
                if self._tty:
                    self._render_locked()
                else:
                    self._heartbeat_locked()

    def _heartbeat_locked(self) -> None:
        """Pipes/CI get one plain line per stall window, never ANSI redraw frames."""
        now = self.clock()
        if not self._transfer_stalled(now):
            return
        if self._last_heartbeat is not None and now - self._last_heartbeat < HEARTBEAT_SECONDS:
            return
        self._last_heartbeat = now
        operation = self.current_operation or "install"
        self.stream.write(
            self._truncate(
                f"  ... waiting for data ({operation}, +{self._duration(now - self.started)})"
            )
            + "\n"
        )
        self.stream.flush()

    def _operations(self) -> list[str]:
        return list(
            dict.fromkeys(
                [
                    *self.completed_operations,
                    *self._in_flight,
                    *([self.current_operation] if self.current_operation else []),
                    *self.remaining_operations,
                ]
            )
        )

    def _step_label(self, operation: str) -> str:
        operations = self._operations()
        if operation not in operations:
            return ""
        return f"[{operations.index(operation) + 1}/{len(operations)}] "

    def _transfer_stalled(self, now: float) -> bool:
        return bool(
            self._download_total is not None
            and self._download_samples
            and now - self._download_samples[-1][0] > STALL_SECONDS
        )

    def _download_rate(self) -> float | None:
        if len(self._download_samples) < 2:
            return None
        started, first = self._download_samples[0]
        ended, last = self._download_samples[-1]
        elapsed = ended - started
        transferred = last - first
        if elapsed < 1.0 or transferred <= 0 or self.clock() - ended > STALL_SECONDS:
            return None
        return transferred / elapsed

    @staticmethod
    def _size(value: float) -> str:
        units = ("B/s", "KiB/s", "MiB/s", "GiB/s")
        for unit in units[:-1]:
            if value < 1024:
                return f"{value:.0f} {unit}"
            value /= 1024
        return f"{value:.1f} {units[-1]}"

    def _remember_commit(self, commit: str) -> None:
        self.commit_full = commit
        mark = "…" if self._unicode else "..."
        self.commit_label = commit[:12] + mark

    def note_commit(self, commit: str | None) -> None:
        """Update the header Commit cell in place. Log mode prints that line once."""
        if not isinstance(commit, str) or len(commit) != 40:
            return
        self._remember_commit(commit)
        if self._env.get("CHAOS_ENGINE_QUIET") == "1" or self.mode == "quiet":
            return
        if self._tty:
            with self._lock:
                self._render_locked()
        elif not self._commit_logged:
            self.stream.write(self._truncate(_align_report("Commit", self.commit_label or "")) + "\n")
            self.stream.flush()
            self._commit_logged = True

    def _header_lines(self) -> list[str]:
        lines: list[str] = []
        if self.project_root:
            lines.append(self._aligned_live_row("Project", strip_controls(self.project_root)))
        if self.source_label:
            lines.append(self._aligned_live_row("Source", strip_controls(self.source_label)))
        if self.commit_label:
            lines.append(self._aligned_live_row("Commit", strip_controls(self.commit_label)))
        return lines

    def _checklist_row(self, item: str, *, name_width: int, active: str, check: str, empty: str) -> str:
        if item in self.completed_operations:
            duration = self._duration(self._completed_elapsed.get(item, 0.0))
            return self._paint(self._truncate(f"  [{check}] {item:<{name_width}}  {duration}"), "32")
        if item == self.failed_operation:
            failed = status_glyph("fail", unicode=self._unicode)
            return self._paint(self._truncate(f"  [{failed}] {item:<{name_width}}  failed"), "31")
        if item == self.current_operation or item in self._in_flight:
            return self._paint(self._truncate(f"  [{active}] {item:<{name_width}}  running"), ION_BLUE)
        return self._paint(self._truncate(f"  [{empty}] {item}"), "2")

    def _rail_lines(self, now: float, elapsed: float) -> list[str]:
        """At most two detail lines under the running step. No Trace or Status row."""
        prefix = "└─ " if self._unicode else "+- "
        operations = self._operations()
        done = sum(1 for item in operations if item in self.completed_operations)
        total = len(operations)
        separator = " · " if self._unicode else " | "
        metrics = [f"{done}/{total}", f"Elapsed {self._duration(elapsed)}"]
        if self._transfer_stalled(now):
            metrics.append("waiting for data")
        else:
            rate = self._download_rate()
            if rate is not None:
                metrics.append(self._size(rate))
        rows: list[str] = []
        if self.detail:
            for line in layout_lines(strip_controls(self.detail), self._width(), hyperlinks=self._hyperlinks):
                shown = prefix + line
                rows.append(shown if line_may_exceed_width(line) else self._truncate(shown))
                if len(rows) >= 2:
                    return rows[:2]
        if len(rows) < 2:
            rows.append(self._truncate(prefix + separator.join(metrics)))
        return rows[:2]

    def _render_locked(self) -> None:
        if self._env.get("CHAOS_ENGINE_QUIET") == "1" or self.mode == "quiet":
            return
        operations = self._operations()
        now = self.clock()
        elapsed = max(0.0, now - self.started)
        frames = SPINNER_UNICODE if self._unicode else SPINNER_ASCII
        active = frames[self._frame % len(frames)]
        check = status_glyph("ok", unicode=self._unicode)
        empty = status_glyph("pending", unicode=self._unicode)
        name_width = max((len(item) for item in operations), default=0)
        lines = [""]
        header = self._header_lines()
        if header:
            lines.extend(header)
            lines.append("")
        for item in operations:
            lines.append(
                self._checklist_row(item, name_width=name_width, active=active, check=check, empty=empty)
            )
            if item == self.current_operation:
                lines.extend(self._rail_lines(now, elapsed))
        if self.cursor and self._lines:
            self.stream.write(f"\x1b[{self._lines}F")
        suffix = "\x1b[K" if self.cursor else ""
        rendered = "\n".join(line + suffix for line in lines) + "\n"
        self.stream.write(rendered)
        self.stream.flush()
        self._lines = len(lines)

    def success(
        self,
        project: Path,
        doctor: dict[str, object],
        clients: dict[str, object],
        *,
        repository: str,
        include_heal_handoff: bool = False,
    ) -> None:
        commit = doctor.get("commit") if isinstance(doctor, dict) else None
        if not isinstance(commit, str) or len(commit) != 40:
            commit = None
        doctor_status = doctor.get("status") if isinstance(doctor, dict) else None
        if not isinstance(doctor_status, str) or not doctor_status:
            doctor_status = "unknown"
        if doctor_status == "healthy" and not include_heal_handoff:
            clear_stale_install_failure_artifacts(project)
        components = doctor.get("components") if isinstance(doctor, dict) else None
        healthy, total, attention = doctor_component_counts(components)
        elapsed = self._duration(max(0.0, self.clock() - self.started))
        extra: list[str] = []
        handoff = project / ".chaos-engine-state" / "merge-handoff.md"
        if handoff.is_file() and not handoff.is_symlink():
            doctor_cli = "py -3" if os.name == "nt" else "python3"
            doctor_command = f"{doctor_cli} .chaos-engine/install.py doctor --project ."
            prompt = (
                "Merge ChaosEngine host configuration using "
                ".chaos-engine-state/merge-handoff.md. Follow "
                "chaos-engine/references/installer-program.md deterministic merge. "
                "Preserve every foreign handler and MCP server. Apply only the listed "
                f"owned blocks. Then run {doctor_command} and follow each fix-next."
            )
            extra.extend(
                [
                    "Merge handoff",
                    "Core is installed. Some host files were left unchanged. Details: "
                    + handoff.as_posix(),
                    f"`{prompt}`",
                ]
            )
        overlay_handoff = project / ".chaos-engine-state" / "overlay-handoff.md"
        if overlay_handoff.is_file() and not overlay_handoff.is_symlink():
            doctor_cli = "py -3" if os.name == "nt" else "python3"
            doctor_command = f"{doctor_cli} .chaos-engine/install.py doctor --project ."
            prompt = (
                "Heal ChaosEngine overlay using .chaos-engine-state/overlay-handoff.md. "
                "Copy only the listed owned files from chaos-engine/ to .chaos-engine/ "
                "(byte-identical; create parents as needed). Preserve every foreign "
                "overlay bit. Rewrite .chaos-engine/manifest.json files digests to match "
                f"the overlay. Then run {doctor_command} and follow each fix-next."
            )
            extra.extend(
                [
                    "Overlay handoff",
                    "Core is installed. Owned overlay bytes still diverge from local SOURCE. "
                    "Details: .chaos-engine-state/overlay-handoff.md",
                    "Launch your agent with this prompt:",
                    f"`{prompt}`",
                ]
            )
        heal = project / HEAL_HANDOFF_RELATIVE
        if include_heal_handoff and heal.is_file() and not heal.is_symlink():
            issue_url = "the GitHub issue linked in .chaos-engine-state/heal-handoff.md"
            try:
                for line in heal.read_text(encoding="utf-8").splitlines():
                    if line.startswith("Issue: "):
                        issue_url = line.split("Issue: ", 1)[1].strip()
                        break
            except OSError:
                # Keep the fallback issue locator when the handoff file cannot be read.
                pass
            doctor_cli = "py -3" if os.name == "nt" else "python3"
            doctor_command = f"{doctor_cli} .chaos-engine/install.py doctor --project ."
            prompt = heal_handoff_prompt(
                doctor_command,
                issue_url,
                artifacts=present_state_artifacts(project),
            )
            extra.extend(
                [
                    "Heal handoff",
                    "Core is installed. Continue with one agent step. Details: "
                    + HEAL_HANDOFF_RELATIVE,
                    "Open issue:" if "issues/new?" in issue_url else "GitHub issue:",
                    issue_url,
                    "Launch your agent with this prompt:",
                    f"`{prompt}`",
                ]
            )
        if commit is not None and not self.commit_label:
            self._remember_commit(commit)
        self.close()
        if self._env.get("CHAOS_ENGINE_QUIET") == "1" or self.mode == "quiet":
            return
        report = format_install_report(
            project=project,
            doctor_status=doctor_status,
            healthy=healthy,
            total=total,
            attention=attention,
            commit=commit,
            clients=clients if isinstance(clients, dict) else {},
            repository=repository,
            source_label=self.source_label,
            elapsed=elapsed,
            extra_blocks=extra,
            color=self._color,
            unicode=self._unicode,
            width=self._width(),
            probes=installed_host_probes(project),
            hyperlinks=self._hyperlinks,
        )
        if self._tty:
            block = self._header_lines()
            if block:
                block.append("")
            frames = SPINNER_UNICODE if self._unicode else SPINNER_ASCII
            active = frames[self._frame % len(frames)]
            check = status_glyph("ok", unicode=self._unicode)
            empty = status_glyph("pending", unicode=self._unicode)
            operations = self._operations()
            name_width = max((len(item) for item in operations), default=0)
            block.extend(
                self._checklist_row(item, name_width=name_width, active=active, check=check, empty=empty)
                for item in operations
            )
            if block:
                self.stream.write("\n".join(block) + "\n")
        elif self.commit_label and not self._commit_logged:
            self.stream.write(self._truncate(_align_report("Commit", self.commit_label)) + "\n")
            self._commit_logged = True
        self.stream.write(report)
        self.stream.flush()

    def close(self) -> None:
        self._stop.set()
        thread = self._thread
        if (
            thread is not None
            and thread is not threading.current_thread()
            and thread.ident is not None
        ):
            thread.join(timeout=1.5)
        self._thread = None
        if self.cursor and self._lines:
            count = self._lines
            self.stream.write(f"\x1b[{count}F" + ("\x1b[K\n" * count) + f"\x1b[{count}F")
            self.stream.flush()
        self._lines = 0



def _report_style(value: str, color: str, *, enabled: bool) -> str:
    if not enabled:
        return value
    if color.startswith("\x1b"):
        return f"{color}{value}\x1b[0m"
    return f"\x1b[{color}m{value}\x1b[0m"


def _align_report(label: str, value: str, *, color: bool = False) -> str:
    painted = _report_style(f"{label:<10}", ION_BLUE, enabled=color)
    return f"  {painted} {value}"


def format_first_session_brief(*, clients: dict[str, object] | None = None) -> str:
    """Return the First-session brief heading followed by three numbered next steps."""
    client_names = sorted(clients) if isinstance(clients, dict) else []
    if client_names:
        open_host = (
            "Open one activated host ("
            + ", ".join(client_names)
            + ") in this project."
        )
    else:
        open_host = (
            "Open any supported host in this project "
            "(Codex, Claude Code, Grok, Gemini, or GitHub Copilot)."
        )
    lines = [
        "First-session brief:",
        "  To get started:",
        f"    1. {open_host}",
        "    2. Ask the agent to load / use the `chaos-engine` skill.",
        "    3. Run a small sample task (for example: ask doctor status, or a one-file reversible edit).",
    ]
    return "\n".join(lines) + "\n"


def format_landed_untracked_lines() -> list[str]:
    """Return Landed/Untracked receipt lines (folded under Guide/Trace)."""
    return [
        "  Landed: portable core (`.chaos-engine/`), lifecycle hooks, five host adapters,",
        "    Caveman + Ponytail companions, self-improve skill, Memory / MemPalace / Graphify store tooling.",
        "  Untracked: generated indexes, caches, receipts, and runtimes",
        "    (`.chaos-engine-runtime*`, dependency/host receipts, `graphify-out`, local tool caches).",
        "    Canonical adapters and config stay trackable.",
    ]


def doctor_component_counts(components: object) -> tuple[int, int, tuple[str, ...]]:
    """Count components the way `install.py doctor` does (#6493).

    A component is healthy when doctor counts it healthy: status ``healthy`` or
    ``compatible-legacy``, or ``absent`` for an optional component. Degraded and
    advisory rows are named instead of being counted as healthy.
    """
    healthy = 0
    total = 0
    attention: list[str] = []
    if isinstance(components, dict):
        for name in sorted(str(item) for item in components):
            item = components[name]
            if not isinstance(item, dict):
                continue
            total += 1
            status = str(item.get("status") or "unknown")
            impact = str(item.get("taskImpact") or "required")
            if status in {"healthy", "compatible-legacy"} or (
                status == "absent" and impact == "optional"
            ):
                healthy += 1
            else:
                attention.append(f"{name} {status}")
    return healthy, total, tuple(attention)


def final_install_doctor(target: Path, project: Path, fallback: dict[str, object]) -> dict[str, object]:
    """Run `install.py doctor`'s exact checks from the installed core (#6493).

    The downloaded installer's folder is already deleted at this point, so its
    sibling probes (companions, identity, overlay, shared-store freshness) would
    be skipped silently and the summary would count fewer, healthier components.
    """
    run = installed_core_doctor(target)
    if run is None:
        return fallback
    try:
        document = run(project, probe_retrieve=True)
    except (OSError, RuntimeError, ValueError, TypeError, ImportError):
        return fallback
    return document if isinstance(document, dict) else fallback


def installed_core_doctor(target: Path):
    """Return the installed core's ``doctor_with_dependencies``, or None (#6499).

    The downloaded installer's folder is gone after install, so only the installed
    core still sees every sibling probe that ``install.py doctor`` runs.
    """
    core = Path(target) / "install.py"
    if not core.is_file():
        return None
    try:
        run = runpy.run_path(str(core)).get("doctor_with_dependencies")
    except (OSError, RuntimeError, ValueError, TypeError, ImportError, SyntaxError):
        return None
    return run if callable(run) else None


def verify_gate_doctor(installer, target: Path, project: Path) -> dict[str, object]:
    """Verify gate from the installed core so it checks what ``install.py doctor`` does (#6499)."""
    run = installed_core_doctor(target) or installer.doctor_with_dependencies
    return run(project, verify_clients=False)


def _doctor_glyph_kind(doctor_status: str) -> str:
    if doctor_status == "healthy":
        return "ok"
    if doctor_status in UNHEALTHY_DOCTOR_STATUSES:
        return "warn"
    return "info"


def format_install_report(
    *,
    project: Path,
    doctor_status: str,
    healthy: int,
    total: int,
    commit: str | None,
    clients: dict[str, object],
    attention: tuple[str, ...] = (),
    repository: str,
    source_label: str | None,
    elapsed: str,
    extra_blocks: list[str] | None = None,
    color: bool = False,
    unicode: bool = False,
    width: int = 80,
    probes: dict[str, dict] | None = None,
    hyperlinks: bool = False,
) -> str:
    """Render the finish receipt. Project, Source, and Commit stay in the header, not here."""
    unhealthy = doctor_status in UNHEALTHY_DOCTOR_STATUSES
    tone = "33" if unhealthy else "32"
    title = "Installed with warnings" if unhealthy else "Installation Successful!"
    glyph = status_glyph("warn" if unhealthy else "ok", unicode=unicode)
    headline = (
        f"{_report_style(glyph, tone, enabled=color)} "
        f"{_report_style(title, tone, enabled=color)}"
    )
    lines = ["", f"  {headline}  ({elapsed})"]
    if width >= 48:
        rule = "──" if unicode else "--"
        lines.append("  " + _report_style(rule * 18, ION_BLUE, enabled=color))
    lines.append("")
    doctor_glyph = status_glyph(_doctor_glyph_kind(doctor_status), unicode=unicode)
    doctor_value = f"{doctor_glyph} {doctor_status}"
    if total:
        doctor_value += f"  {healthy}/{total} components"
    if attention:
        doctor_value += f" (needs attention: {', '.join(attention)})"
    lines.append(_align_report("Doctor", doctor_value, color=color))
    client_names = sorted(clients) if isinstance(clients, dict) else []
    lines.append(
        _align_report("Hosts", ", ".join(client_names) or "none activated yet", color=color)
    )
    lines.append("")
    started = format_first_session_brief(clients=clients).rstrip("\n")
    if color:
        started = started.replace(
            "To get started:",
            _report_style("To get started:", ION_BLUE, enabled=True),
            1,
        )
    lines.append(started)
    if extra_blocks:
        lines.append("")
        for block in extra_blocks:
            if block in {"Merge handoff", "Heal handoff"}:
                paint = "31" if block == "Heal handoff" else ION_BLUE
                lines.append("  " + _report_style(block, paint, enabled=color))
            else:
                lines.append(block)
    lines.append("")
    lines.append(
        format_host_onboarding_cards(
            detected=detect_install_hosts(),
            activated=clients,
            color=color,
            probes=probes,
        ).rstrip("\n")
    )
    lines.append("")
    guide = installer_user_guide_url(repository)
    if hyperlinks:
        lines.append(_align_report("Guide", osc8(guide, link_label(guide)), color=color))
    else:
        plain = _align_report("Guide", guide, color=False)
        if len(plain) <= width:
            lines.append(_align_report("Guide", guide, color=color))
        else:
            lines.append(_align_report("Guide", "", color=color).rstrip())
            lines.extend(layout_lines(guide, width, hyperlinks=False))
    trace = install_trace_path(Path(project)).as_posix()
    # Stable machine-readable receipt lines (agents and tests parse these).
    receipt = []
    if commit is not None:
        receipt.append(f"Resolved commit: {commit}")
    if total:
        receipt.append(f"Doctor: {doctor_status} ({healthy}/{total} components healthy)")
    else:
        receipt.append(f"Doctor: {doctor_status}")
    if client_names:
        receipt.append(f"Clients: {', '.join(client_names)}")
    receipt.append(f"Full install trace: {trace}")
    lines.append(_align_report("Receipt", _report_style(receipt[0], "2", enabled=color), color=color))
    lines.extend(
        "             " + _report_style(item, "2", enabled=color) for item in receipt[1:]
    )
    lines.extend(format_landed_untracked_lines())
    lines.append("")
    return "\n".join(lines) + "\n"


def confirm_operation(operation: str, *, input_stream, output) -> None:
    """Confirm one step. ``CI=1`` or ``--yes`` answers without reading stdin."""
    if os.environ.get("CI") == "1" or os.environ.get("CHAOS_ENGINE_NO_INPUT") == "1":
        return
    output.write(f"Confirm {operation}? [y/N] ")
    output.flush()
    if input_stream.readline().strip().casefold() not in {"y", "yes"}:
        raise InstallCancelled(f"ChaosEngine installation cancelled before {operation}")


HOST_DETECT_COMMANDS = (
    ("claude", "claude", "Claude Code"),
    ("codex", "codex", "Codex"),
    ("grok", "grok", "Grok"),
    ("gemini", "gemini", "Gemini"),
    ("copilot", "gh", "GitHub Copilot"),
)

HOST_NEXT_ACTIONS = {
    "claude": "Open Claude Code in this project and ask it to use the chaos-engine skill.",
    "codex": "Start a Codex session in this project and ask it to use chaos-engine.",
    "grok": "Open Grok in this project and ask it to follow AGENTS.md / chaos-engine.",
    "gemini": "Open Gemini CLI in this project and ask it to use the chaos-engine skill.",
    "copilot": "Open this repo in an IDE with GitHub Copilot and ask Copilot to use chaos-engine.",
}


HOST_ONBOARDING_CARDS = {
    "claude": {
        "label": "Claude Code",
        "path": "marketplace/plugin",
        "how": (
            "Install registers a path-unique local marketplace and installs the "
            "`chaos-engine` (+ companions) plugins at project scope. Restart Claude "
            "Code, then ask it to use the chaos-engine skill."
        ),
        "gap": "Requires the `claude` CLI on PATH for automatic marketplace activation.",
    },
    "codex": {
        "label": "Codex",
        "path": "marketplace/plugin",
        "how": (
            "Install registers a path-unique local marketplace and installs the "
            "`chaos-engine` (+ companions) plugins. Restart Codex so it reloads the "
            "plugin cache, then ask it to use chaos-engine."
        ),
        "gap": "Requires the `codex` CLI on PATH for automatic marketplace activation.",
    },
    "grok": {
        "label": "Grok",
        "path": "file/hook injection",
        "how": (
            "Install writes AGENTS.md guidance and project hooks under `.grok/`. "
            "Open Grok in this project, run `grok inspect --json`, and if "
            "`projectTrusted` is false run `/hooks-trust`, then reload hooks."
        ),
        "gap": (
            "Hook trust is host-gated; doctor stays healthy and reports sync-advisory "
            "until the operator runs `/hooks-trust` when using Grok."
        ),
    },
    "gemini": {
        "label": "Gemini",
        "path": "file/hook injection",
        "how": (
            "Install writes GEMINI.md / `.gemini/settings.json` and the Node "
            "`hooks/launch.js` launcher. Open Gemini CLI in this project and ask it "
            "to use the chaos-engine skill."
        ),
        "gap": (
            "Needs Node.js for the Gemini hook launcher; unsupported native events "
            "stay explicit capability gaps."
        ),
    },
    "copilot": {
        "label": "GitHub Copilot",
        "path": "file/hook injection",
        "how": (
            "Install writes `.github/copilot-instructions.md` and "
            "`.github/hooks/chaos-engine.json`. Open this repo in an IDE with "
            "GitHub Copilot (or Copilot cloud agent) and ask Copilot to use chaos-engine."
        ),
        "gap": (
            "Copilot is IDE/cloud hosted; CLI detection is soft (`gh` / `code` / `cursor`)."
        ),
    },
}


def format_host_onboarding_cards(
    *,
    detected: list[tuple[str, str, bool]] | None = None,
    activated: dict[str, object] | None = None,
    color: bool = False,
    targets: tuple[str, ...] | None = None,
    probes: dict[str, dict] | None = None,
) -> str:
    """Render a rustup-style host table; how/gap only for one actionable host."""
    detected_map = {
        host_id: found for host_id, _label, found in (detected or [])
    }
    activated_names = {
        str(name).casefold() for name in (activated or {})
    }
    probe_map = probes or {}

    def _probe(host_id: str) -> dict | None:
        row = probe_map.get(host_id)
        return row if isinstance(row, dict) else None

    def _is_activated(host_id: str) -> bool:
        return host_id in activated_names or any(
            name == host_id or name.startswith(f"{host_id}-")
            for name in activated_names
        )

    def _row_ready(host_id: str) -> bool:
        """Marketplace activation, or a trusted Grok hook load. A Codex file is not ready."""
        probe = _probe(host_id)
        if host_id == "grok" and isinstance(probe, dict) and probe.get("status") == "healthy":
            return True
        if host_id == "codex" and isinstance(probe, dict) and probe.get("status") in {
            "configured", "disabled", "unsupported",
        }:
            return False
        return _is_activated(host_id)

    actionable: str | None = None
    for host_id, _command, _label in HOST_DETECT_COMMANDS:
        if detected_map.get(host_id) and not _row_ready(host_id):
            actionable = host_id
            break
    if actionable is None:
        for host_id, _command, _label in HOST_DETECT_COMMANDS:
            if not detected_map.get(host_id) and not _row_ready(host_id):
                actionable = host_id
                break
    heading = _report_style("Hosts", ION_BLUE, enabled=color)
    lines = ["Host onboarding cards:", f"  {heading}"]
    for host_id, _command, _label in HOST_DETECT_COMMANDS:
        card = HOST_ONBOARDING_CARDS[host_id]
        found = bool(detected_map.get(host_id))
        probe = _probe(host_id)
        if host_id == "codex" and isinstance(probe, dict) and probe.get("status") in {
            "configured", "disabled", "unsupported",
        }:
            status = str(probe["status"])
        elif _row_ready(host_id):
            status = "activated"
        elif host_id == "copilot" and found:
            status = "IDE signal"
        elif found:
            status = "detected"
        else:
            status = "not on PATH"
        status_cell = f"{status:<14}"
        if color and status == "activated":
            status_cell = _report_style(status_cell, "32", enabled=True)
        elif color:
            status_cell = _report_style(status_cell, "2", enabled=True)
        path = card["path"].replace("file/hook injection", "file/hook")
        lines.append(f"    {card['label']:<16} {status_cell} {path}")
        if host_id == actionable:
            lines.append(f"      how: {card['how']}")
            gap = card["gap"]
            if (
                isinstance(probe, dict)
                and probe.get("detail")
                and probe.get("status") not in {None, "healthy", "absent"}
            ):
                gap = str(probe["detail"])
            lines.append(f"      gap: {gap}")
        elif (
            host_id == "codex"
            and isinstance(probe, dict)
            and probe.get("detail")
            and probe.get("status") not in {None, "healthy", "absent"}
        ):
            lines.append(f"      hook: {probe['detail']}")
    if targets and "grok-bot" in targets:
        lines.extend(_grok_bot_onboarding_lines())
    return "\n".join(lines) + "\n"


def _grok_bot_onboarding_lines() -> list[str]:
    """Point the Grok Bot card at hosts.INSTRUCTION_ONLY_HOSTS, not a receipt shim."""
    import importlib.util

    path = runtime_module(Path(__file__).resolve().parent, "hosts.py")
    spec = importlib.util.spec_from_file_location("ce_bootstrap_hosts_card", path)
    if spec is None or spec.loader is None:
        raise RuntimeError("hosts.py is required for the Grok Bot card")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    entry = module.INSTRUCTION_ONLY_HOSTS["grok-bot"]
    instructions = str(entry["instructions"])
    gap = str(entry["gap"])
    return [
        f"    {'Grok Bot':<16} {'instruction-only':<14} {instructions}",
        f"      how: Read {instructions} at task start. No receipt shim is installed.",
        f"      gap: {gap}",
    ]



# Install-time client ids. Instruction-only ids stay out of HOST_CAPABILITIES.
INSTALL_HOST_IDS = (
    "claude",
    "codex",
    "grok",
    "gemini",
    "copilot",
    "opencode",
    "cursor",
    "grok-bot",
)
# Signals already read by this repository on 2026-11-08. Not detect_host(), and
# not PATH, GROK_SESSION_ID, GEMINI_HOME, GEMINI_PROJECT_DIR, or COPILOT_HOME.
IMPLICIT_CLIENT_SIGNALS = (
    ("CLAUDE_CODE_ENTRYPOINT", "claude"),
    ("CLAUDE_PLUGIN_ROOT", "claude"),
    ("CODEX_HOME", "codex"),
    ("GROK_HOOK_EVENT", "grok"),
    ("CURSOR_AGENT", "cursor"),
    ("CURSOR_CONVERSATION_ID", "cursor"),
)
PRECHECK_HOSTS = ("claude", "codex", "grok", "gemini")
CLIENT_QUESTION = "Which clients should this install complete?"


class InstallHostError(ValueError):
    """Explicit or implicit client selection failed closed."""


class InstallHostResolution:
    """Selected clients, and whether the interactive wizard may ask."""

    __slots__ = ("hosts", "prompt")

    def __init__(self, hosts: tuple[str, ...], prompt: bool) -> None:
        self.hosts = hosts
        self.prompt = prompt


def parse_install_hosts(raw: str) -> tuple[str, ...]:
    """Parse a comma- or whitespace-separated host list. Unknown ids fail closed."""
    parts = [part.strip().casefold() for part in re.split(r"[\s,]+", raw.strip()) if part.strip()]
    known = ", ".join(INSTALL_HOST_IDS)
    if not parts:
        raise InstallHostError(f"missing ChaosEngine host (choose from: {known})")
    unknown = [part for part in parts if part not in INSTALL_HOST_IDS]
    if unknown:
        raise InstallHostError(
            "unknown ChaosEngine host: " + ", ".join(unknown) + f" (choose from: {known})"
        )
    return tuple(host for host in INSTALL_HOST_IDS if host in parts)


def resolve_install_hosts(
    *, explicit: str | None = None, environ: dict[str, str] | None = None
) -> InstallHostResolution:
    """Map --hosts / CHAOS_ENGINE_HOST, else exactly one implicit client signal.

    An empty result means no client. The prompt flag is true only then, so the
    interactive wizard may ask. This function does not call detect_host().
    """
    env = os.environ if environ is None else environ
    flag = explicit.strip() if isinstance(explicit, str) else ""
    configured = str(env.get("CHAOS_ENGINE_HOST") or "").strip()
    if flag or configured:
        chosen = parse_install_hosts(flag or configured)
        if flag and configured and chosen != parse_install_hosts(configured):
            known = ", ".join(INSTALL_HOST_IDS)
            raise InstallHostError(
                f"CHAOS_ENGINE_HOST={configured} conflicts with --hosts {flag} (choose from: {known})"
            )
        return InstallHostResolution(chosen, False)
    found: list[str] = []
    for key, host in IMPLICIT_CLIENT_SIGNALS:
        value = env.get(key)
        if isinstance(value, str) and value.strip() and host not in found:
            found.append(host)
    if len(found) > 1:
        raise InstallHostError("multiple ChaosEngine clients are active: " + " and ".join(found))
    if found:
        return InstallHostResolution((found[0],), False)
    return InstallHostResolution((), True)


def prechecked_completion_hosts(*, which=shutil.which) -> tuple[str, ...]:
    """PATH pre-check for the interactive empty answer. Not Copilot and not Cursor."""
    return tuple(host for host in PRECHECK_HOSTS if which(host))


def ask_completion_hosts(*, input_stream, output, which=shutil.which) -> tuple[str, ...]:
    """Ask once. An empty answer is the pre-checked set. An unknown id does not continue."""
    prechecked = prechecked_completion_hosts(which=which)
    known = ", ".join(INSTALL_HOST_IDS)
    marked = ", ".join(prechecked) if prechecked else "none"
    output.write(f"{CLIENT_QUESTION} [{known}]\n")
    output.write(f"Pre-checked (empty answer selects these only): {marked}\n")
    output.write("Clients: ")
    output.flush()
    answer = input_stream.readline()
    if not answer.strip():
        return prechecked
    try:
        return parse_install_hosts(answer)
    except InstallHostError:
        output.write(f"Unknown client. Choose from: {known}\n")
        raise


def detect_install_hosts(*, which=shutil.which) -> list[tuple[str, str, bool]]:
    """Return (id, label, detected) for the five supported hosts."""
    detected: list[tuple[str, str, bool]] = []
    for host_id, command, label in HOST_DETECT_COMMANDS:
        found = which(command) is not None
        if host_id == "copilot" and not found:
            # Copilot is IDE-hosted; treat a present `code`/`cursor` CLI as a soft signal.
            found = which("code") is not None or which("cursor") is not None
        detected.append((host_id, label, found))
    return detected


def run_first_run_wizard(
    *,
    project: Path,
    repository: str,
    with_maven_tools: bool,
    input_stream,
    output,
    which=shutil.which,
    ask_clients: bool = False,
    resolved_hosts: tuple[str, ...] = (),
) -> tuple[str, ...] | None:
    """Guide a first-time interactive install before any network work."""
    hosts = detect_install_hosts(which=which)
    present = [label for _host_id, label, found in hosts if found]
    absent = [label for _host_id, label, found in hosts if not found]
    unicode = stream_supports_unicode(output)
    found_glyph = status_glyph("ok", unicode=unicode)
    missing_glyph = status_glyph("pending", unicode=unicode)
    output.write("ChaosEngine first-run wizard\n")
    output.write(_align_report("Project", str(project)) + "\n")
    output.write(_align_report("Source", repository) + "\n")
    output.write("\n  1. What gets installed\n")
    output.write(
        "     The portable ChaosEngine core, lifecycle hooks, Memory, MemPalace,\n"
        "     Graphify CLI, five host adapters, and the Caveman + Ponytail companion\n"
        "     skills (on by default; your off-switches still win).\n"
    )
    if with_maven_tools:
        output.write("     Maven Tools MCP will also be installed for this project.\n")
    output.write("\n  2. Hosts\n")
    if present:
        output.write("     Detected host CLIs: " + ", ".join(present) + "\n")
    else:
        output.write(
            "     No host CLIs detected yet (Claude Code, Codex, Grok, Gemini, or IDE).\n"
            "     Adapters still install for all five hosts.\n"
        )
    if absent:
        output.write("     Not detected on PATH: " + ", ".join(absent) + "\n")
    for _host_id, label, found in hosts:
        glyph = found_glyph if found else missing_glyph
        status = "on PATH" if found else "not on PATH"
        output.write(f"       {glyph} {label:<16} {status}\n")
    output.write("\n  3. Next after install\n")
    for host_id, label, found in hosts:
        glyph = found_glyph if found else missing_glyph
        output.write(f"     {glyph} {label}: {HOST_NEXT_ACTIONS[host_id]}\n")
    if resolved_hosts:
        selected: tuple[str, ...] | None = tuple(resolved_hosts)
    elif ask_clients:
        selected = ask_completion_hosts(input_stream=input_stream, output=output, which=which) or None
    else:
        selected = None
    output.write("\n")
    output.flush()
    confirm_operation("Install companions (Caveman + Ponytail) with the core", input_stream=input_stream, output=output)
    confirm_operation("Continue ChaosEngine install", input_stream=input_stream, output=output)
    return selected


@contextmanager
def interactive_terminal():
    path = "CONIN$" if os.name == "nt" else os.path.join(os.sep, "dev", "tty")
    try:
        with open(path, "r", encoding="utf-8") as stream:  # noqa: PTH123 - controlling terminal path.
            yield stream
    except OSError as error:
        raise RuntimeError("interactive mode requires a usable controlling terminal") from error


def parse_retry_after(value: str) -> float | None:
    try:
        delay = float(value)
    except ValueError:
        try:
            parsed = email.utils.parsedate_to_datetime(value)
        except (TypeError, ValueError, OverflowError):
            return None
        if parsed is None or parsed.tzinfo is None:
            return None
        delay = max(0.0, parsed.timestamp() - time.time())
    if not 0 <= delay <= MAX_RETRY_AFTER_SECONDS:
        return None
    return delay


GITHUB_TOKEN_HOSTS = frozenset(
    {"api.github.com", "github.com", "codeload.github.com", "raw.githubusercontent.com"}
)
GH_AUTH_TIMEOUT_SECONDS = 5
RATE_LIMIT_FAILURE = "GitHub API rate limit reached"
_GH_CLI_TOKEN: list[str | None] = []
_GH_CLI_LOCK = threading.Lock()


def _gh_cli_token() -> str | None:
    """`gh auth token` once per process, bounded; None when gh is absent or signed out."""
    if os.environ.get("CHAOS_ENGINE_GH_AUTH", "").strip().casefold() in {"0", "false", "no", "off"}:
        return None
    with _GH_CLI_LOCK:
        if not _GH_CLI_TOKEN:
            _GH_CLI_TOKEN.append(_read_gh_cli_token())
        return _GH_CLI_TOKEN[0]


def _read_gh_cli_token() -> str | None:
    executable = shutil.which("gh")
    if not executable:
        return None
    try:
        completed = subprocess.run(  # nosec B603 - resolved gh binary, fixed argv.
            [executable, "auth", "token", "--hostname", "github.com"],
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            timeout=GH_AUTH_TIMEOUT_SECONDS,
            check=False,
        )
    except (OSError, subprocess.SubprocessError, ValueError):
        return None
    token = (completed.stdout or "").strip()
    if completed.returncode != 0 or not token or any(character.isspace() for character in token):
        return None
    return token


def github_request_token() -> tuple[str | None, str]:
    """#6235: GITHUB_TOKEN, then GH_TOKEN, then `gh auth token`, else anonymous.

    Returns the token and the name of its source. The value is only ever put
    in an Authorization header; it is never printed, traced, or written.
    """
    for key in ("GITHUB_TOKEN", "GH_TOKEN"):
        value = os.environ.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip(), key
    token = _gh_cli_token()
    return (token, "gh auth token") if token else (None, "anonymous")


def request(url: str) -> urllib.request.Request:
    url = _rewrite_fixture_url(url)
    headers = {"Accept": "application/vnd.github+json", "User-Agent": "ChaosEngine-bootstrap"}
    if (urllib.parse.urlsplit(url).hostname or "").casefold() in GITHUB_TOKEN_HOSTS:
        token, _source = github_request_token()
        if token:
            headers["Authorization"] = f"Bearer {token}"
    return urllib.request.Request(url, headers=headers)


def _header(headers, name: str) -> str:
    if headers is None:
        return ""
    try:
        value = headers.get(name)
    except (AttributeError, TypeError):
        return ""
    if value is None:
        return ""
    return " ".join(str(value).split())[:80]


def _read_http_error_body(error: urllib.error.HTTPError) -> str:
    fp = getattr(error, "fp", None)
    if fp is None:
        return ""
    try:
        raw = fp.read(4096)
    except (OSError, ValueError, AttributeError):
        return ""
    if isinstance(raw, bytes):
        return raw.decode("utf-8", "replace")
    return str(raw or "")


def _remember_http_body(error: urllib.error.HTTPError) -> None:
    if getattr(error, "_ce_body", None) is not None:
        return
    error._ce_body = _read_http_error_body(error)


def _http_mentions_rate_limit(error: urllib.error.HTTPError) -> bool:
    if getattr(error, "_ce_body", None) is None:
        _remember_http_body(error)
    text = f"{getattr(error, 'msg', '') or ''}\n{getattr(error, '_ce_body', '') or ''}"
    return "rate limit" in text.casefold()


def http_error_detail(error: urllib.error.HTTPError) -> str:
    """Status, reason phrase, safe path, and rate-limit headers. No query or token."""
    url = str(getattr(error, "filename", None) or getattr(error, "url", "") or "")
    phrase = " ".join(str(getattr(error, "msg", "") or "").split())[:200]
    parts = [f"HTTP {error.code}"]
    if phrase:
        parts.append(phrase)
    parts.append(safe_url_path(url))
    extras = [
        f"{name}: {value}"
        for name in ("Retry-After", "X-RateLimit-Remaining", "X-RateLimit-Reset")
        if (value := _header(getattr(error, "headers", None), name))
    ]
    text = " ".join(parts)
    if extras:
        text += " (" + "; ".join(extras) + ")"
    return text


def rate_limit_failure(error: BaseException, url: str) -> str | None:
    """Actionable message for a GitHub 403/429 that is rate limited, else None.

    Quota is described as spent only when ``X-RateLimit-Remaining`` is ``0``.
    A reason phrase or body that says "rate limit" still names the status and path.
    """
    if not isinstance(error, urllib.error.HTTPError) or error.code not in {403, 429}:
        return None
    headers = error.headers
    remaining = _header(headers, "X-RateLimit-Remaining")
    if remaining != "0" and not _http_mentions_rate_limit(error):
        return None
    detail = http_error_detail(error)
    if remaining != "0":
        return (
            f"{RATE_LIMIT_FAILURE}: {detail}. "
            'Fix: export GITHUB_TOKEN="$(gh auth token)" '
            "(PowerShell: $env:GITHUB_TOKEN = gh auth token), or run `gh auth login` "
            "so the installer uses your GitHub login automatically; then rerun the same install command."
        )
    reset = _header(headers, "X-RateLimit-Reset")
    when = ""
    if reset.isdigit():
        minutes = max(0, round((int(reset) - time.time()) / 60))
        when = f"; it resets at {time.strftime('%H:%M UTC', time.gmtime(int(reset)))} (in about {minutes} min)"
    host = urllib.parse.urlsplit(url).hostname or "GitHub"
    _token, source = github_request_token()
    if source == "anonymous":
        quota = (
            f"{RATE_LIMIT_FAILURE}: the anonymous quota for {host} is spent{when}. "
            'Fix: export GITHUB_TOKEN="$(gh auth token)" '
            "(PowerShell: $env:GITHUB_TOKEN = gh auth token), or run `gh auth login` "
            "so the installer uses your GitHub login automatically; then rerun the same install command."
        )
    else:
        quota = (
            f"{RATE_LIMIT_FAILURE}: the quota of the token from {source} for {host} is spent{when}. "
            "Fix: wait for the reset, or export GITHUB_TOKEN with a different token; "
            "then rerun the same install command."
        )
    return f"{quota} Request: {detail}."


def valid_branch(branch: str) -> bool:
    parts = branch.split("/")
    return (
        re.fullmatch(r"[^\x00-\x20\x7f~^:?*\\\[\]]+", branch) is not None
        and not branch.startswith(("-", "/"))
        and not branch.endswith(("/", "."))
        and "//" not in branch
        and ".." not in branch
        and "@{" not in branch
        and branch != "HEAD"
        and all(part and not part.startswith(".") and not part.endswith(".lock") for part in parts)
    )


def is_transient_network_error(error: BaseException) -> bool:
    """True for blips worth a bounded exponential backoff (SSL EOF, GnuTLS, resets)."""
    if isinstance(error, urllib.error.HTTPError):
        retry_after = error.headers.get("Retry-After") if error.headers is not None else None
        return error.code in TRANSIENT_HTTP_STATUS or (
            error.code == 403 and retry_after is not None
        )
    if isinstance(error, (ConnectionError, TimeoutError, urllib.error.URLError)):
        return True
    if isinstance(error, ssl.SSLError):
        return True
    blob = f"{type(error).__name__}: {error}".upper()
    return any(marker in blob for marker in TRANSIENT_SSL_MARKERS)


def retry_delay(error: BaseException, attempt: int) -> float | None:
    """Per-attempt backoff; None means do not retry.

    CE 2026.10.31.8: ``ssl.SSLEOFError`` / UNEXPECTED_EOF used to return None
    (bare OSError path) and abort a 590-file raw download mid-tree. Treat SSL
    and marker-matched OSErrors as transient with exponential backoff.
    """
    if isinstance(error, urllib.error.HTTPError):
        retry_after = error.headers.get("Retry-After") if error.headers is not None else None
        if error.code not in TRANSIENT_HTTP_STATUS and not (
            error.code == 403 and retry_after is not None
        ):
            return None
        if retry_after is not None:
            delay = parse_retry_after(retry_after)
            if delay is None:
                return None
            return delay
        if error.code == 429:
            return MAX_RETRY_AFTER_SECONDS
        return RETRY_BASE_SECONDS * (2**attempt)
    if not is_transient_network_error(error):
        return None
    return RETRY_BASE_SECONDS * (2**attempt)


def rate_limit_reset_delay(error: BaseException) -> float | None:
    """One wait for a 403/429 that names ``X-RateLimit-Reset`` and not ``Retry-After``.

    The ceiling is ``MAX_RETRY_AFTER_SECONDS``, the same cap ``parse_retry_after`` uses.
    Callers sleep once and then fail; they do not open the request again.
    """
    if not isinstance(error, urllib.error.HTTPError) or error.code not in {403, 429}:
        return None
    headers = error.headers
    if headers is None or headers.get("Retry-After") is not None:
        return None
    if not _http_mentions_rate_limit(error):
        return None
    reset = _header(headers, "X-RateLimit-Reset")
    if not reset.isdigit():
        return None
    delay = max(0.0, int(reset) - time.time())
    if delay > MAX_RETRY_AFTER_SECONDS:
        return MAX_RETRY_AFTER_SECONDS
    return delay


class UpstreamReadError(RuntimeError):
    """A bounded upstream read failed. ``url_path`` is the path only, never a secret."""

    def __init__(self, message: str, *, url_path: str, http_status: int | None) -> None:
        super().__init__(message)
        self.url_path = url_path
        self.http_status = http_status


def safe_url_path(url: str) -> str:
    """Path of ``url`` with query, fragment, and userinfo removed."""
    path = urllib.parse.urlsplit(url).path or "/"
    if ".." in path.split("/"):
        return "/"
    path = re.sub(
        r"(?i)(token|secret|password|api_key)(=|/)[^/]+",
        r"\1\2<redacted>",
        path,
    )
    return path[:400]


def infer_read_purpose(url: str, purpose: str | None) -> str:
    """``download`` for source fetches; everything else stays a resolve read."""
    if purpose in {"download", "resolve"}:
        return purpose
    split = urllib.parse.urlsplit(url)
    host = (split.hostname or "").casefold()
    path = split.path.casefold()
    if host in {"raw.githubusercontent.com", "codeload.github.com"}:
        return "download"
    if (
        "git/trees/" in path
        or "/tarball/" in path
        or "/tar.gz/" in path
        or path.endswith(".tar.gz")
    ):
        return "download"
    return "resolve"


def upstream_read_failure_message(
    url: str, error: BaseException, attempts: int, purpose: str | None
) -> str:
    """Phase-specific cause. Resolve keeps the historical string; download names the HTTP status."""
    if infer_read_purpose(url, purpose) != "download":
        return "unable to resolve latest ChaosEngine from the configured upstream"
    status = error.code if isinstance(error, urllib.error.HTTPError) else None
    path = urllib.parse.urlsplit(url).path.casefold()
    label = (
        "tree"
        if "git/trees/" in path or "/tarball/" in path or "/tar.gz/" in path or path.endswith(".tar.gz")
        else "file"
    )
    status_text = f"HTTP {status} " if isinstance(status, int) else ""
    noun = "attempt" if attempts == 1 else "attempts"
    return (
        f"unable to download ChaosEngine source {label} "
        f"({status_text}after {attempts} {noun}): {safe_url_path(url)}"
    )


def _certificate_verify_failed(error: BaseException) -> bool:
    current: object = error
    for _ in range(5):
        if not isinstance(current, BaseException):
            return False
        if isinstance(current, ssl.SSLCertVerificationError):
            return True
        if "CERTIFICATE_VERIFY_FAILED" in str(current):
            return True
        reason = getattr(current, "reason", None)
        if isinstance(reason, BaseException) and reason is not current:
            current = reason
            continue
        cause = getattr(current, "__cause__", None)
        if isinstance(cause, BaseException) and cause is not current:
            current = cause
            continue
        return False
    return False


def _system_ca_context() -> ssl.SSLContext | None:
    """OS trust store. Verification stays required. Never an unverified context."""
    context = ssl.create_default_context()
    loaded = False
    if sys.platform == "darwin":
        chunks: list[bytes] = []
        for keychain in (
            "/System/Library/Keychains/SystemRootCertificates.keychain",
            "/Library/Keychains/System.keychain",
        ):
            if not os.path.isfile(keychain):
                continue
            try:
                chunks.append(
                    subprocess.check_output(  # nosec B603 - fixed security argv, no shell.
                        ["/usr/bin/security", "find-certificate", "-a", "-p", keychain],
                        stderr=subprocess.DEVNULL,
                        timeout=15,
                    )
                )
            except (OSError, subprocess.SubprocessError):
                continue
        blob = b"".join(chunks)
        if b"BEGIN CERTIFICATE" in blob:
            context.load_verify_locations(cadata=blob)
            loaded = True
    else:
        for candidate in (
            "/etc/ssl/certs/ca-certificates.crt",
            "/etc/pki/tls/certs/ca-bundle.crt",
            "/etc/ssl/cert.pem",
            "/etc/ssl/certs/ca-bundle.crt",
        ):
            if os.path.isfile(candidate):
                context.load_verify_locations(cafile=candidate)
                loaded = True
                break
    if not loaded or context.verify_mode != ssl.CERT_REQUIRED or not context.check_hostname:
        return None
    return context


def _open_request(opener, built, timeout: float):
    """Open once. On a missing issuer, retry once with the OS trust store.

    A caller-supplied opener is not replaced. Other errors are not retried.
    """
    try:
        try:
            return opener(built, timeout=timeout)
        except TypeError:
            return opener(built)
    except urllib.error.URLError as error:
        if opener is not urllib.request.urlopen or not _certificate_verify_failed(error):
            raise
        system = _system_ca_context()
        if system is None:
            raise
        return urllib.request.urlopen(built, timeout=timeout, context=system)


def read_response(
    opener,
    url: str,
    *,
    limit: int = MAX_RESPONSE_BYTES,
    sleeper=None,
    progress=None,
    purpose: str | None = None,
) -> bytes:
    sleeper = time.sleep if sleeper is None else sleeper
    for attempt in range(MAX_READ_ATTEMPTS):
        try:
            with _open_request(opener, request(url), 30) as response:
                chunks = []
                total = 0
                while chunk := response.read(min(64 * 1024, limit + 1 - total)):
                    chunks.append(chunk)
                    total += len(chunk)
                    if progress is not None:
                        progress(len(chunk))
                    if total > limit:
                        break
                value = b"".join(chunks)
            break
        except (OSError, TimeoutError, urllib.error.URLError) as error:
            try:
                delay = retry_delay(error, attempt)
            finally:
                if isinstance(error, urllib.error.HTTPError):
                    _remember_http_body(error)
                    error.close()
            if delay is None or attempt + 1 == MAX_READ_ATTEMPTS:
                limited = rate_limit_failure(error, url)
                if limited is not None:
                    raise RuntimeError(limited) from error
                status = error.code if isinstance(error, urllib.error.HTTPError) else None
                raise UpstreamReadError(
                    upstream_read_failure_message(url, error, attempt + 1, purpose),
                    url_path=safe_url_path(url),
                    http_status=status if isinstance(status, int) else None,
                ) from error
            sleeper(delay)
    if len(value) > limit:
        raise ValueError("ChaosEngine upstream response exceeds the download limit")
    return value


def normalize_repository(value: str) -> str:
    """Accept `owner/name` or `https://github.com/owner/name[.git]` (#6230).

    Anything else is returned unchanged so `resolve_latest` rejects it.
    """
    match = GITHUB_URL.fullmatch(value.strip())
    return match.group(1) if match else value


def _pinned_local_head() -> str | None:
    """HEAD of an explicit local clone. Used only after the network resolve fails."""
    env = os.environ.get(LOCAL_CLONE_ENV, "").strip()
    if not env:
        return None
    root = resolve_local_clone(env)
    if root is None:
        return None
    try:
        completed = subprocess.run(  # nosec B603 B607 - fixed git argv, checkout from the env.
            ["git", "-C", str(root), "rev-parse", "HEAD"],
            check=False,
            capture_output=True,
            text=True,
        )
    except OSError:
        return None
    commit = (completed.stdout or "").strip()
    if completed.returncode != 0 or COMMIT.fullmatch(commit) is None:
        return None
    return commit


def resolve_latest(repository: str, branch: str | None, opener=urllib.request.urlopen) -> tuple[str, str]:
    repository = normalize_repository(repository)
    components = repository.split("/")
    if (
        REPOSITORY.fullmatch(repository) is None
        or len(components) != 2
        or any(component in {".", ".."} for component in components)
    ):
        raise ValueError("repository must be an explicit GitHub owner/repository")
    if branch is None:
        try:
            repository_document = read_response(
                opener,
                f"https://api.github.com/repos/{repository}",
                purpose="resolve",
            )
        except (OSError, urllib.error.URLError, TimeoutError, RuntimeError):
            pinned = _pinned_local_head()
            if pinned is None:
                raise
            return pinned, "main"
        try:
            repository_value = json.loads(repository_document)
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise ValueError("GitHub returned invalid repository metadata") from error
        branch = repository_value.get("default_branch") if isinstance(repository_value, dict) else None
        if not isinstance(branch, str):
            raise ValueError("GitHub returned invalid repository metadata")
    if not valid_branch(branch):
        raise ValueError("branch is invalid")
    if COMMIT.fullmatch(branch) is not None:
        return branch, branch
    encoded_branch = urllib.parse.quote(branch, safe="")
    try:
        document = read_response(
            opener,
            f"https://api.github.com/repos/{repository}/commits/{encoded_branch}",
            purpose="resolve",
        )
    except (OSError, urllib.error.URLError, TimeoutError, RuntimeError):
        pinned = _pinned_local_head()
        if pinned is None:
            raise
        return pinned, branch
    try:
        value = json.loads(document)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ValueError("GitHub returned an invalid ChaosEngine revision") from error
    commit = value.get("sha") if isinstance(value, dict) else None
    if not isinstance(commit, str) or COMMIT.fullmatch(commit) is None:
        raise ValueError("GitHub returned an invalid ChaosEngine revision")
    return commit, branch


def is_pack_path(path: PurePosixPath) -> bool:
    """A project pack or add-on manifest file that ships beside the core.

    `<dir>/ce-pack/...` is a project pack; `<dir>/ce-addons/...` holds optional
    add-on manifests. Files an add-on includes from elsewhere are fetched only
    after the user selected it (`download_addon_files`).
    """
    return len(path.parts) >= 3 and path.parts[1] in {"ce-pack", "ce-addons"}


ADDON_FLAG = re.compile(r"--(with|without)-([a-z][a-z0-9-]*)")


def split_addon_flags(arguments: list[str]) -> tuple[set[str], set[str], list[str]]:
    """`--with-<addon>` / `--without-<addon>` are validated against manifests after download."""
    requested: set[str] = set()
    removed: set[str] = set()
    rest: list[str] = []
    for argument in arguments:
        match = ADDON_FLAG.fullmatch(argument)
        if match is None:
            rest.append(argument)
            continue
        (requested if match.group(1) == "with" else removed).add(match.group(2))
    return requested, removed, rest


def _select_addon_blobs(
    tree: list, destination: Path, patterns: list[tuple[PurePosixPath, str]]
) -> tuple[list[PurePosixPath], set[PurePosixPath]]:
    """Add-on blobs still missing under ``destination``, and which of them are ``100755``."""
    selected: list[PurePosixPath] = []
    executable: set[PurePosixPath] = set()
    for entry in tree:
        path = PurePosixPath(str(entry.get("path", "")))
        if entry.get("type") != "blob" or ".." in path.parts or path.is_absolute():
            continue
        if destination.joinpath(*path.parts).is_file():
            continue
        if not any(
            path.is_relative_to(base) and fnmatch.fnmatchcase(path.relative_to(base).as_posix(), pattern)
            for base, pattern in patterns
        ):
            continue
        size = entry.get("size")
        if not isinstance(size, int) or size < 0 or size > MAX_FILE_BYTES:
            raise ValueError("ChaosEngine source file exceeds the download limit")
        selected.append(path)
        if entry.get("mode") == "100755":
            executable.add(path)
    return selected, executable


def download_addon_files(
    repository: str,
    commit: str,
    destination: Path,
    source: Path,
    addons: tuple[str, ...],
    *,
    opener=urllib.request.urlopen,
    reporter: InstallReporter | None = None,
) -> int:
    """Fetch files selected repository-shipped add-ons include from outside their folder."""
    catalog_path = runtime_module(source, "addon_catalog.py")
    if not addons or not catalog_path.is_file():
        return 0
    catalog = types.SimpleNamespace(**runpy.run_path(str(catalog_path)))
    found = catalog.discover(source)
    patterns = []
    for name in addons:
        entry = found[name]
        if entry["internal"] or not entry["manifest"].get("include"):
            continue
        manifest_path = PurePosixPath(Path(entry["root"]).relative_to(destination).as_posix()) / catalog.MANIFEST
        patterns.extend(catalog.repository_paths(manifest_path, entry["manifest"]))
    if not patterns:
        return 0
    encoded_repository = "/".join(urllib.parse.quote(part, safe="") for part in repository.split("/"))
    document = read_response(
        opener,
        f"https://api.github.com/repos/{encoded_repository}/git/trees/{commit}?recursive=1",
        purpose="download",
    )
    value = json.loads(document)
    if not isinstance(value, dict) or value.get("truncated") is not False:
        raise ValueError("GitHub returned an incomplete ChaosEngine source tree")
    selected, executable = _select_addon_blobs(value.get("tree", []), destination, patterns)
    if len(selected) > MAX_FILES:
        raise ValueError("ChaosEngine add-on contains too many files")
    for path in selected:
        encoded_path = "/".join(urllib.parse.quote(part, safe="") for part in path.parts)
        content = read_response(
            opener,
            f"https://raw.githubusercontent.com/{encoded_repository}/{commit}/{encoded_path}",
            limit=MAX_FILE_BYTES,
            purpose="download",
        )
        target = destination.joinpath(*path.parts)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(content)
        if path in executable:
            mark_executable(target)
    if reporter is not None:
        reporter.trace(f"download {len(selected)} add-on files")
    return len(selected)


INSTALL_SOURCE_RECORD = ".chaos-engine-state/install-source.json"


def record_install_source(project: Path, repository: str, branch: str | None) -> None:
    """Keep the plain install source in local, untracked state for `maintain`.

    A portable manifest stores only digests and a consumer repository's origin is not
    the harness source, so `maintain` needs this record to rebuild the reinstall command.
    """
    path = Path(project) / INSTALL_SOURCE_RECORD
    path.parent.mkdir(parents=True, exist_ok=True)
    record = {"repository": normalize_repository(repository), "branch": branch or ""}
    path.write_text(json.dumps(record) + "\n", encoding="utf-8")


def git_blob_sha1(content: bytes) -> str:
    """Git blob oid for *content* (sha1 of blob header + NUL + bytes)."""
    digest = hashlib.sha1()
    digest.update(b"blob " + str(len(content)).encode("ascii") + bytes([0]))
    digest.update(content)
    return digest.hexdigest()


def git_tree_sha1(entries: list[tuple[str, str, str]]) -> str:
    """Git tree oid. Each entry is ``(mode, name, hex_sha)``; directories use mode ``40000``."""

    def sort_key(item: tuple[str, str, str]) -> str:
        mode, name, _hexsha = item
        return name + "/" if mode == "40000" else name

    body = b"".join(
        f"{mode} {name}".encode("utf-8") + b"\0" + bytes.fromhex(hexsha)
        for mode, name, hexsha in sorted(entries, key=sort_key)
    )
    return hashlib.sha1(f"tree {len(body)}\0".encode("ascii") + body).hexdigest()


def source_directory_tree_sha(files: dict[str, tuple[bytes, bool]]) -> str:
    """Tree oid of one directory. Keys are relative posix paths; values are ``(bytes, executable)``."""
    nested: dict = {}
    for raw, (content, executable) in files.items():
        parts = PurePosixPath(raw).parts
        if not parts or any(part in {"", ".", ".."} for part in parts):
            raise ValueError("ChaosEngine source tree contains an unsafe path")
        node = nested
        for part in parts[:-1]:
            child = node.get(part)
            if child is None:
                child = {}
                node[part] = child
            elif not isinstance(child, dict):
                raise ValueError("ChaosEngine source tree has an unexpected layout")
            node = child
        if isinstance(node.get(parts[-1]), dict):
            raise ValueError("ChaosEngine source tree has an unexpected layout")
        node[parts[-1]] = (content, executable)
    return _hash_source_tree(nested)


def _hash_source_tree(node: dict) -> str:
    entries: list[tuple[str, str, str]] = []
    for name, value in node.items():
        if isinstance(value, dict):
            entries.append(("40000", name, _hash_source_tree(value)))
        else:
            content, executable = value
            entries.append(("100755" if executable else "100644", name, git_blob_sha1(content)))
    return git_tree_sha1(entries)



ORIGIN_ONLY_ROOT_FILES = frozenset(
    {
        "CONTRIBUTING.md",
        "CODE_OF_CONDUCT.md",
        "SECURITY.md",
        "CHANGELOG.md",
        "ROADMAP.md",
    }
)


REMOTE_MANIFEST_NAME = "chaosengine-manifest.json"
RELEASE_VERSION = re.compile(r"^v?\d+\.\d+\.\d{8}(?:\.\d+)?$")
_SYNC_ACTIONS = frozenset({"unchanged", "update", "add", "restore", "edited", "stray", "remove"})


def normalize_payload(content: bytes) -> bytes:
    """Line-ending-only differences compare equal. The stored form is LF."""
    return content.replace(b"\r\n", b"\n").replace(b"\r", b"\n")


def payload_sha256(content: bytes) -> str:
    return hashlib.sha256(normalize_payload(content)).hexdigest()


def assert_safe_sync_path(path: str) -> PurePosixPath:
    relative = PurePosixPath(path)
    if (
        relative.is_absolute()
        or not relative.parts
        or ".." in relative.parts
        or any(part in {"", ".", ".."} for part in relative.parts)
    ):
        raise ValueError(f"CE-INSTALL-FAILED: unsafe path {path}")
    return relative


def plan_file_actions(
    remote_files: dict[str, dict[str, object]],
    base_files: dict[str, str],
    local_sha: dict[str, str],
) -> list[dict[str, object]]:
    """Compare remote manifest, installed base, and on-disk sha256.

    ``local_sha`` values are newline-normalized. A missing path is absent from the dict.
    """
    actions: list[dict[str, object]] = []
    paths = set(remote_files) | set(base_files) | set(local_sha)
    for path in sorted(paths):
        assert_safe_sync_path(path)
        remote = remote_files.get(path)
        base = base_files.get(path)
        local = local_sha.get(path)
        if path not in remote_files and path.startswith("addons/"):
            # Add-on payloads are published by the add-on step, not the core manifest.
            continue
        if path not in remote_files and path not in base_files:
            actions.append({"path": path, "action": "stray"})
            continue
        if path not in remote_files:
            actions.append({"path": path, "action": "remove", "edited": local is not None and local != base})
            continue
        remote_sha = str(remote.get("sha256") or "") if isinstance(remote, dict) else ""
        if local is None:
            actions.append({"path": path, "action": "add" if path not in base_files else "restore"})
            continue
        if base is not None and local == base and remote_sha == base:
            actions.append({"path": path, "action": "unchanged"})
            continue
        if base is not None and local == base and remote_sha != base:
            actions.append({"path": path, "action": "update"})
            continue
        if base is not None and local != base:
            actions.append({"path": path, "action": "edited", "remote": remote_sha})
            continue
        if local == remote_sha:
            actions.append({"path": path, "action": "unchanged"})
            continue
        actions.append({"path": path, "action": "add" if base is None else "update"})
    return actions


def sync_counts(actions: list[dict[str, object]]) -> dict[str, int]:
    counts = {name: 0 for name in sorted(_SYNC_ACTIONS)}
    for row in actions:
        action = str(row.get("action") or "")
        if action in counts:
            counts[action] += 1
    counts["updated"] = counts["update"]
    counts["added"] = counts["add"] + counts["restore"]
    return counts


def format_sync_counts(actions: list[dict[str, object]]) -> str:
    counts = sync_counts(actions)
    return f"{counts['updated']} updated, {counts['added']} added, {counts['unchanged']} unchanged"


def core_blob_cache_root() -> Path:
    """Same root as ``dependencies.download_cache_root``. Inlined: curl|bash has no package path."""
    override = os.environ.get("CHAOS_ENGINE_CACHE_DIR")
    if override:
        base = Path(override)
    elif os.name == "nt":
        base = Path(os.environ.get("LOCALAPPDATA") or Path.home() / "AppData/Local") / "chaos-engine"
    elif sys.platform == "darwin":
        base = Path.home() / "Library/Caches/chaos-engine"
    else:
        base = Path(os.environ.get("XDG_CACHE_HOME") or Path.home() / ".cache") / "chaos-engine"
    return base / "downloads"


def cached_git_blob(sha: str) -> bytes | None:
    """Bytes previously stored under their git blob oid."""
    if not re.fullmatch(r"[0-9a-fA-F]{40}", sha or ""):
        return None
    path = core_blob_cache_root() / "git" / sha.casefold()
    try:
        if path.is_file() and not path.is_symlink():
            return path.read_bytes()
    except OSError:
        return None
    return None


def _store_cache_bytes(root: Path, name: str, content: bytes) -> None:
    """Best-effort cache write. A same-key race or a full disk must not fail the download."""
    temporary: Path | None = None
    try:
        root.mkdir(parents=True, exist_ok=True)
        target = root / name
        if target.exists():
            return
        temporary = root / f".{name}.{os.getpid()}.{threading.get_ident()}.tmp"
        temporary.write_bytes(content)
        os.replace(temporary, target)
        temporary = None
    except OSError:
        return
    finally:
        if temporary is not None:
            try:
                temporary.unlink()
            except OSError:
                return


def store_git_blob(sha: str, content: bytes) -> None:
    if not re.fullmatch(r"[0-9a-fA-F]{40}", sha or ""):
        return
    _store_cache_bytes(core_blob_cache_root() / "git", sha.casefold(), content)


def cached_blob(digest: str) -> bytes | None:
    if not re.fullmatch(r"[0-9a-f]{64}", digest or ""):
        return None
    path = core_blob_cache_root() / digest
    try:
        if path.is_file() and not path.is_symlink():
            return path.read_bytes()
    except OSError:
        return None
    return None


def store_cached_blob(digest: str, content: bytes) -> None:
    if not re.fullmatch(r"[0-9a-f]{64}", digest or ""):
        return
    _store_cache_bytes(core_blob_cache_root(), digest, content)


def kept_edits_root(project: Path, stamp: str) -> Path:
    return project / ".chaos-engine-state" / "kept-edits" / stamp


def read_installed_file_index(project: Path) -> tuple[dict[str, str], dict[str, str]]:
    """Return ``(base sha256 by path, normalized local sha256 by path)`` for ``.chaos-engine``."""
    target = project / ".chaos-engine"
    base: dict[str, str] = {}
    manifest_path = target / "manifest.json"
    if manifest_path.is_file() and not manifest_path.is_symlink():
        try:
            document = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError):
            document = {}
        files = document.get("files") if isinstance(document, dict) else None
        if isinstance(files, dict):
            base = {str(key): str(value) for key, value in files.items() if isinstance(value, str)}
    local: dict[str, str] = {}
    if not target.is_dir():
        return base, local
    for path in sorted(target.rglob("*")):
        if path.is_symlink() or not path.is_file():
            if path.is_symlink():
                raise ValueError(f"CE-INSTALL-FAILED: link in installed tree: {path}")
            continue
        relative = path.relative_to(target).as_posix()
        if relative == "manifest.json" or "__pycache__" in PurePosixPath(relative).parts or relative.endswith(".pyc"):
            continue
        if relative in {"runtime/entry-stamp", ".overlay-materialize.json"}:
            continue
        local[relative] = payload_sha256(path.read_bytes())
    return base, local


def _is_addon_receipt_path(path: str) -> bool:
    parts = PurePosixPath(path).parts
    return len(parts) == 3 and parts[0] == "addons" and parts[2] == "receipt.json"


def verify_named_paths(target: Path) -> list[str]:
    """Owned paths whose raw bytes differ from the manifest digest.

    The manifest stores ``file_sha256`` of the original bytes. A newline-normalized
    hash false-positives a CR checkout. Add-on receipts are not ownership.
    """
    project = target.parent if target.name == ".chaos-engine" else target
    base, _local = read_installed_file_index(project)
    root = project / ".chaos-engine"
    drifted: list[str] = []
    for path, digest in base.items():
        if _is_addon_receipt_path(path):
            continue
        file = root / path
        if file.is_symlink() or not file.is_file():
            drifted.append(path)
            continue
        if hashlib.sha256(file.read_bytes()).hexdigest() != digest:
            drifted.append(path)
    return sorted(drifted)


class SyncKeepEdits(SystemExit):
    """``--keep-edits`` found user edits. Exit 3 and do not publish."""

    def __init__(self, paths: list[str]):
        super().__init__(3)
        self.paths = list(paths)


class DryRunDone(Exception):
    """The plan was printed and nothing under the project was published."""

    def __init__(self, actions: list[dict[str, object]], commit: str):
        super().__init__("dry-run")
        self.actions = actions
        self.commit = commit


def omitted_source_relative(relative: PurePosixPath) -> bool:
    """Brand masters, research notes, repo community files, CI and repo tests are not part of the portable core."""
    return (
        relative.parts[:2] == ("assets", "brand")
        or relative.parts[:1] in {(".github",), ("tests",), ("experiments",), ("graphify-out",), ("docs",)}
        or relative.as_posix() in ORIGIN_ONLY_ROOT_FILES
        or relative.as_posix() == REMOTE_MANIFEST_NAME
    )


def _select_source_blobs(
    tree: list,
) -> tuple[list[tuple[PurePosixPath, int, str]], int, set[PurePosixPath]]:
    """Bounded ChaosEngine and pack blobs to download, their total size, and the ``100755`` ones.

    Each selected row is ``(path, size, blob_sha)`` so ``fetch_blob`` can verify
    content against the tree oid after download/retry (not size alone).
    """
    selected: list[tuple[PurePosixPath, int, str]] = []
    executable: set[PurePosixPath] = set()
    total = 0
    for entry in tree:
        if not isinstance(entry, dict) or not isinstance(entry.get("path"), str):
            raise ValueError("GitHub returned an invalid ChaosEngine source tree")
        path = PurePosixPath(entry["path"])
        if path.is_absolute() or ".." in path.parts or not path.parts:
            raise ValueError("ChaosEngine source tree contains an unsafe path")
        if path.parts[0] != "chaos-engine" and not is_pack_path(path):
            continue
        if entry.get("type") == "tree":
            continue
        if entry.get("type") != "blob" or entry.get("mode") not in {"100644", "100755"}:
            raise ValueError("ChaosEngine source tree contains an unsupported entry")
        # Omit before the size gate. An experiments blob over MAX_FILE_BYTES is not installed.
        # Pack blobs stay on the size gate: they are not chaos-engine relative paths.
        if path.parts[0] == "chaos-engine" and not is_pack_path(path):
            relative = PurePosixPath(*path.parts[1:])
            if not relative.parts:
                raise ValueError("ChaosEngine source tree has an unexpected layout")
            if omitted_source_relative(relative):
                continue
        size = entry.get("size")
        if not isinstance(size, int) or size < 0 or size > MAX_FILE_BYTES:
            raise ValueError("ChaosEngine source file exceeds the download limit")
        sha = entry.get("sha")
        if not isinstance(sha, str) or len(sha) != 40:
            raise ValueError("ChaosEngine source tree entry is missing a blob sha")
        if entry.get("mode") == "100755":
            executable.add(path)
        if is_pack_path(path):
            selected.append((path, size, sha))
            total += size
            continue
        selected.append((path, size, sha))
        total += size
    return selected, total, executable


def mark_executable(path: Path) -> None:
    """Keep a Git ``100755`` blob runnable; raw downloads arrive as plain files."""
    mode = path.stat().st_mode
    path.chmod(mode | ((mode & 0o444) >> 2))


def resolve_local_clone(explicit: str | Path | None = None) -> Path | None:
    """Return a usable local repo root containing ``chaos-engine/``, or None.

    Order: explicit arg → ``CHAOS_ENGINE_LOCAL_CLONE`` env → this source tree.
    No absolute machine paths are embedded (portable-core guard).
    """
    candidates: list[Path] = []
    if explicit is not None:
        candidates.append(Path(explicit))
    env = os.environ.get(LOCAL_CLONE_ENV, "").strip()
    if env:
        candidates.append(Path(env))
    # The checkout that shipped this bootstrap.py (same repo the bot is in).
    # A repository-root source checkout ships bootstrap.py at its root (#8057 R1).
    # Only a git checkout qualifies, so an installed overlay is never a source.
    # It is tried before the parent directory so a sibling tree never wins.
    here = Path(__file__).resolve().parent
    if (here / ".git").exists() and (here / ROOT_SKILL_PATH).is_file():
        candidates.append(here)
    candidates.append(Path(__file__).resolve().parents[1])
    seen: set[Path] = set()
    for candidate in candidates:
        try:
            root = candidate.resolve()
        except OSError:
            continue
        if root in seen:
            continue
        seen.add(root)
        # Root layout first, then the legacy nested folder (#8057 R1).
        if (root / ROOT_SKILL_PATH).is_file() and (root / "install.py").is_file() and (root / "VERSION").is_file():
            return root
        ce = root / "chaos-engine"
        if not ce.is_dir():
            # Allow pointing straight at chaos-engine/
            if (root / "install.py").is_file() and (root / "VERSION").is_file():
                return root.parent if root.name == "chaos-engine" else root
            continue
        if (ce / "install.py").is_file() and (ce / "VERSION").is_file():
            return root
    return None


def copy_source_from_local_clone(
    local_root: Path,
    destination: Path,
    *,
    reporter: InstallReporter | None = None,
) -> Path:
    """Copy the bounded ChaosEngine subtree from a local clone (network fallback)."""
    local_root = Path(local_root).resolve()
    if (local_root / ROOT_SKILL_PATH).is_file():
        # Repository-root layout wins over a nested folder (#8057 R1).
        source_src = local_root
    else:
        source_src = local_root / "chaos-engine"
    if not source_src.is_dir():
        raise ValueError(f"local clone missing chaos-engine/: {local_root}")
    source = destination / "chaos-engine"
    if source.exists():
        shutil.rmtree(source)
    caches = shutil.ignore_patterns("__pycache__", ".pytest_cache", "*.pyc", ".git")

    def ignore(directory: str, names: list[str]) -> set[str]:
        # Same omit rule as the remote download, applied to source-relative paths.
        skipped = set(caches(directory, names))
        base = Path(directory).resolve().relative_to(source_src.resolve())
        # relative_to(self) is '.'; that prefix must not hide root omit rules.
        parts = () if base.parts == (".",) else base.parts
        for name in names:
            relative = PurePosixPath(*parts, name)
            if omitted_source_relative(relative):
                skipped.add(name)
        if not parts:
            # A repo-root tempfile directory is not source.
            skipped.update(name for name in names if name.startswith("tmp"))
        return skipped

    try:
        shutil.copytree(source_src, source, ignore=ignore)
    except shutil.Error as error:
        rows = error.args[0] if error.args else []
        vanished_temp = rows and all(
            isinstance(row, tuple)
            and len(row) >= 3
            and Path(str(row[0])).name.startswith("tmp")
            and "No such file or directory" in str(row[2])
            for row in rows
        )
        if not vanished_temp:
            raise
    if not (source / "skills/chaos-engine/SKILL.md").is_file():
        raise ValueError("local ChaosEngine clone is incomplete")
    if reporter is not None:
        reporter.trace("local-clone fallback")
    return source


def _rewrite_fixture_url(url: str) -> str:
    origin = os.environ.get("CHAOS_ENGINE_FIXTURE_ORIGIN", "").strip().rstrip("/")
    if not origin:
        return url
    for prefix in (
        "https://raw.githubusercontent.com",
        "https://api.github.com",
        "https://codeload.github.com",
        "https://github.com",
    ):
        if url.startswith(prefix):
            return origin + url[len(prefix) :]
    return url


def _opening(opener, url: str, timeout: float = 60, *, rewrite: bool = True):
    target = _rewrite_fixture_url(url) if rewrite else url
    headers = {"Accept": "application/vnd.github+json", "User-Agent": "ChaosEngine-bootstrap"}
    host = (urllib.parse.urlsplit(target).hostname or "").casefold()
    if host in GITHUB_TOKEN_HOSTS:
        token, _source = github_request_token()
        if token:
            headers["Authorization"] = f"Bearer {token}"
    built = urllib.request.Request(target, headers=headers)
    return _open_request(opener, built, timeout)


def _read_url_bytes(opener, url: str, *, limit: int = 8_000_000, rewrite: bool = True) -> bytes:
    with _opening(opener, url, rewrite=rewrite) as response:
        payload = response.read(limit + 1)
    if len(payload) > limit:
        raise ValueError("CE-INSTALL-FAILED: response exceeds the download limit")
    return payload


def _manifest_document(payload: bytes) -> dict[str, object] | None:
    try:
        document = json.loads(payload.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return None
    if not isinstance(document, dict) or not isinstance(document.get("files"), dict):
        return None
    return document


def fetch_remote_manifest(repository: str, commit: str, opener) -> dict[str, object] | None:
    """One manifest request. ``None`` when this revision does not publish one."""
    encoded = "/".join(urllib.parse.quote(part, safe="") for part in repository.split("/"))
    url = f"https://raw.githubusercontent.com/{encoded}/{commit}/{REMOTE_MANIFEST_NAME}"
    try:
        payload = _read_url_bytes(opener, url)
    except (OSError, urllib.error.URLError, ValueError, KeyError, TypeError):
        return None
    return _manifest_document(payload)


def verify_release_manifest(repository: str, version: str, opener) -> dict[str, object]:
    """Check the release ``.sha256`` before any blob download. A mismatch refuses the pin."""
    tag = version if version.startswith("v") else f"v{version}"
    encoded = "/".join(urllib.parse.quote(part, safe="") for part in repository.split("/"))
    base = f"https://github.com/{encoded}/releases/download/{urllib.parse.quote(tag, safe='')}"
    manifest_bytes = _read_url_bytes(opener, f"{base}/{REMOTE_MANIFEST_NAME}")
    digest_bytes = _read_url_bytes(opener, f"{base}/{REMOTE_MANIFEST_NAME}.sha256")
    expected = digest_bytes.decode("utf-8", "replace").strip().split()[0].lower()
    actual = hashlib.sha256(manifest_bytes).hexdigest()
    if expected != actual:
        raise ValueError("CE-INSTALL-FAILED: release manifest sha256 does not match")
    attestation = f"{base}/{REMOTE_MANIFEST_NAME}.intoto.jsonl"
    try:
        evidence = _read_url_bytes(opener, attestation)
    except (OSError, urllib.error.URLError, ValueError):
        evidence = b""
    if evidence and actual not in evidence.decode("utf-8", "replace"):
        raise ValueError("CE-INSTALL-FAILED: release attestation does not match the manifest")
    document = _manifest_document(manifest_bytes)
    if document is None:
        raise ValueError("CE-INSTALL-FAILED: release manifest is invalid")
    return document


def _stage_dir(project: Path, commit: str) -> Path:
    return project / ".chaos-engine-state" / "stage" / commit


def _blob_matches(content: bytes, digest: str, blob_sha: str) -> bool:
    if digest and payload_sha256(content) != digest and hashlib.sha256(content).hexdigest() != digest:
        return False
    if blob_sha and git_blob_sha1(normalize_payload(content)) != blob_sha and git_blob_sha1(content) != blob_sha:
        return False
    return True


def _copy_kept(project: Path, stamp: str, relative: str, source: Path) -> None:
    destination = kept_edits_root(project, stamp) / relative
    destination.parent.mkdir(parents=True, exist_ok=True)
    if source.is_symlink():
        raise ValueError(f"CE-INSTALL-FAILED: refusing to keep a link: {relative}")
    shutil.copy2(source, destination)


def materialize_manifest_sync(
    project: Path,
    destination: Path,
    manifest: dict[str, object],
    *,
    opener,
    repository: str,
    offline: bool = False,
    keep_edits: bool = False,
    force: bool = False,
    dry_run: bool = False,
) -> tuple[Path, list[dict[str, object]]]:
    """Build a source tree from the remote manifest, downloading only add/update/restore."""
    commit = str(manifest.get("commit") or "")
    if COMMIT.fullmatch(commit) is None:
        raise ValueError("CE-INSTALL-FAILED: manifest commit is invalid")
    remote_files = manifest.get("files")
    if not isinstance(remote_files, dict):
        raise ValueError("CE-INSTALL-FAILED: manifest files are invalid")
    typed: dict[str, dict[str, object]] = {}
    for key, value in remote_files.items():
        assert_safe_sync_path(str(key))
        if not isinstance(value, dict):
            raise ValueError("CE-INSTALL-FAILED: manifest entry is invalid")
        mode = str(value.get("mode") or "100644")
        if mode not in {"100644", "100755"}:
            raise ValueError("CE-INSTALL-FAILED: unsupported manifest mode")
        typed[str(key)] = value
    base, local = read_installed_file_index(project)
    actions = plan_file_actions(typed, base, local)
    edited = [str(row["path"]) for row in actions if row["action"] == "edited"]
    if keep_edits and edited:
        raise SyncKeepEdits(edited)
    materialize_manifest_sync.downloads = 0  # type: ignore[attr-defined]
    if os.environ.get("CHAOS_ENGINE_QUIET") != "1":
        print("Will do: " + format_sync_counts(actions), file=sys.stderr)
    if dry_run:
        return destination / "chaos-engine", actions
    installed = project / ".chaos-engine"
    stage = _stage_dir(project, commit)
    encoded_repo = "/".join(urllib.parse.quote(part, safe="") for part in repository.split("/"))
    root_layout = manifest.get("rootLayout") is not False
    missing: list[str] = []
    for row in actions:
        action = str(row["action"])
        if action in {"unchanged", "stray", "remove"}:
            continue
        path = str(row["path"])
        meta = typed[path]
        digest = str(meta.get("sha256") or "")
        blob_sha = str(meta.get("gitBlobSha1") or "")
        staged = stage / path
        if staged.is_file() and not staged.is_symlink() and _blob_matches(staged.read_bytes(), digest, blob_sha):
            continue
        cached = cached_blob(digest) if digest else None
        if cached is not None and _blob_matches(cached, digest, blob_sha):
            continue
        missing.append(path)
    if offline and missing:
        raise ValueError("CE-INSTALL-FAILED: offline cache miss: " + ", ".join(missing))
    payloads: dict[str, bytes] = {}
    downloads = 0
    for row in actions:
        action = str(row["action"])
        if action in {"unchanged", "stray", "remove"}:
            continue
        path = str(row["path"])
        installed_path = installed / path
        if installed_path.is_symlink() or (stage / path).is_symlink():
            raise ValueError(f"CE-INSTALL-FAILED: link: {path}")
        meta = typed[path]
        digest = str(meta.get("sha256") or "")
        blob_sha = str(meta.get("gitBlobSha1") or "")
        content: bytes | None = None
        staged = stage / path
        if staged.is_file() and not staged.is_symlink() and _blob_matches(staged.read_bytes(), digest, blob_sha):
            content = staged.read_bytes()
        if content is None and digest:
            cached = cached_blob(digest)
            if cached is not None and _blob_matches(cached, digest, blob_sha):
                content = cached
        if content is None:
            if offline:
                raise ValueError(f"CE-INSTALL-FAILED: offline cache miss: {path}")
            remote_path = path if root_layout else f"chaos-engine/{path}"
            url = f"https://raw.githubusercontent.com/{encoded_repo}/{commit}/{remote_path}"
            content = _read_url_bytes(opener, url)
            downloads += 1
            if not _blob_matches(content, digest, blob_sha):
                raise ValueError(f"CE-INSTALL-FAILED: sha256 mismatch: {path}")
            staged.parent.mkdir(parents=True, exist_ok=True)
            if staged.is_symlink():
                raise ValueError(f"CE-INSTALL-FAILED: link: {path}")
            staged.write_bytes(content)
            if digest:
                store_cached_blob(digest, normalize_payload(content))
        payloads[path] = content
    materialize_manifest_sync.downloads = downloads  # type: ignore[attr-defined]
    stamp = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
    if not force:
        for row in actions:
            action = str(row["action"])
            if action not in {"edited", "stray", "remove"}:
                continue
            path = str(row["path"])
            installed_path = installed / path
            if installed_path.is_symlink():
                raise ValueError(f"CE-INSTALL-FAILED: link: {path}")
            if installed_path.is_file():
                _copy_kept(project, stamp, path, installed_path)
    source = destination / "chaos-engine"
    if source.exists():
        shutil.rmtree(source)
    source.mkdir(parents=True, exist_ok=True)
    for row in actions:
        path = str(row["path"])
        action = str(row["action"])
        if action in {"stray", "remove"}:
            continue
        meta = typed[path]
        target = source / path
        target.parent.mkdir(parents=True, exist_ok=True)
        if action == "unchanged" and (installed / path).is_file():
            raw = (installed / path).read_bytes()
            shutil.copy2(installed / path, target)
            if normalize_payload(raw) != raw:
                target.write_bytes(normalize_payload(raw))
            continue
        content = payloads[path]
        target.write_bytes(normalize_payload(content))
        if str(meta.get("mode")) == "100755":
            mark_executable(target)
    if os.environ.get("CHAOS_ENGINE_QUIET") != "1":
        print(format_sync_counts(actions), file=sys.stderr)
        edited = [str(row["path"]) for row in actions if row["action"] == "edited"]
        if edited and not force:
            print("kept edits: " + ", ".join(edited), file=sys.stderr)
            print(kept_edits_root(project, stamp).as_posix(), file=sys.stderr)
    if not (source / "skills/chaos-engine/SKILL.md").is_file():
        raise ValueError("ChaosEngine source tree is incomplete")
    return source, actions


def download_source(
    repository: str,
    commit: str,
    destination: Path,
    *,
    opener=urllib.request.urlopen,
    reporter: InstallReporter | None = None,
    local_clone: str | Path | None = None,
    project: Path | None = None,
) -> Path:
    """Per-file download with SSL retries; fall back to a local clone on network failure."""
    download_source.last_root_layout = True  # type: ignore[attr-defined]
    download_source.last_actions = []  # type: ignore[attr-defined]
    if project is not None and (project / ".chaos-engine" / "manifest.json").is_file():
        try:
            manifest = fetch_remote_manifest(repository, commit, opener)
            if manifest is not None and str(manifest.get("commit") or commit) in {commit, str(manifest.get("commit"))}:
                if manifest.get("commit") in {None, ""}:
                    manifest = dict(manifest)
                    manifest["commit"] = commit
                source, actions = materialize_manifest_sync(
                    project,
                    destination,
                    manifest,
                    opener=opener,
                    repository=repository,
                    offline=os.environ.get("CHAOS_ENGINE_OFFLINE") == "1",
                    keep_edits=os.environ.get("CHAOS_ENGINE_KEEP_EDITS") == "1",
                    force=os.environ.get("CHAOS_ENGINE_FORCE") == "1",
                    dry_run=os.environ.get("CHAOS_ENGINE_DRY_RUN") == "1",
                )
                download_source.last_root_layout = manifest.get("rootLayout") is not False  # type: ignore[attr-defined]
                download_source.last_actions = actions  # type: ignore[attr-defined]
                download_source.last_downloads = int(getattr(materialize_manifest_sync, "downloads", 0))  # type: ignore[attr-defined]
                if reporter is not None:
                    reporter.trace(format_sync_counts(actions))
                return source
        except SyncKeepEdits:
            raise
        except ValueError as error:
            if str(error).startswith("CE-INSTALL-FAILED"):
                raise
        except (OSError, urllib.error.URLError, KeyError, TypeError):
            pass
    try:
        source = download_source_remote(
            repository, commit, destination, opener=opener, reporter=reporter, project=project
        )
        download_source.last_root_layout = bool(getattr(download_source_remote, "last_root_layout", True))  # type: ignore[attr-defined]
        return source
    except (RuntimeError, OSError, urllib.error.URLError) as error:
        blob = f"{type(error).__name__}: {error}".upper()
        networkish = (
            is_transient_network_error(error)
            or "UNABLE TO RESOLVE" in blob
            or any(marker in blob for marker in TRANSIENT_SSL_MARKERS)
            or isinstance(error, RuntimeError)
        )
        if not networkish:
            raise
        trace_upstream_failure(reporter, error)
        root = resolve_local_clone(local_clone)
        if root is None:
            raise
        if reporter is not None:
            reporter.trace(
                f"download failed ({type(error).__name__}); falling back to local clone"
            )
        return copy_source_from_local_clone(root, destination, reporter=reporter)


def _parse_git_tree(document: bytes) -> list:
    try:
        value = json.loads(document)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ValueError("GitHub returned an invalid ChaosEngine source tree") from error
    if not isinstance(value, dict) or value.get("truncated") is not False:
        raise ValueError("GitHub returned an incomplete ChaosEngine source tree")
    tree = value.get("tree")
    if not isinstance(tree, list):
        raise ValueError("GitHub returned an invalid ChaosEngine source tree")
    return tree


def _tree_lists_chaos_engine_paths(tree: list) -> bool:
    """True when paths are already repository-relative (fixture or expanded tree).

    A non-recursive root listing names ``chaos-engine`` itself as a tree and is not expanded.
    """
    for entry in tree:
        if not isinstance(entry, dict):
            continue
        path = entry.get("path")
        if not isinstance(path, str):
            continue
        if path == "chaos-engine" and entry.get("type") == "tree":
            continue
        if path == "chaos-engine" or path.startswith("chaos-engine/"):
            return True
    return False


def _tree_sha(entry: dict | None) -> str | None:
    if not isinstance(entry, dict):
        return None
    sha = entry.get("sha")
    if isinstance(sha, str) and COMMIT.fullmatch(sha):
        return sha
    return None


def _read_git_tree(opener, encoded_repository: str, sha: str, *, recursive: bool) -> list:
    suffix = "?recursive=1" if recursive else ""
    url = f"https://api.github.com/repos/{encoded_repository}/git/trees/{sha}{suffix}"
    return _parse_git_tree(read_response(opener, url, purpose="download"))


def _prefix_tree(tree: list, prefix: str) -> list:
    """Prefix a subtree so selectors keep repository-relative paths."""
    prefixed = []
    for entry in tree:
        if not isinstance(entry, dict) or not isinstance(entry.get("path"), str):
            raise ValueError("GitHub returned an invalid ChaosEngine source tree")
        path = entry["path"]
        copied = dict(entry)
        if path == prefix or path.startswith(prefix + "/"):
            copied["path"] = path
        else:
            copied["path"] = f"{prefix}/{path}" if path else prefix
        prefixed.append(copied)
    return prefixed


class ResolvedTreeUnavailable(Exception):
    """A recursive fetch failed after pack discovery had already finished."""

    def __init__(self, tree_shas: dict[str, str], *, root_layout: bool = False):
        super().__init__("ChaosEngine source tree listing failed")
        self.tree_shas = dict(tree_shas)
        self.root_layout = root_layout


def _discover_pack_trees(root: list, opener, encoded_repository: str, tree_shas: dict[str, str]) -> None:
    """Record ``<dir>/ce-pack`` and ``<dir>/ce-addons`` oids from one-level listings.

    Only those two child trees are fetched recursively. The parent directory and
    the rest of the repository are not.
    """
    for item in root:
        if not isinstance(item, dict) or item.get("type") != "tree":
            continue
        name = item.get("path")
        if not isinstance(name, str) or name == "chaos-engine" or "/" in name or name in {"", ".", ".."}:
            continue
        parent_sha = _tree_sha(item)
        if parent_sha is None:
            raise ValueError("GitHub returned an invalid ChaosEngine source tree")
        children = _read_git_tree(opener, encoded_repository, parent_sha, recursive=False)
        for child in children:
            if not isinstance(child, dict) or child.get("type") != "tree":
                continue
            child_name = child.get("path")
            if child_name not in {"ce-pack", "ce-addons"}:
                continue
            child_sha = _tree_sha(child)
            if child_sha is None:
                raise ValueError("GitHub returned an invalid ChaosEngine source tree")
            tree_shas[f"{name}/{child_name}"] = child_sha


ROOT_SKILL_PATH = "skills/chaos-engine/SKILL.md"
NESTED_PREFIX = "chaos-engine"


def _root_tree_has_layout_hint(root: list) -> bool:
    """A one-level listing that could be a repository-root ChaosEngine tree."""
    names = {
        (item.get("path"), item.get("type"))
        for item in root
        if isinstance(item, dict)
    }
    return ("skills", "tree") in names and ("install.py", "blob") in names


def _has_root_skill(entries: list) -> bool:
    return any(
        isinstance(entry, dict)
        and entry.get("path") == ROOT_SKILL_PATH
        and entry.get("type") == "blob"
        for entry in entries
    )


def remote_source_path(repository_path: PurePosixPath, *, root_layout: bool) -> PurePosixPath:
    """Path in the upstream repository for an internal ``chaos-engine/...`` path.

    Internally every core path is ``chaos-engine/<relative>``. A repository-root
    layout (the standalone repo, #8057 R1) stores the same file at ``<relative>``.
    """
    if root_layout and repository_path.parts[:1] == (NESTED_PREFIX,):
        relative = PurePosixPath(*repository_path.parts[1:])
        if not relative.parts:
            raise ValueError("ChaosEngine source tree has an unexpected layout")
        return relative
    return repository_path


def fetch_chaos_engine_source(
    encoded_repository: str, commit: str, opener
) -> tuple[list, dict[str, str], bool]:
    """Core entries, tree identities, and whether the source sits at the repository root.

    Prefix order (#8057 R1): a root-level ``skills/chaos-engine/SKILL.md`` makes
    the repository root the source; else a nested ``chaos-engine/`` tree keeps the
    legacy filter; else fail closed. Root-layout entries are re-keyed under
    ``chaos-engine/`` so the selectors and verifiers stay layout-agnostic.
    """
    root_url = f"https://api.github.com/repos/{encoded_repository}/git/trees/{commit}"
    document = read_response(opener, root_url, purpose="download")
    root = _parse_git_tree(document)
    if _tree_lists_chaos_engine_paths(root):
        return root, {}, False
    if _root_tree_has_layout_hint(root):
        try:
            root_sha = json.loads(document).get("sha")
        except (UnicodeDecodeError, json.JSONDecodeError, AttributeError):
            root_sha = None
        if not isinstance(root_sha, str) or COMMIT.fullmatch(root_sha) is None:
            raise ValueError("GitHub returned an invalid ChaosEngine source tree")
        tree_shas = {NESTED_PREFIX: root_sha}
        try:
            expanded = _read_git_tree(opener, encoded_repository, root_sha, recursive=True)
        except (UpstreamReadError, OSError, TimeoutError, urllib.error.URLError) as error:
            raise ResolvedTreeUnavailable(tree_shas, root_layout=True) from error
        if _has_root_skill(expanded):
            prefixed = []
            for entry in expanded:
                if not isinstance(entry, dict) or not isinstance(entry.get("path"), str):
                    raise ValueError("GitHub returned an invalid ChaosEngine source tree")
                copied = dict(entry)
                copied["path"] = f"{NESTED_PREFIX}/{entry['path']}"
                prefixed.append(copied)
            return prefixed, tree_shas, True
    entries, tree_shas = _fetch_nested_tree(root, encoded_repository, opener)
    return entries, tree_shas, False


def fetch_chaos_engine_tree(
    encoded_repository: str, commit: str, opener
) -> tuple[list, dict[str, str]]:
    """Compatibility wrapper: entries and tree identities, without the layout flag."""
    entries, tree_shas, _root_layout = fetch_chaos_engine_source(encoded_repository, commit, opener)
    return entries, tree_shas


def _fetch_nested_tree(
    root: list, encoded_repository: str, opener
) -> tuple[list, dict[str, str]]:
    """Core blobs plus sibling ce-pack/ce-addons. Never ``git/trees/<commit>?recursive=1``.

    The map is complete before any recursive fetch: ``chaos-engine`` plus every
    ``<dir>/ce-pack`` and ``<dir>/ce-addons`` the one-level scan found. An
    already-expanded fixture returns an empty map. A recursive fetch of an
    already-discovered tree keeps that complete map so the tarball can be
    checked against every identity. A parent or pack listing that fails before
    the scan finishes is the original download error, not a partial map.
    """
    core_sha = _tree_sha(
        next(
            (
                item
                for item in root
                if isinstance(item, dict)
                and item.get("path") == "chaos-engine"
                and item.get("type") == "tree"
            ),
            None,
        )
    )
    if core_sha is None:
        raise ValueError("ChaosEngine source tree has an unexpected layout")
    tree_shas = {"chaos-engine": core_sha}
    # Discovery must finish. A 504 here is a download failure, not a core-only tarball.
    _discover_pack_trees(root, opener, encoded_repository, tree_shas)
    try:
        entries = _prefix_tree(
            _read_git_tree(opener, encoded_repository, core_sha, recursive=True),
            "chaos-engine",
        )
        for rel, sha in tree_shas.items():
            if rel == "chaos-engine":
                continue
            entries.extend(
                _prefix_tree(
                    _read_git_tree(opener, encoded_repository, sha, recursive=True),
                    rel,
                )
            )
    except (UpstreamReadError, OSError, TimeoutError, urllib.error.URLError) as error:
        raise ResolvedTreeUnavailable(tree_shas) from error
    return entries, tree_shas


def _tarball_fallback_allowed(error: BaseException) -> bool:
    """Transient read failures can use the commit tarball. Integrity and tree-shape errors cannot."""
    if RATE_LIMIT_FAILURE in str(error):
        return False
    return isinstance(error, (UpstreamReadError, OSError, TimeoutError, urllib.error.URLError))


def source_tar_repo_path(name: str, *, root_layout: bool = False) -> PurePosixPath | None:
    """Repo-relative path to keep, or None. Keeps ``chaos-engine/**`` and ``*/ce-pack|ce-addons/**``.

    In a root layout every member is core and is re-keyed under ``chaos-engine/``.
    """
    if not isinstance(name, str) or not name or name.startswith(("/", "\\")) or "\\" in name:
        raise ValueError("ChaosEngine source tarball contains an unsafe path")
    parts = PurePosixPath(name).parts
    if not parts or any(part in {"", ".", ".."} for part in parts):
        raise ValueError("ChaosEngine source tarball contains an unsafe path")
    if root_layout:
        if len(parts) < 2:
            return None
        return PurePosixPath(NESTED_PREFIX, *parts[1:])
    if len(parts) < 3:
        return None
    repo = PurePosixPath(*parts[1:])
    if repo.parts[0] == "chaos-engine" or is_pack_path(repo):
        return repo
    return None


def _pack_root(path: PurePosixPath) -> str:
    return f"{path.parts[0]}/{path.parts[1]}"


def _accept_tarball_prefix(name: str, prefix: str | None) -> str:
    member_prefix = PurePosixPath(name).parts[0]
    if prefix is None:
        return member_prefix
    if member_prefix != prefix:
        raise ValueError("ChaosEngine source tarball has an unexpected layout")
    return prefix


def _regular_tar_member(member: tarfile.TarInfo) -> bool:
    return bool(member.isfile() and not member.issym() and not member.islnk())


def _keep_source_member(
    repo_path: PurePosixPath,
    expected: list[tuple[PurePosixPath, int, str]] | None,
    expected_by_repo: dict[PurePosixPath, tuple[int, str]] | None,
    identities: dict[str, str],
) -> bool:
    if repo_path.parts[0] == "chaos-engine":
        return True
    listed = expected_by_repo is not None and repo_path in expected_by_repo
    identified = expected is None and _pack_root(repo_path) in identities
    return listed or identified


def _read_tar_member(archive: tarfile.TarFile, member: tarfile.TarInfo) -> tuple[bytes, bool]:
    size = member.size
    if not isinstance(size, int) or size < 0 or size > MAX_FILE_BYTES:
        raise ValueError("ChaosEngine source file exceeds the download limit")
    extracted = archive.extractfile(member)
    if extracted is None:
        raise ValueError("ChaosEngine source tarball is invalid")
    content = extracted.read(MAX_FILE_BYTES + 1)
    if len(content) != size:
        raise ValueError("ChaosEngine source file does not match the resolved tree")
    return content, bool(member.mode & 0o111)


def _store_source_member(
    repo_path: PurePosixPath,
    content: bytes,
    file_executable: bool,
    core_files: dict[str, tuple[bytes, bool]],
    pack_files: dict[str, dict[str, tuple[bytes, bool]]],
) -> bool:
    """Store one kept member. Return whether it counts toward the install limit."""
    if repo_path.parts[0] == "chaos-engine":
        relative = PurePosixPath(*repo_path.parts[1:])
        if not relative.parts:
            raise ValueError("ChaosEngine source tarball has an unexpected layout")
        key = relative.as_posix()
        if key in core_files:
            raise ValueError("ChaosEngine source tarball has an unexpected layout")
        core_files[key] = (content, file_executable)
        return not omitted_source_relative(relative)
    root_key = _pack_root(repo_path)
    relative_key = PurePosixPath(*repo_path.parts[2:]).as_posix()
    bucket = pack_files.setdefault(root_key, {})
    if relative_key in bucket:
        raise ValueError("ChaosEngine source tarball has an unexpected layout")
    bucket[relative_key] = (content, file_executable)
    return True


def _collect_tarball_files(
    archive: tarfile.TarFile,
    *,
    expected: list[tuple[PurePosixPath, int, str]] | None,
    expected_by_repo: dict[PurePosixPath, tuple[int, str]] | None,
    identities: dict[str, str],
    root_layout: bool = False,
) -> tuple[dict[str, tuple[bytes, bool]], dict[str, dict[str, tuple[bytes, bool]]]]:
    core_files: dict[str, tuple[bytes, bool]] = {}
    pack_files: dict[str, dict[str, tuple[bytes, bool]]] = {}
    total = 0
    kept = 0
    prefix: str | None = None
    inspected = 0
    for member in archive:
        inspected += 1
        if inspected > MAX_TARBALL_MEMBERS:
            raise ValueError("ChaosEngine source tarball contains too many files")
        repo_path = source_tar_repo_path(member.name, root_layout=root_layout)
        if repo_path is None:
            continue
        prefix = _accept_tarball_prefix(member.name, prefix)
        if not _regular_tar_member(member):
            continue
        if not _keep_source_member(repo_path, expected, expected_by_repo, identities):
            continue
        # In-limit omitted members still have to be read: the fallback tree oid includes them.
        # An omitted member over MAX_FILE_BYTES is dropped here, before that read raises.
        if repo_path.parts[0] == "chaos-engine":
            relative = PurePosixPath(*repo_path.parts[1:])
            size = member.size
            if (
                relative.parts
                and omitted_source_relative(relative)
                and (not isinstance(size, int) or size < 0 or size > MAX_FILE_BYTES)
            ):
                continue
        content, file_executable = _read_tar_member(archive, member)
        if not _store_source_member(repo_path, content, file_executable, core_files, pack_files):
            continue
        total += len(content)
        kept += 1
        if total > MAX_SOURCE_BYTES or kept > MAX_FILES:
            raise ValueError("ChaosEngine source tree exceeds the download limit")
    return core_files, pack_files


def extract_chaos_engine_tarball(
    payload: bytes,
    destination: Path,
    *,
    expected: list[tuple[PurePosixPath, int, str]] | None,
    executable: set[PurePosixPath] | None,
    tree_shas: dict[str, str] | None = None,
    root_layout: bool = False,
) -> Path:
    """Write the core and shipped packs from a commit tarball.

    Blob SHAs are checked when the listing produced ``expected``. Otherwise the
    archive must reproduce every resolved tree SHA (core, ce-pack, ce-addons),
    including files the install itself omits. Bytes that lack either check are
    not written.
    """
    identities = tree_shas or {}
    if expected is None and "chaos-engine" not in identities:
        raise ValueError("ChaosEngine source tarball cannot be verified")
    try:
        archive = tarfile.open(fileobj=io.BytesIO(payload), mode="r:gz")  # nosec B202 - members are filtered, never extractall
    except (tarfile.TarError, EOFError, OSError) as error:
        raise ValueError("ChaosEngine source tarball is invalid") from error
    expected_by_repo = {path: (size, sha) for path, size, sha in expected} if expected is not None else None
    try:
        core_files, pack_files = _collect_tarball_files(
            archive,
            expected=expected,
            expected_by_repo=expected_by_repo,
            identities=identities,
            root_layout=root_layout,
        )
    finally:
        archive.close()
    if expected_by_repo is not None:
        _verify_tarball_blobs(core_files, pack_files, expected_by_repo)
    else:
        _verify_tarball_trees(core_files, pack_files, identities)
    return _write_verified_tarball(
        destination,
        core_files,
        pack_files,
        expected=expected,
        executable=executable,
    )


def _verify_tarball_blobs(
    core_files: dict[str, tuple[bytes, bool]],
    pack_files: dict[str, dict[str, tuple[bytes, bool]]],
    expected_by_repo: dict[PurePosixPath, tuple[int, str]],
) -> None:
    seen: set[PurePosixPath] = set()
    for key, (content, _executable) in core_files.items():
        relative = PurePosixPath(key)
        if omitted_source_relative(relative):
            continue
        repo_path = PurePosixPath("chaos-engine", *relative.parts)
        spec = expected_by_repo.get(repo_path)
        if spec is None or spec[0] != len(content) or git_blob_sha1(content).casefold() != spec[1].casefold():
            raise ValueError("ChaosEngine source tarball does not match the resolved tree")
        seen.add(repo_path)
    for root_key, files in pack_files.items():
        root = PurePosixPath(root_key)
        for key, (content, _executable) in files.items():
            repo_path = PurePosixPath(*root.parts, *PurePosixPath(key).parts)
            spec = expected_by_repo.get(repo_path)
            if spec is None or spec[0] != len(content) or git_blob_sha1(content).casefold() != spec[1].casefold():
                raise ValueError("ChaosEngine source tarball does not match the resolved tree")
            seen.add(repo_path)
    missing = [path.as_posix() for path in expected_by_repo if path not in seen]
    if missing:
        raise ValueError("ChaosEngine source tarball does not match the resolved tree")


def _verify_tarball_trees(
    core_files: dict[str, tuple[bytes, bool]],
    pack_files: dict[str, dict[str, tuple[bytes, bool]]],
    tree_shas: dict[str, str],
) -> None:
    core_sha = tree_shas.get("chaos-engine")
    if not isinstance(core_sha, str) or source_directory_tree_sha(core_files).casefold() != core_sha.casefold():
        raise ValueError("ChaosEngine source tarball does not match the resolved tree")
    for key, sha in tree_shas.items():
        if key == "chaos-engine":
            continue
        files = pack_files.get(key, {})
        if source_directory_tree_sha(files).casefold() != sha.casefold():
            raise ValueError("ChaosEngine source tarball does not match the resolved tree")


def _write_verified_tarball(
    destination: Path,
    core_files: dict[str, tuple[bytes, bool]],
    pack_files: dict[str, dict[str, tuple[bytes, bool]]],
    *,
    expected: list[tuple[PurePosixPath, int, str]] | None,
    executable: set[PurePosixPath] | None,
) -> Path:
    source = destination / "chaos-engine"
    source.mkdir()
    for key, (content, file_executable) in core_files.items():
        relative = PurePosixPath(key)
        if omitted_source_relative(relative):
            continue
        _write_verified_file(
            source.joinpath(*relative.parts),
            source,
            content,
            file_executable=file_executable,
            repo_path=PurePosixPath("chaos-engine", *relative.parts),
            expected=expected,
            executable=executable,
        )
    for root_key, files in pack_files.items():
        root = PurePosixPath(root_key)
        for key, (content, file_executable) in files.items():
            relative = PurePosixPath(key)
            repo_path = PurePosixPath(*root.parts, *relative.parts)
            _write_verified_file(
                destination.joinpath(*repo_path.parts),
                destination,
                content,
                file_executable=file_executable,
                repo_path=repo_path,
                expected=expected,
                executable=executable,
            )
    if not (source / "skills/chaos-engine/SKILL.md").is_file():
        raise ValueError("ChaosEngine source tree is incomplete")
    return source


def _write_verified_file(
    target: Path,
    parent: Path,
    content: bytes,
    *,
    file_executable: bool,
    repo_path: PurePosixPath,
    expected: list[tuple[PurePosixPath, int, str]] | None,
    executable: set[PurePosixPath] | None,
) -> None:
    if not _path_is_inside(target, parent):
        raise ValueError("ChaosEngine source tarball contains an unsafe path")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(content)
    if expected is not None:
        if executable is not None and repo_path in executable:
            mark_executable(target)
    elif file_executable:
        mark_executable(target)


def download_source_tarball(
    encoded_repository: str,
    commit: str,
    destination: Path,
    *,
    opener,
    reporter: InstallReporter | None,
    expected: list[tuple[PurePosixPath, int, str]] | None,
    executable: set[PurePosixPath] | None,
    tree_shas: dict[str, str] | None = None,
    root_layout: bool = False,
) -> Path:
    """Verified fallback: codeload tarball, then the GitHub tarball API."""
    if COMMIT.fullmatch(commit) is None:
        raise ValueError("GitHub returned an invalid ChaosEngine revision")
    if expected is None and (not tree_shas or "chaos-engine" not in tree_shas):
        raise ValueError("ChaosEngine source tarball cannot be verified")
    urls = (
        f"https://codeload.github.com/{encoded_repository}/tar.gz/{commit}",
        f"https://api.github.com/repos/{encoded_repository}/tarball/{commit}",
    )
    last: BaseException | None = None
    for url in urls:
        try:
            payload = read_response(opener, url, limit=MAX_TARBALL_BYTES, purpose="download")
        except (UpstreamReadError, OSError, TimeoutError, urllib.error.URLError, RuntimeError) as error:
            trace_upstream_failure(reporter, error)
            last = error
            continue
        return extract_chaos_engine_tarball(
            payload,
            destination,
            expected=expected,
            executable=executable,
            tree_shas=tree_shas,
            root_layout=root_layout,
        )
    if last is not None:
        raise last
    raise RuntimeError("unable to download ChaosEngine source tree (after 0 attempts): /")


def _clear_partial_source(destination: Path) -> None:
    """Drop a half-written core and any sibling pack trees in the download directory."""
    core = destination / "chaos-engine"
    if core.exists():
        shutil.rmtree(core, ignore_errors=True)
    if not destination.is_dir():
        return
    for child in list(destination.iterdir()):
        if not child.is_dir():
            continue
        for name in ("ce-pack", "ce-addons"):
            pack = child / name
            if pack.exists():
                shutil.rmtree(pack, ignore_errors=True)


def _manifest_file_digest(project: Path, relative: str) -> str | None:
    manifest_path = project / ".chaos-engine" / "manifest.json"
    try:
        document = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return None
    files = document.get("files") if isinstance(document, dict) else None
    digest = files.get(relative) if isinstance(files, dict) else None
    return digest if isinstance(digest, str) else None


def _reuse_selected_blob(
    project: Path | None, repository_path: PurePosixPath, expected_sha: str
) -> bytes | None:
    """Installed bytes or a blob-cache hit for this git oid. None means download."""
    cached = cached_git_blob(expected_sha)
    if cached is not None and git_blob_sha1(cached).casefold() == expected_sha.casefold():
        return cached
    if project is None or repository_path.parts[:1] != ("chaos-engine",):
        return None
    relative = PurePosixPath(*repository_path.parts[1:])
    if not relative.parts:
        return None
    installed = project / ".chaos-engine" / relative
    if installed.is_file() and not installed.is_symlink():
        raw = installed.read_bytes()
        if git_blob_sha1(raw).casefold() == expected_sha.casefold():
            return raw
    digest = _manifest_file_digest(project, relative.as_posix())
    if digest:
        blob = cached_blob(digest)
        if blob is not None and git_blob_sha1(blob).casefold() == expected_sha.casefold():
            return blob
    return None


def _write_selected_blobs(
    selected: list[tuple[PurePosixPath, int, str]],
    total: int,
    executable: set[PurePosixPath],
    *,
    encoded_repository: str,
    commit: str,
    destination: Path,
    opener,
    reporter: InstallReporter | None,
    root_layout: bool = False,
    project: Path | None = None,
) -> Path:
    if reporter is not None:
        reporter.begin_download(total, detail=f"{len(selected)} source files")
        reporter.trace(f"download {len(selected)} files ({total} bytes)")
    source = destination / "chaos-engine"
    source.mkdir()
    mkdir_lock = threading.Lock()

    def fetch_blob(item: tuple[PurePosixPath, int, str]) -> None:
        repository_path, expected_size, expected_sha = item
        content = _reuse_selected_blob(project, repository_path, expected_sha)
        if content is None:
            remote_path = remote_source_path(repository_path, root_layout=root_layout)
            encoded_path = "/".join(urllib.parse.quote(part, safe="") for part in remote_path.parts)
            content = read_response(
                opener,
                f"https://raw.githubusercontent.com/{encoded_repository}/{commit}/{encoded_path}",
                limit=MAX_FILE_BYTES,
                progress=None if reporter is None else reporter.downloaded,
                purpose="download",
            )
            store_git_blob(expected_sha, content)
            store_cached_blob(hashlib.sha256(content).hexdigest(), content)
        elif reporter is not None:
            reporter.downloaded(len(content))
        if len(content) != expected_size:
            raise ValueError("ChaosEngine source file does not match the resolved tree")
        actual_sha = git_blob_sha1(content)
        if actual_sha.casefold() != expected_sha.casefold():
            raise ValueError("ChaosEngine source file hash does not match the resolved tree")
        target = destination.joinpath(*repository_path.parts)
        with mkdir_lock:
            target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(content)
        if repository_path in executable:
            mark_executable(target)

    workers = max(1, min(DOWNLOAD_WORKERS, len(selected)))
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = [pool.submit(fetch_blob, item) for item in selected]
        for future in as_completed(futures):
            future.result()
    if not (source / "skills/chaos-engine/SKILL.md").is_file():
        raise ValueError("ChaosEngine source tree is incomplete")
    return source


def download_source_remote(
    repository: str,
    commit: str,
    destination: Path,
    *,
    opener=urllib.request.urlopen,
    reporter: InstallReporter | None = None,
    project: Path | None = None,
) -> Path:
    """Download the core and sibling packs. A tarball is used only when its bytes are bound to a resolved tree."""
    encoded_repository = "/".join(
        urllib.parse.quote(part, safe="") for part in repository.split("/")
    )
    tree_shas: dict[str, str] = {}
    expected: list[tuple[PurePosixPath, int, str]] | None = None
    executable: set[PurePosixPath] | None = None
    root_layout = False
    download_source_remote.last_root_layout = False  # type: ignore[attr-defined]
    try:
        try:
            tree, tree_shas, root_layout = fetch_chaos_engine_source(encoded_repository, commit, opener)
        except ResolvedTreeUnavailable as incomplete:
            tree_shas = incomplete.tree_shas
            root_layout = incomplete.root_layout
            cause = incomplete.__cause__
            if cause is None:
                raise
            raise cause
        selected, total, executable = _select_source_blobs(tree)
        if not selected:
            raise ValueError("ChaosEngine source tree has an unexpected layout")
        if len(selected) > MAX_FILES:
            raise ValueError("ChaosEngine source tree contains too many files")
        if total > MAX_SOURCE_BYTES:
            raise ValueError("ChaosEngine source tree exceeds the download limit")
        expected = selected
        download_source_remote.last_root_layout = root_layout  # type: ignore[attr-defined]
        return _write_selected_blobs(
            selected,
            total,
            executable,
            encoded_repository=encoded_repository,
            commit=commit,
            destination=destination,
            opener=opener,
            reporter=reporter,
            root_layout=root_layout,
            project=project,
        )
    except (RuntimeError, OSError, urllib.error.URLError, ValueError) as error:
        if not _tarball_fallback_allowed(error):
            raise
        if expected is None and "chaos-engine" not in tree_shas:
            raise
        trace_upstream_failure(reporter, error)
        if reporter is not None:
            reporter.trace("download falling back to source tarball")
        download_source_remote.last_root_layout = root_layout  # type: ignore[attr-defined]
        _clear_partial_source(destination)
        try:
            return download_source_tarball(
                encoded_repository,
                commit,
                destination,
                opener=opener,
                reporter=reporter,
                expected=expected,
                executable=executable,
                tree_shas=tree_shas if expected is None else None,
                root_layout=root_layout,
            )
        except (RuntimeError, OSError, urllib.error.URLError, ValueError):
            _clear_partial_source(destination)
            raise


def load_installer(source: Path):
    path = source / "install.py"
    return types.SimpleNamespace(**runpy.run_path(str(path)))


def resolve_distribution(installer, project: Path, source: Path, requested: str | None) -> str:
    if isinstance(requested, str) and requested.strip():
        return requested.strip()
    detect = getattr(installer, "detect_distribution", None)
    if callable(detect):
        guessed = detect(project, source)
        if isinstance(guessed, str) and guessed.strip():
            return guessed.strip()
    return "portable"


def _walk_upstream(error: BaseException):
    current: BaseException | None = error
    seen: set[int] = set()
    while current is not None and id(current) not in seen and len(seen) < 8:
        seen.add(id(current))
        yield current
        current = current.__cause__ or current.__context__


def upstream_url_path(error: BaseException) -> str | None:
    """First recorded URL path on this failure. Path only; no query, userinfo, or local path."""
    for item in _walk_upstream(error):
        path = getattr(item, "url_path", None)
        if isinstance(path, str) and path.startswith("/") and ".." not in path.split("/"):
            return path[:400]
    return None


def upstream_http_status(error: BaseException) -> int | None:
    for item in _walk_upstream(error):
        status = getattr(item, "http_status", None)
        if isinstance(status, int):
            return status
    return None


def trace_upstream_failure(reporter: InstallReporter | None, error: BaseException) -> None:
    if reporter is None:
        return
    path = upstream_url_path(error)
    if path is None:
        return
    message = f"upstream failed path={path}"
    if any(item[1] == message for item in reporter.traces):
        return
    reporter.trace(message)


def _failure_before_install_core(reporter: InstallReporter) -> bool:
    if reporter.current_operation == "Install core":
        return False
    if "Install core" in reporter.completed_operations or "Install core" in reporter._in_flight:
        return False
    return True


def _defer_installed_upgrade(
    prior_install: bool, reporter: InstallReporter, error: BaseException
) -> bool:
    """A transient resolve/download failure must not hard-fail a core that is already installed."""
    if not prior_install or isinstance(error, (KeyboardInterrupt, SystemExit, InstallCancelled)):
        return False
    return _failure_before_install_core(reporter)


def _redact_report_value(value: object, root: Path | None = None) -> object:
    if isinstance(value, str):
        return redact(value, root=root)
    if isinstance(value, dict):
        return {
            str(key): _redact_report_value(item, root=root) for key, item in value.items()
        }
    if isinstance(value, (list, tuple)):
        return [_redact_report_value(item, root=root) for item in value]
    return value


def _redact_obj(value: object, root: Path | None = None) -> object:
    return _redact_report_value(value, root=root)


def _bounded_doctor(doctor: dict) -> dict[str, object]:
    wrapped = RuntimeError("doctor")
    wrapped.doctor = doctor  # type: ignore[attr-defined]
    report = doctor_failure_payload(wrapped)
    redacted = _redact_report_value(report)
    return redacted if isinstance(redacted, dict) else {}


def existing_core_doctor(project: Path) -> dict[str, object]:
    """Run the installed core's doctor. A doctor failure leaves that core in place."""
    commit = installed_core_commit(project)
    fallback: dict[str, object] = {"status": "unknown", "commit": commit, "components": {}}
    run = installed_core_doctor(project / ".chaos-engine")
    if not callable(run):
        return fallback
    try:
        document = run(project, verify_clients=False)
    except Exception:
        return fallback
    if not isinstance(document, dict):
        return fallback
    report = _bounded_doctor(document)
    if not isinstance(report.get("commit"), str):
        report["commit"] = commit
    if not isinstance(report.get("components"), dict):
        report["components"] = {}
    if not isinstance(report.get("status"), str) or not report.get("status"):
        report["status"] = "unknown"
    return report


def emit_upgrade_deferred(
    reporter: InstallReporter, report: dict[str, object], error: BaseException
) -> None:
    commit = report.get("commit") if isinstance(report.get("commit"), str) else None
    status = report.get("status") if isinstance(report.get("status"), str) else "unknown"
    components = report.get("components") if isinstance(report.get("components"), dict) else {}
    names = ", ".join(sorted(str(name) for name in components)) or "none"
    http_status = upstream_http_status(error)
    reason = f"GitHub returned HTTP {http_status}" if http_status is not None else "the upgrade could not be downloaded"
    subject = f"ChaosEngine {commit}" if commit else "ChaosEngine"
    if status == "healthy" and commit:
        state = f"Your installed {subject} is unchanged and working."
    else:
        state = f"Your installed {subject} is unchanged."
    reporter.stream.write(
        "\n".join(
            (
                "CE-UPGRADE-DEFERRED",
                state,
                f"{reason}. Rerun the installer later.",
                f"Doctor status {status}; commit {commit or 'unknown'}; components {names}.",
                "",
            )
        )
    )
    reporter.stream.flush()
    reporter.trace("upgrade deferred CE-UPGRADE-DEFERRED")


def installed_upgrade_deferred(
    project: Path, reporter: InstallReporter, error: BaseException
) -> dict[str, object]:
    report = existing_core_doctor(project)
    emit_upgrade_deferred(reporter, report, error)
    commit = report.get("commit") if isinstance(report.get("commit"), str) else None
    return {
        "status": "upgrade-skipped",
        "error": "CE-UPGRADE-DEFERRED",
        "cause": one_line_cause(error),
        "commit": commit,
        "components": report.get("components") if isinstance(report.get("components"), dict) else {},
        "doctor": report,
        "root": ".chaos-engine",
    }


def _open_install_terminal(interactive: bool, terminal_factory):
    try:
        terminal_context = terminal_factory() if interactive else None
        if terminal_context is not None:
            return terminal_context, terminal_context.__enter__()
        return None, None
    except OSError as error:
        raise RuntimeError("interactive mode requires a usable controlling terminal") from error


def _install_operations(skip_tools: bool, with_maven_tools: bool) -> list[str]:
    operations = ["Resolve source", "Download source", "Install core"]
    if not skip_tools:
        operations.extend(("Provision dependencies", "Verify installation", "Activate clients"))
    if with_maven_tools:
        operations.insert(-2, "Install Maven Tools")
    return operations


def _finish_host_completion(installer, project: Path, targets, *, already_wired: bool) -> None:
    """Keep PATH shims from a locked install. A selected set replaces that wiring."""
    if targets is None:
        clear = getattr(installer, "clear_completion_targets", None)
        if already_wired and callable(clear):
            clear(project)
        return
    if already_wired:
        unwire = getattr(installer, "unwire_receipt_shims", None)
        if callable(unwire):
            unwire(project)
    apply = getattr(installer, "apply_install_host_completion", None)
    if callable(apply):
        apply(project, targets)


def _prepare_shaft_addons(
    project: Path,
    source: Path,
    opener,
    *,
    requested: set[str] | None,
    removed: set[str] | None,
) -> None:
    """Version-pinned SHAFT skills. Empty projects do not touch the network."""
    import importlib.util

    candidates = (
        Path(source) / "packs" / "shaft" / "sync.py",
        Path(__file__).resolve().parent / "packs" / "shaft" / "sync.py",
        project / ".chaos-engine" / "packs" / "shaft" / "sync.py",
    )
    module_path = next((item for item in candidates if item.is_file()), None)
    if module_path is None:
        return
    spec = importlib.util.spec_from_file_location("ce_shaft_sync", module_path)
    if spec is None or spec.loader is None:
        return
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module.prepare(
        project,
        source,
        opener,
        requested=set(requested or ()),
        removed=set(removed or ()),
    )


def _run_core_install(
    project: Path,
    scratch: dict,
    *,
    repository: str,
    branch: str | None,
    skip_tools: bool,
    with_maven_tools: bool,
    maven_tools_mode: str,
    distribution: str | None,
    opener,
    provisioner,
    reporter: InstallReporter,
    bundle_options: dict[str, bool] | None,
    addons_requested: set[str] | None,
    addons_removed: set[str] | None,
    confirm,
    remaining,
    completion_targets: tuple[str, ...] | None = None,
) -> tuple[Path, str, object]:
    confirm("Resolve source")
    reporter.start("Resolve source", remaining=remaining("Resolve source"))
    commit, resolved_branch = resolve_latest(repository, branch, opener=opener)
    note_commit = getattr(reporter, "note_commit", None)
    if callable(note_commit):
        note_commit(commit)
    reporter.complete("Resolve source", remaining=remaining("Resolve source"))
    scratch["temporary"] = tempfile.TemporaryDirectory(
        prefix="chaos-engine-bootstrap-", dir=disjoint_download_parent(project)
    )
    temporary = scratch["temporary"]
    confirm("Download source")
    reporter.start("Download source", remaining=remaining("Download source"))
    source = download_source(
        repository,
        commit,
        Path(temporary.name),
        opener=opener,
        reporter=reporter,
        project=project,
    )
    root_layout = bool(getattr(download_source, "last_root_layout", False))
    _prepare_shaft_addons(
        project,
        source,
        opener,
        requested=addons_requested,
        removed=addons_removed,
    )
    source_url = source_tree_url(repository, commit, root_layout=root_layout)
    reporter.detail = source_url
    if os.environ.get("CHAOS_ENGINE_QUIET") != "1":
        version = product_version()
        print(
            f"{repository} {version} {commit} -> {project}",
            file=sys.stderr,
        )
        print(source_url, file=sys.stderr)
    if os.environ.get("CHAOS_ENGINE_DRY_RUN") == "1":
        raise DryRunDone(list(getattr(download_source, "last_actions", [])), commit)
    # Remote manifest sync already refuses before download. A local-clone
    # fallback never sees that manifest, so compare the installed tree here
    # and exit 3 before Install core replaces the edited files.
    if os.environ.get("CHAOS_ENGINE_KEEP_EDITS") == "1":
        drifted = verify_named_paths(project / ".chaos-engine")
        if drifted:
            raise SyncKeepEdits(drifted)
    reporter.complete("Download source", remaining=remaining("Download source"))
    installer = load_installer(source)
    addons: tuple[str, ...] = ()
    plan = getattr(installer, "plan_install", None)
    planned = plan(project, source, addons_requested or set(), addons_removed or set()) if callable(plan) else None
    if isinstance(planned, tuple) and len(planned) == 2 and isinstance(planned[0], str):
        distribution = distribution or planned[0]
        addons = tuple(planned[1])
        if addons:
            download_addon_files(
                repository, commit, Path(temporary.name), source, addons, opener=opener, reporter=reporter
            )
    elif addons_requested or addons_removed:
        raise ValueError("this ChaosEngine revision does not support optional add-ons")
    distribution = resolve_distribution(installer, project, source, distribution)
    addon_options = {"addons": addons} if addons else {}
    if distribution == "portable":
        provenance = {
            "kind": "git-digest",
            "repositorySha256": hashlib.sha256(repository.casefold().encode()).hexdigest(),
            "branchSha256": hashlib.sha256(resolved_branch.encode()).hexdigest(),
            "commit": commit,
        }
    else:
        provenance = {
            "kind": "git",
            "repository": repository,
            "branch": resolved_branch,
            "commit": commit,
        }
    legacy_layout = getattr(installer, "legacy_profile_layout", None)
    legacy_packs = legacy_layout(project / ".chaos-engine") if callable(legacy_layout) else []
    confirm("Install core")
    reporter.start("Install core", remaining=remaining("Install core"))
    reporter.trace(f"install core commit={commit} distribution={distribution}")
    if skip_tools:
        target = installer.install(
            project, source, commit, source_record=provenance, distribution=distribution,
            **addon_options,
        )
        reporter.complete("Install core", remaining=remaining("Install core"))
        # Tool provisioning is skipped. Host adapters still bind so doctor can
        # see a receipt for the core that just installed.
        hosts_py = runtime_module(Path(target), "hosts.py")
        if hosts_py.is_file() and not hosts_py.is_symlink():
            host_controller = installer.load_installed_controller(Path(target), "hosts")
            manifest = json.loads((Path(target) / "manifest.json").read_text(encoding="utf-8"))
            digest = manifest.get("capabilityPolicySha256")
            host_controller.install(
                project,
                core_commit=commit,
                capability_policy_digest=digest if isinstance(digest, str) else None,
            )
        mark = getattr(installer, "mark_tools_skipped", None)
        if callable(mark):
            mark(target)
    else:
        # Core and provision are sequential: install_with_dependencies completes
        # "Install core" then starts "Provision dependencies" before deps work.
        confirm("Provision dependencies")
        if with_maven_tools:
            confirm("Install Maven Tools")
        target = installer.install_with_dependencies(
            project,
            source,
            commit,
            provisioner=provisioner,
            source_record=provenance,
            distribution=distribution,
            with_maven_tools=with_maven_tools,
            maven_tools_mode=maven_tools_mode,
            reporter=reporter,
            confirmer=confirm,
            bundle_options=bundle_options,
            **addon_options,
        )
        _complete_dependency_steps(reporter, remaining, with_maven_tools=with_maven_tools)
    _finish_host_completion(installer, project, completion_targets, already_wired=not skip_tools)
    suggest = getattr(installer, "suggest_addons", None)
    tips = suggest(project, source, addons) if callable(suggest) else []
    if tips:
        print(installer.addon_tip(tips), file=sys.stderr)
    if legacy_packs:
        # CE-10 hard cut: name the replaced profiles/<name> layout once.
        replaced = not legacy_layout(project / ".chaos-engine")
        print(installer.hard_cut_message(legacy_packs, replaced=replaced), file=sys.stderr)
    return target, commit, installer


def _complete_dependency_steps(reporter: InstallReporter, remaining, *, with_maven_tools: bool) -> None:
    if with_maven_tools and "Install Maven Tools" in getattr(reporter, "_in_flight", ()):
        reporter.complete("Install Maven Tools", remaining=remaining("Install Maven Tools"))
    if "Provision dependencies" in getattr(reporter, "_in_flight", ()) or (
        reporter.current_operation == "Provision dependencies"
    ):
        reporter.complete(
            "Provision dependencies",
            remaining=remaining("Provision dependencies"),
        )
    if "Install core" in getattr(reporter, "_in_flight", ()) or (
        reporter.current_operation == "Install core"
    ):
        reporter.complete("Install core", remaining=remaining("Install core"))


def _publish_heal_handoff(
    project: Path,
    *,
    repository: str,
    commit: str,
    target: Path,
    installer,
    host_controller,
    reporter: InstallReporter,
    remaining,
    confirm,
    interactive: bool,
    terminal_context,
    doctor: dict,
    health_error: BaseException,
    completion_targets: tuple[str, ...] | None = None,
) -> dict[str, object]:
    reporter.complete("Verify installation", remaining=remaining("Verify installation"))
    try:
        confirm("Activate clients")
        reporter.start("Activate clients", remaining=remaining("Activate clients"))
        clients = _activate_resolved_clients(
            installer, host_controller, project, completion_targets, confirm, interactive=interactive
        )
        reporter.complete("Activate clients", remaining=())
    except Exception:
        clients = {"clients": {}}
    prefix = installer_cli_prefix(project) or "python3 .chaos-engine/install.py"
    fields = installer_issue_fields(
        "CE-INSTALL-FAILED",
        health_error,
        reporter,
        project,
        f"{prefix} status --project . --json",
        f"{prefix} doctor --project . --json",
    )
    issue_url = publish_installer_issue(repository, "CE-INSTALL-FAILED", fields, root=project)
    write_heal_handoff(project, fields, issue_url)
    doctor["clients"] = clients.get("clients", {})
    if terminal_context is not None:
        terminal_context.__exit__(None, None, None)
    reporter.success(
        project,
        doctor,
        doctor["clients"],
        repository=repository,
        include_heal_handoff=True,
    )
    reporter.close()
    return {
        "status": "heal-handoff",
        "root": str(target),
        "commit": commit,
        "clients": clients,
        "doctor": doctor,
        "issueUrl": issue_url,
    }


def _rollback_failed_verify(
    project: Path,
    error: BaseException,
    *,
    prior_install: bool,
    installer,
    commit: str,
    terminal_context,
) -> None:
    if isinstance(error, InstallHealthError) and prior_install:
        error.observed_upgrade_commit = error.observed_commit
        error.observed_upgrade_components = error.observed_components
        error.observed_upgrade_component_details = error.observed_component_details
    if not isinstance(error, (KeyboardInterrupt, InstallCancelled)):
        _rollback_replaced_core(project, error, prior_install=prior_install, installer=installer, commit=commit)
    if terminal_context is not None:
        terminal_context.__exit__(*sys.exc_info())
    raise


def _rollback_replaced_core(
    project: Path,
    error: BaseException,
    *,
    prior_install: bool,
    installer,
    commit: str,
) -> None:
    backup = project / ".chaos-engine.backup"
    keep_core = False
    if prior_install and backup.exists():
        probe = getattr(installer, "account_rollback_has_exact_prior_host_receipt", None)
        if callable(probe):
            try:
                keep_core = probe(project) is False
            except (OSError, ValueError):
                # A probe failure must not replace the verify error.
                keep_core = True
    if prior_install and backup.exists() and not keep_core:
        _swap_back_previous_core(project, error, installer=installer, commit=commit)


def _swap_back_previous_core(project: Path, error: BaseException, *, installer, commit: str) -> None:
    core_marker = project / ".chaos-engine" / "install.py"
    core_before = _regular_file_bytes(core_marker)
    try:
        installer.rollback(project)
    except ValueError as rollback_error:
        # A missing receipt raised before any swap keeps the new core.
        # A swap that already replaced the core must stay visible.
        core_unchanged = core_before is not None and _regular_file_bytes(core_marker) == core_before
        if not (_inexact_prior_rollback(rollback_error) and core_unchanged):
            raise
    else:
        # #6338: say which core is installed after the rollback.
        restored = installed_core_commit(project)
        if restored is not None:
            error.rolled_back_to = restored  # type: ignore[attr-defined]
            error.rolled_back_from = commit  # type: ignore[attr-defined]
            record_install_rollback(project, commit, restored)


def _activate_resolved_clients(installer, host_controller, project: Path, targets, confirm, *, interactive: bool):
    """Today's activation when unattended; selected Claude/Codex only when targets are set."""
    if targets is None:
        if interactive:
            return host_controller.activate_detected_plugins(project, confirmer=confirm)
        return host_controller.activate_detected_plugins(project)
    activate = getattr(installer, "activate_completion_targets", None)
    if not callable(activate):
        return {"clients": {}}
    return activate(
        project,
        targets,
        host_controller=host_controller,
        confirmer=confirm if interactive else None,
    )


def _verify_and_activate(
    project: Path,
    *,
    repository: str,
    commit: str,
    target: Path,
    installer,
    reporter: InstallReporter,
    remaining,
    confirm,
    interactive: bool,
    prior_install: bool,
    terminal_context,
    completion_targets: tuple[str, ...] | None = None,
) -> dict[str, object]:
    host_controller = installer.load_installed_controller(target, "hosts")
    try:
        reporter.start("Verify installation", remaining=remaining("Verify installation"))
        migrate = getattr(host_controller, "migrate_legacy_memory_store", None)
        if callable(migrate):
            migrate(project)
        doctor = verify_gate_doctor(installer, target, project)
        if _required_install_unhealthy(doctor):
            health_error = InstallHealthError("Verify installation", doctor)
            if not prior_install and core_install_py(project):
                return _publish_heal_handoff(
                    project,
                    repository=repository,
                    commit=commit,
                    target=target,
                    installer=installer,
                    host_controller=host_controller,
                    reporter=reporter,
                    remaining=remaining,
                    confirm=confirm,
                    interactive=interactive,
                    terminal_context=terminal_context,
                    doctor=doctor,
                    health_error=health_error,
                    completion_targets=completion_targets,
                )
            raise health_error
        reporter.complete("Verify installation", remaining=remaining("Verify installation"))
        confirm("Activate clients")
        reporter.start("Activate clients", remaining=remaining("Activate clients"))
        clients = _activate_resolved_clients(
            installer, host_controller, project, completion_targets, confirm, interactive=interactive
        )
        reporter.complete("Activate clients", remaining=())
        doctor = final_install_doctor(target, project, doctor)
        doctor["clients"] = clients.get("clients", {})
    except BaseException as error:
        reporter.close()
        _rollback_failed_verify(
            project,
            error,
            prior_install=prior_install,
            installer=installer,
            commit=commit,
            terminal_context=terminal_context,
        )
    if terminal_context is not None:
        terminal_context.__exit__(None, None, None)
    reporter.success(project, doctor, doctor["clients"], repository=repository)
    reporter.close()
    return {
        "status": "installed",
        "root": str(target),
        "commit": commit,
        "clients": clients,
        "doctor": doctor,
    }


def lift_consumer_project(project: Path) -> Path:
    """Return the given project directory. The installer does not climb to a parent.

    Standalone curl|bash file: same rule as install.py, without importing it.
    """
    return Path(project).resolve()


def install_latest(
    project: Path,
    *,
    repository: str,
    branch: str | None = None,
    skip_tools: bool = False,
    with_maven_tools: bool = False,
    maven_tools_mode: str = "native",
    distribution: str | None = None,
    opener=urllib.request.urlopen,
    provisioner=None,
    interactive: bool = False,
    reporter: InstallReporter | None = None,
    terminal_factory=interactive_terminal,
    bundle_options: dict[str, bool] | None = None,
    addons_requested: set[str] | None = None,
    addons_removed: set[str] | None = None,
    hosts: str | None = None,
) -> dict[str, object]:
    if skip_tools and with_maven_tools:
        raise ValueError("--with-maven-tools cannot be combined with --skip-tools")
    resolution = resolve_install_hosts(explicit=hosts)
    project = lift_consumer_project(Path(project))
    if not project.is_dir():
        raise ValueError(f"project is not a directory: {project}")
    with_maven_tools = wants_maven_tools(
        project, skip_tools=skip_tools, requested=with_maven_tools
    )
    reporter = reporter or InstallReporter()
    reporter.announce(project, repository, branch or "default")
    terminal_context, terminal_input = _open_install_terminal(interactive, terminal_factory)
    if terminal_input is not None:
        completion_targets = run_first_run_wizard(
            project=project,
            repository=repository,
            with_maven_tools=with_maven_tools,
            input_stream=terminal_input,
            output=reporter.stream,
            ask_clients=not resolution.hosts,
            resolved_hosts=resolution.hosts,
        )
    else:
        completion_targets = resolution.hosts or None

    def confirm(name: str) -> None:
        if terminal_input is not None:
            confirm_operation(name, input_stream=terminal_input, output=reporter.stream)

    operations = _install_operations(skip_tools, with_maven_tools)
    remaining = lambda name: tuple(operations[operations.index(name) + 1 :])
    prior_install = (project / ".chaos-engine").exists()
    scratch: dict = {"temporary": None}
    try:
        target, commit, installer = _run_core_install(
            project,
            scratch,
            repository=repository,
            branch=branch,
            skip_tools=skip_tools,
            with_maven_tools=with_maven_tools,
            maven_tools_mode=maven_tools_mode,
            distribution=distribution,
            opener=opener,
            provisioner=provisioner,
            reporter=reporter,
            bundle_options=bundle_options,
            addons_requested=addons_requested,
            addons_removed=addons_removed,
            confirm=confirm,
            remaining=remaining,
            completion_targets=completion_targets,
        )
        scratch["temporary"].cleanup()
    except DryRunDone as done:
        if scratch["temporary"] is not None:
            scratch["temporary"].cleanup()
        if terminal_context is not None:
            terminal_context.__exit__(None, None, None)
        reporter.close()
        summary = format_sync_counts(done.actions)
        if os.environ.get("CHAOS_ENGINE_QUIET") != "1":
            print(summary, file=sys.stderr)
        return {
            "status": "dry-run",
            "commit": done.commit,
            "root": str(project / ".chaos-engine"),
            "summary": summary,
            "sync": sync_counts(done.actions),
        }
    except BaseException as error:
        trace_upstream_failure(reporter, error)
        defer = _defer_installed_upgrade(prior_install, reporter, error)
        reporter.close()
        if scratch["temporary"] is not None:
            scratch["temporary"].cleanup()
        if terminal_context is not None:
            terminal_context.__exit__(*sys.exc_info())
        if defer:
            return installed_upgrade_deferred(project, reporter, error)
        raise
    if skip_tools or provisioner is not None:
        if terminal_context is not None:
            terminal_context.__exit__(None, None, None)
        reporter.close()
        return {"status": "installed", "root": str(target), "commit": commit}
    return _verify_and_activate(
        project,
        repository=repository,
        commit=commit,
        target=target,
        installer=installer,
        reporter=reporter,
        remaining=remaining,
        confirm=confirm,
        interactive=interactive,
        prior_install=prior_install,
        terminal_context=terminal_context,
        completion_targets=completion_targets,
    )


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description=__doc__)
    result.add_argument("--project", type=Path, default=Path.cwd())
    result.add_argument("--repository", required=True, type=normalize_repository)
    result.add_argument("--branch")
    result.add_argument("--distribution")
    result.add_argument("--skip-tools", action="store_true", help=argparse.SUPPRESS)
    result.add_argument("--with-maven-tools", action="store_true")
    result.add_argument(
        "--skip-pack-post-install",
        action="store_true",
        help="do not run the selected project pack's postInstall installer",
    )
    result.add_argument(
        "--consumer",
        action="store_true",
        help="consumer-repository mode: keep the overlay out of git status via .git/info/exclude",
    )
    result.add_argument(
        "--maven-tools-mode", choices=("native", "docker"), default="native"
    )
    for bundle_name in (
        "memory",
        "mempalace",
        "graphify",
        "ponytail",
        "caveman",
    ):
        result.add_argument(
            f"--without-{bundle_name}",
            action="store_true",
            help=f"Disable default-on {bundle_name} (Memory/MemPalace/Graphify/Ponytail/Caveman).",
        )
    result.add_argument(
        "--lean-grok-skills",
        action="store_true",
        default=False,
        help=(
            "Recommended for ChaosEngine: disable Grok bundled game-* and imagine "
            "skills via ~/.grok/config.toml (or CHAOS_ENGINE_LEAN_GROK_SKILLS=1)."
        ),
    )
    result.epilog = (
        "Optional add-ons stay opt-in (--with-<addon> / --without-<addon>, or "
        "CHAOS_ENGINE_ADDONS=a,b). The one-liner reidentifies a project pack: "
        "the pack home gets that distribution, a matching project gets its user "
        "skills, and every other project stays portable. "
        "Uninstall remains: python3 .chaos-engine/install.py uninstall --project ."
    )
    result.add_argument("--interactive", action="store_true")
    result.add_argument(
        "--hosts",
        action="append",
        default=None,
        help="Client ids to complete (comma-separated). Also CHAOS_ENGINE_HOST.",
    )
    result.add_argument(
        "--verbose",
        action="store_true",
        help="Stream every trace line (same as CHAOS_ENGINE_VERBOSE=1).",
    )
    result.add_argument("-n", "--dry-run", action="store_true", help="Print the plan and write nothing.")
    result.add_argument(
        "--yes",
        "--no-input",
        action="store_true",
        dest="no_input",
        help="Do not prompt. CI=1 and a non-interactive stdin imply this.",
    )
    result.add_argument("-q", "--quiet", action="store_true", help="Errors only.")
    result.add_argument("--json", action="store_true", help="One JSON document on stdout.")
    result.add_argument("--no-color", action="store_true", help="Disable ANSI color. In-place redraw stays on a TTY.")
    result.add_argument(
        "--color",
        choices=("auto", "always", "never"),
        default=None,
        help="Colour mode. NO_COLOR and --no-color win over always. Also CHAOS_ENGINE_COLOR.",
    )
    result.add_argument("--ascii", action="store_true", help="Force ASCII glyphs (CHAOS_ENGINE_ASCII=1).")
    result.add_argument("--no-hyperlinks", action="store_true", help="Do not emit OSC 8 hyperlinks.")
    result.add_argument(
        "--version",
        dest="version_pin",
        help="Release 0.4.YYYYMMDD.N or a 40-hex commit. Also CHAOS_ENGINE_VERSION.",
    )
    result.add_argument(
        "--no-modify-path",
        action="store_true",
        help="Do not change the user Path (Windows).",
    )
    result.add_argument(
        "--keep-edits",
        action="store_true",
        help="Exit 3 when an owned file was edited, before publishing.",
    )
    result.add_argument("--offline", action="store_true", help="Use only the cache or --from-bundle.")
    result.add_argument("--force", action="store_true", help="Replace edited files without copying them.")
    result.add_argument("--from-bundle", type=Path, default=None)
    result.add_argument("--shaft-skills-version", default=None)
    result.add_argument("--no-auto-addons", action="store_true")
    return result


def installer_help_url(repository: str) -> str:
    owner = repository.partition("/")[0].casefold()
    return f"https://{owner}.github.io/docs/agentic/chaos-engine#installer-errors"


def installer_user_guide_url(repository: str) -> str:
    owner = repository.partition("/")[0].casefold()
    return f"https://{owner}.github.io/docs/agentic/chaos-engine"


def installer_cli_prefix(project: Path | None = None) -> str | None:
    root = Path(project) if project is not None else Path.cwd()
    cli = root / ".chaos-engine" / "install.py"
    if not cli.is_file():
        return None
    command = "py -3" if os.name == "nt" else "python3"
    return f"{command} .chaos-engine/install.py"


def failed_install_result(error: BaseException) -> dict[str, str]:
    """Failure payload. ``cause`` is the child reason, not only the error code."""
    return {
        "status": "failed",
        "error": classify_install_error(error),
        "cause": one_line_cause(error),
    }


def _plugin_list_timeout(error: BaseException) -> bool:
    """True when ``plugin list --available --json`` is still running past its wait."""
    if not isinstance(error, subprocess.TimeoutExpired):
        return False
    command = error.cmd if isinstance(error.cmd, (list, tuple)) else str(error.cmd).split()
    return {"plugin", "list", "--available", "--json"} <= {str(part) for part in command}


def classify_install_error(error: BaseException) -> str:
    if isinstance(error, (KeyboardInterrupt, InstallCancelled)):
        return "CE-INSTALL-CANCELLED"
    # A still-running plugin list is not a failed install (#7826). The upgrade
    # path swallows it; this keeps a bubbled timeout out of CE-INSTALL-FAILED.
    if _plugin_list_timeout(error):
        return "CE-INSTALL-PLUGIN-LIST-RUNNING"
    detail = str(error)
    if "Claude marketplace collision" in detail or "Claude plugin collision" in detail:
        return "CE-CLAUDE-MARKETPLACE-CONFLICT"
    if "interactive mode requires" in detail:
        return "CE-INTERACTIVE-TERMINAL"
    if "checksum" in detail:
        return "CE-INSTALL-CHECKSUM"
    if "unsupported platform" in detail:
        return "CE-INSTALL-UNSUPPORTED-PLATFORM"
    if "entrypoint probe failed" in detail:
        return "CE-INSTALL-PROBE-FAILED"
    if RATE_LIMIT_FAILURE in detail:
        return "CE-GITHUB-RATE-LIMIT"
    return "CE-INSTALL-FAILED"


def one_line_cause(error: BaseException) -> str:
    text = str(error).strip() or error.__class__.__name__
    cause = getattr(error, "__cause__", None)
    if isinstance(cause, BaseException):
        extra = str(cause).strip() or cause.__class__.__name__
        if extra and extra not in text:
            text = f"{text} | cause: {extra}"
    if isinstance(error, FileNotFoundError) or getattr(error, "winerror", None) == 2:
        missing = None
        if getattr(error, "filename", None):
            missing = Path(str(error.filename)).name
        elif error.args:
            missing = str(error.args[-1])
        if missing and "dependency launcher not found" not in text:
            text = (
                f"dependency launcher not found: {missing} "
                f"(WinError 2 / file not found). fix-next: install `{missing}` on PATH "
                f"then rerun the ChaosEngine install one-liner"
            )
    text = " ".join(text.split())
    try:
        return redact(text)
    except Exception:
        return _REDACTION_FAILED


def installer_issue_fields(
    code: str,
    error: BaseException,
    reporter: InstallReporter | None,
    project: Path | None,
    status_command: str,
    doctor_command: str,
) -> dict[str, str]:
    """Build every installer issue-form field from local, redacted evidence."""
    runtime = runtime_environment()
    payload = doctor_failure_payload(error)
    doctor_details = "not reported"
    if payload.get("components"):
        labels: list[str] = []
        components = payload["components"]
        if isinstance(components, dict):
            for name, item in components.items():
                if not isinstance(item, dict):
                    continue
                mark = item.get("code") or item.get("detail") or item.get("status")
                if isinstance(mark, str):
                    labels.append(f"{name}:{mark}")
        if labels:
            doctor_details = _bounded_evidence(",".join(labels), 8000)
    hosts_receipt = "unknown"
    core_dir = "unknown"
    install_py = "unknown"
    install_trace = "not available"
    install_trace_snippet = ""
    console_log = ""
    doctor_json = ""
    if project is not None:
        try:
            root = Path(project).resolve()
            hosts_receipt = (
                "present" if (root / ".chaos-engine-hosts.json").is_file() else "absent"
            )
            core_dir = "present" if (root / ".chaos-engine").is_dir() else "absent"
            install_py = (
                "present" if (root / ".chaos-engine" / "install.py").is_file() else "absent"
            )
            trace = install_trace_path(root)
            if trace.is_file():
                install_trace = ".chaos-engine-state/install-trace.json"
                raw = redact_report_text(trace.read_text(encoding="utf-8"), root=root)
                install_trace_snippet = _bounded_evidence(raw, 40000)
            console_rel, doctor_rel = write_failure_artifacts(root, reporter, error)
            console_path = root / console_rel
            if console_path.is_file():
                console_log = redact_report_text(console_path.read_text(encoding="utf-8"), root=root)
            if doctor_rel != "not available":
                doctor_path = root / doctor_rel
                if doctor_path.is_file():
                    doctor_json = redact_report_text(
                        doctor_path.read_text(encoding="utf-8"), root=root
                    )
        except OSError:
            # Keep default field values when install artifacts cannot be read.
            pass
    return {
        "error_code": code,
        "cause": _bounded_evidence(one_line_cause(error), 4000),
        "failed_phase": getattr(error, "phase", None)
        or (reporter.current_operation if reporter else "unknown")
        or "unknown",
        "unhealthy": ", ".join(getattr(error, "unhealthy", ())) or "not reported",
        "platform": sys.platform,
        "os_name": runtime["os_name"] or "unknown",
        "os_version": runtime["os_version"] or "unknown",
        "architecture": runtime["architecture"] or "unknown",
        "python_version": runtime["python_version"] or "unknown",
        "machine": runtime["machine"] or "unknown",
        "doctor_details": doctor_details or "not reported",
        "hosts_receipt": hosts_receipt,
        "core_dir": core_dir,
        "install_py": install_py,
        "install_trace": install_trace,
        "install_trace_snippet": install_trace_snippet,
        "console_log": console_log,
        "doctor_json": doctor_json,
        "status_command": status_command,
        "doctor_command": doctor_command,
        "additional": "\n".join(
            part
            for part in (
                "Auto-filled by the ChaosEngine installer.",
                "The redacted trace, console log, and doctor JSON are in this issue.",
                json.dumps(
                    telemetry_allowlist(
                        {
                            **_telemetry_facts(),
                            "failing_step": str(
                                getattr(error, "phase", None)
                                or (reporter.current_operation if reporter else "")
                                or ""
                            )[:80],
                            "doctor_code": (
                                doctor_details if doctor_details != "not reported" else ""
                            ),
                            "commit": (
                                payload.get("commit")
                                if isinstance(payload.get("commit"), str)
                                and re.fullmatch(r"[0-9a-fA-F]{40}", payload.get("commit", ""))
                                else ""
                            ),
                            "trace_tail": "\n".join(
                                str(message)[:200]
                                for _ended, message in (
                                    reporter.traces[-15:] if reporter is not None else []
                                )
                            ),
                        }
                    ),
                    sort_keys=True,
                ),
                install_rollback_summary(error),
                _exception_chain(error),
                _ssl_report_facts(error),
            )
            if part
        ),
    }


def publish_installer_issue(
    repository: str,
    code: str,
    fields: dict[str, str],
    *,
    opener=urllib.request.urlopen,
    token: str | None = None,
    extra: dict[str, str] | None = None,
    root: Path | None = None,
) -> str:
    title = f"[ChaosEngine installer] {code}"
    repository = normalize_repository(repository)
    resolved = resolve_issue_token(token)
    if resolved:
        created = create_installer_github_issue(
            repository,
            title,
            issue_form_markdown(fields, root=root),
            resolved,
            opener=opener,
        )
        if created:
            return created
    return encode_issue_form_url(repository, title, fields, extra=extra, root=root)


def _process_text(value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode("utf-8", "replace")
    return str(value)


def _graphify_uv_install_timeout(error: BaseException) -> bool:
    """True when ``uv`` was installing graphifyy and the wait expired.

    Prepared, Installed, Downloading, or empty output still means the process
    was killed while work was in progress. That is not a network outage.
    ``TimeoutExpired`` keeps the captured text off ``str(error)``.
    """
    if not isinstance(error, subprocess.TimeoutExpired):
        return False
    command = error.cmd
    text = command if isinstance(command, str) else " ".join(str(part) for part in command)
    folded = text.casefold()
    return "graphifyy" in folded and "uv" in folded and "install" in folded


def _still_unpacking_account_timeout(error: BaseException) -> bool:
    """True when a graphify account command timed out while work was still running.

    A graphifyy ``uv`` install that times out is over budget even when the
    captured text says Prepared, Installed, or Downloading, and when the
    output is empty because the process was killed while still running.
    Other graphify timeouts still need unpacking or wheel output.
    ``TimeoutExpired`` keeps the still-running output off ``str(error)``.
    """
    if _graphify_uv_install_timeout(error):
        return True
    chunks: list[str] = []
    if isinstance(error, subprocess.TimeoutExpired):
        command = error.cmd
        chunks.append(
            command if isinstance(command, str) else " ".join(str(part) for part in command)
        )
        chunks.append(_process_text(error.output))
        chunks.append(_process_text(getattr(error, "stderr", None)))
    else:
        chunks.append(str(error))
        for attr in ("output", "stdout", "stderr", "full_output"):
            chunks.append(_process_text(getattr(error, attr, None)))
    blob = "\n".join(chunks).casefold()
    if "graphifyy" not in blob:
        return False
    if "unpack" not in blob and "wheel" not in blob:
        return False
    if isinstance(error, subprocess.TimeoutExpired):
        return True
    return "exceeded its budget" in blob and "still in progress" in blob


def next_fix_hint(code: str, error: BaseException, prefix: str | None) -> str:
    """Return exactly one actionable fix-next for every failure (#6325)."""
    cause = one_line_cause(error).casefold()
    rerun = "then rerun the same install one-liner."
    if _still_unpacking_account_timeout(error):
        return (
            "the command exceeded its budget while work was still in progress; "
            f"retry when the machine is less busy, {rerun}"
        )
    rules = (
        (
            isinstance(error, InstallHealthError) or "doctor did not report" in cause,
            "paste the heal prompt below into any supported host in this folder.",
        ),
        (
            code == "CE-GITHUB-RATE-LIMIT",
            'export GITHUB_TOKEN="$(gh auth token)" (or GH_TOKEN, or run '
            f"`gh auth login`), {rerun}",
        ),
        (
            "java_home" in cause
            or "environment variable is needed" in cause
            or "mvn path unresolved" in cause
            or "auto-provision" in cause
            or ("jdk" in cause and "javac" in cause and "fix-next" in cause),
            (
                "ChaosEngine already tried to auto-provision JDK/mvn/JAVA_HOME/PATH; "
                "open the prefilled issue link and launch your agent with the printed "
                "prompt so it can fix the install locally. "
                + ASK_BEFORE_UPSTREAM
            ),
        ),
        (
            "maven tools" in cause
            and any(token in cause for token in ("checksum", "crc", "receipt validation")),
            f"run `{prefix or 'python3 .chaos-engine/install.py'} repair --project . "
            "--component maven-tools-mcp` (discards the corrupt cached JAR, then reuses "
            "a healthy version or reinstalls), then rerun doctor.",
        ),
        ("checksum" in cause, f"check network/proxy interference, {rerun}"),
        (
            "timed out" in cause or "temporary failure" in cause or "network" in cause,
            f"restore network connectivity, {rerun}",
        ),
        (
            "python" in cause and ("not found" in cause or "required" in cause),
            "install Python 3 (or leave it absent so the wrapper bootstraps uv), "
            + rerun,
        ),
        (
            "core is missing" in cause or "ce_core_missing" in cause,
            "rerun the same install one-liner so ChaosEngine can restore "
            ".chaos-engine under the existing host receipt (or uninstall, then install).",
        ),
        (
            "no download found" in cause,
            "the requested runtime is not downloadable yet; update ChaosEngine "
            f"(newer releases fall back to the newest downloadable patch), {rerun}",
        ),
    )
    for matched, hint in rules:
        if matched:
            return hint
    if prefix:
        return f"run `{prefix} doctor --project .` and follow each fix-next, {rerun}"
    return (
        "the issue below already contains the redacted trace, console log, "
        f"and doctor JSON, {rerun}"
    )


def terminal_issue_link(issue_url: str, *, saved: bool, live: bool) -> str:
    """Keep a multi-kilobyte prefilled URL off an interactive screen (#6325)."""
    if not live or not saved or len(issue_url) <= 300:
        return issue_url
    label = issue_url.split("?", 1)[0] + " (prefilled installer report)"
    return (
        f"\x1b]8;;{issue_url}\x1b\\{label}\x1b]8;;\x1b\\\n"
        f"Full URL: {HEAL_HANDOFF_RELATIVE}"
    )


def emit_install_failure(
    code: str,
    error: BaseException,
    repository: str,
    reporter: InstallReporter | None = None,
    project: Path | None = None,
    opener=urllib.request.urlopen,
    token: str | None = None,
) -> str | None:
    """Print only three user-facing items (L94); details go to heal-handoff/issue."""
    unicode = stream_supports_unicode(sys.stderr)
    color = (
        reporter.color_enabled
        if reporter is not None
        else terminal_color_enabled(tty=stream_is_tty(sys.stderr))
    )
    prefix = installer_cli_prefix(project)
    status_command = f"{prefix} status --project . --json" if prefix else "not available"
    doctor_command = f"{prefix} doctor --project . --json" if prefix else "not available"
    print(file=sys.stderr)
    print(
        "  "
        + _report_style(status_glyph("fail", unicode=unicode), "31", enabled=color)
        + " "
        + _report_style("Installation failed", "31", enabled=color),
        file=sys.stderr,
    )
    print(file=sys.stderr)
    if code == "CE-INSTALL-CANCELLED":
        # Cancellation is not a defect report; keep the short resume hint only.
        print("Installation interrupted. Last verified generation was kept.", file=sys.stderr)
        print("Rerun the same install command to continue.", file=sys.stderr)
        if os.environ.get("CHAOS_ENGINE_DEBUG") == "1":
            traceback.print_exc()
        return None
    fields = installer_issue_fields(
        code,
        error,
        reporter,
        project,
        status_command,
        doctor_command,
    )
    fields["fix_next"] = next_fix_hint(code, error, prefix)
    issue_url = publish_installer_issue(
        repository,
        code,
        fields,
        opener=opener,
        token=token,
        extra=upgrade_query_extras(error),
        root=project,
    )
    if project is not None and core_install_py(project):
        write_heal_handoff(project, fields, issue_url)
    artifacts = present_state_artifacts(project) if project is not None else []
    prompt = heal_handoff_prompt(
        fields["doctor_command"], issue_url, artifacts=artifacts
    )
    # (2) prefilled GitHub issue link (diagnostics live in the URL / handoff)
    if "issues/new?" in issue_url:
        print("Open issue:", file=sys.stderr)
    else:
        print("GitHub issue:", file=sys.stderr)
    print(
        terminal_issue_link(
            issue_url,
            saved=project is not None and core_install_py(project),
            live=(
                stream_is_tty(sys.stderr)
                and hyperlinks_allowed()
                and select_mode(tty=stream_is_tty(sys.stderr)) == "tty"
            ),
        ),
        file=sys.stderr,
    )
    print(file=sys.stderr)
    # (3) copy-paste agent prompt
    print("Launch your agent with this prompt:", file=sys.stderr)
    print(f"`{prompt}`", file=sys.stderr)
    if os.environ.get("CHAOS_ENGINE_DEBUG") == "1":
        traceback.print_exc()
    return issue_url


def _post_install_entry(profile: Path) -> dict | None:
    try:
        document = json.loads(profile.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return None
    if not isinstance(document, dict):
        return None
    value = document.get("postInstall")
    script = value.get("script") if isinstance(value, dict) else None
    arguments = value.get("args", []) if isinstance(value, dict) else []
    script_path = PurePosixPath(script) if isinstance(script, str) else None
    if not (
        isinstance(script, str)
        and script_path is not None
        and not script_path.is_absolute()
        and script_path.parts[:1] != ("/",)
        and re.fullmatch(r"[A-Za-z0-9_./-]+\.py", script)
        and ".." not in script.split("/")
        and isinstance(arguments, list)
        and all(isinstance(item, str) and item.startswith("--") for item in arguments)
    ):
        return None
    name = document.get("name") if isinstance(document.get("name"), str) else profile.parent.name
    repository = document.get("repository") if isinstance(document.get("repository"), str) else ""
    ref = document.get("defaultBranch") if isinstance(document.get("defaultBranch"), str) else ""
    return {"pack": name, "script": script, "args": arguments, "repository": repository, "ref": ref}


def pack_post_installs(project: Path) -> list[dict]:
    """``postInstall`` entries of the project packs the installer selected.

    The pack home distribution installs that pack, so its ``postInstall`` runs.
    A portable install does not include the pack. Optional add-ons have no
    ``postInstall``. A ShaftHQ/SHAFT_ENGINE checkout keeps the profile in its
    own ``shaft-skills/ce-pack`` tree, which is the source when the harness
    checkout is not nested beside that pack. That home profile is marked
    ``home`` and may only run a script already in the checkout.
    """
    profiles = [(path, False) for path in (project / ".chaos-engine" / "packs").glob("*/profile.json")]
    homes = [
        path
        for path in sorted(project.glob("*/ce-pack/profile.json"))
        if (path.parent / "entrypoint.md").is_file() and not path.is_symlink()
    ]
    if len(homes) == 1:
        profiles.append((homes[0], True))
    found = []
    seen: set[tuple[str, tuple[str, ...]]] = set()
    for profile, home in profiles:
        entry = _post_install_entry(profile)
        if entry is None:
            continue
        key = (entry["script"], tuple(entry["args"]))
        if key in seen:
            continue
        seen.add(key)
        entry["home"] = home
        found.append(entry)
    return found


def run_pack_post_install(
    project: Path,
    repository: str,
    commit: str,
    entry: dict,
    *,
    opener=urllib.request.urlopen,
    runner=subprocess.run,
) -> int:
    """Run the local pack installer, or a sealed script from this install commit."""
    relative = PurePosixPath(entry["script"])
    if relative.is_absolute() or ".." in relative.parts or not relative.parts or relative.parts[0] == "/":
        raise ValueError("CE-INSTALL-FAILED: pack postInstall script escapes the project")
    local = project.joinpath(*relative.parts)
    try:
        if not local.resolve().is_relative_to(project.resolve()):
            raise ValueError("CE-INSTALL-FAILED: pack postInstall script escapes the project")
    except OSError:
        pass
    if local.is_file() and not local.is_symlink():
        completed = runner(  # nosec B603 - fixed interpreter, project script, validated flag list.
            [sys.executable, str(local), *entry["args"]], cwd=project, check=False
        )
        return int(completed.returncode)
    if os.environ.get("CHAOS_ENGINE_OFFLINE") == "1":
        raise ValueError("CE-INSTALL-FAILED: offline pack postInstall has no local script")
    # A home profile is not sealed payload. Its repository and defaultBranch
    # must not choose a URL. The script runs only when it is already local.
    if entry.get("home"):
        raise ValueError("CE-INSTALL-FAILED: pack postInstall has no local script")
    # Sealed pack payload downloads from this install's commit only.
    if COMMIT.fullmatch(str(commit)) is None:
        raise ValueError("CE-INSTALL-FAILED: pack postInstall ref is invalid")
    encoded_repository = "/".join(urllib.parse.quote(part, safe="") for part in str(repository).split("/"))
    encoded_ref = urllib.parse.quote(str(commit), safe="")
    content = read_response(
        opener,
        f"https://raw.githubusercontent.com/{encoded_repository}/{encoded_ref}/{entry['script']}",
        purpose="download",
    )
    with tempfile.TemporaryDirectory(prefix="ce-pack-post-install-") as temporary:
        script = Path(temporary) / Path(entry["script"]).name
        script.write_bytes(content)
        completed = runner(  # nosec B603 - fixed interpreter, pinned-commit script, validated flag list.
            [sys.executable, str(script), *entry["args"]], cwd=project, check=False
        )
    return int(completed.returncode)


def _run_framework_offers(project: Path) -> None:
    """Offer add-on agentic installers after the core is in place.

    ``--skip-tools`` skips dependency provisioning only. The consumer offer
    still runs, and it defaults to No in CI and without a TTY.
    """
    path = runtime_module(project / ".chaos-engine", "prerequisites.py")
    if not path.is_file() or path.is_symlink():
        return
    import importlib.util

    spec = importlib.util.spec_from_file_location("ce_prerequisites_offer", path)
    if spec is None or spec.loader is None:
        return
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    runner = getattr(module, "run", None)
    if not callable(runner):
        return
    try:
        runner(project, install_ok=True)
    except Exception as error:  # noqa: BLE001 - the offer never fails the core install.
        print(f"ChaosEngine prerequisite offer failed: {error}", file=sys.stderr)


def post_install_packs(args, result: dict) -> int:
    project = Path(args.project).resolve()
    commit = str(result.get("commit") or args.branch or "main")
    worst = 0
    for entry in pack_post_installs(project):
        if args.skip_pack_post_install:
            print(f"Skipped {entry['pack']} pack postInstall (--skip-pack-post-install).", file=sys.stderr)
            continue
        print(f"Running {entry['pack']} pack postInstall: {entry['script']}", file=sys.stderr)
        try:
            code = run_pack_post_install(project, args.repository, commit, entry)
        except (OSError, ValueError, urllib.error.URLError, RuntimeError) as error:
            code = 1
            print(f"{entry['pack']} pack postInstall could not start: {error}", file=sys.stderr)
        result.setdefault("packPostInstall", {})[entry["pack"]] = code
        if code:
            print(f"{entry['pack']} pack postInstall failed (exit {code}); ChaosEngine itself is installed. "
                  f"Rerun the installer, or run {entry['script']} {' '.join(entry['args'])}.", file=sys.stderr)
        worst = worst or code
    return worst


MINIMUM_PYTHON = (3, 11)


def python_floor_message(version: tuple[int, ...] | None = None) -> str:
    """What is missing, why, and the one fix (#7766)."""
    found = ".".join(str(part) for part in (version or sys.version_info)[:3])
    return (
        f"ChaosEngine requires Python {MINIMUM_PYTHON[0]}.{MINIMUM_PYTHON[1]} or newer; found {found}. "
        "Hooks and the installer refuse an older interpreter. "
        "Rerun the install one-liner, which provisions a supported Python through uv before any prompt.\n"
    )


def _run_bundled_install(args) -> int:
    """Install from a verified bundle without a blob download."""
    import zipfile

    bundle = Path(args.from_bundle)
    with zipfile.ZipFile(bundle) as archive:
        raw = archive.read("install.py")
    work = Path(tempfile.mkdtemp(prefix="ce-bundle-installer-"))
    script = work / "install.py"
    script.write_bytes(raw)
    argv = [
        str(script),
        "install",
        "--from-bundle",
        str(bundle),
        "--project",
        str(args.project),
        "--skip-tools",
    ]
    old = sys.argv
    try:
        sys.argv = argv
        runpy.run_path(str(script), run_name="__main__")
    except SystemExit as error:
        code = error.code
        return int(code) if isinstance(code, int) else (0 if code is None else 1)
    finally:
        sys.argv = old
    return 0


def apply_install_flags(args) -> dict[str, str | None]:
    """Copy one-liner flags into the environment the download plan already reads."""
    previous: dict[str, str | None] = {}

    def assign(key: str, value: str | None) -> None:
        if key not in previous:
            previous[key] = os.environ.get(key)
        if value is None:
            os.environ.pop(key, None)
        else:
            os.environ[key] = value

    if getattr(args, "quiet", False):
        assign("CHAOS_ENGINE_QUIET", "1")
    color = getattr(args, "color", None)
    if getattr(args, "no_color", False) or color == "never":
        assign("NO_COLOR", "1")
        assign("CHAOS_ENGINE_COLOR", "never")
    elif color == "always":
        assign("CHAOS_ENGINE_COLOR", "always")
    elif color == "auto":
        assign("CHAOS_ENGINE_COLOR", "auto")
    if getattr(args, "ascii", False):
        assign("CHAOS_ENGINE_ASCII", "1")
    if getattr(args, "no_hyperlinks", False):
        assign("CHAOS_ENGINE_HYPERLINKS", "0")
    if getattr(args, "dry_run", False):
        assign("CHAOS_ENGINE_DRY_RUN", "1")
    if getattr(args, "keep_edits", False):
        assign("CHAOS_ENGINE_KEEP_EDITS", "1")
    if getattr(args, "offline", False):
        assign("CHAOS_ENGINE_OFFLINE", "1")
    if getattr(args, "force", False):
        assign("CHAOS_ENGINE_FORCE", "1")
    if getattr(args, "no_input", False) or os.environ.get("CI") == "1":
        assign("CHAOS_ENGINE_NO_INPUT", "1")
    if getattr(args, "json", False):
        assign("CHAOS_ENGINE_JSON", "1")
    if getattr(args, "no_auto_addons", False):
        assign("CHAOS_ENGINE_NO_AUTO_ADDONS", "1")
    skills = getattr(args, "shaft_skills_version", None)
    if isinstance(skills, str) and skills.strip():
        assign("CHAOS_ENGINE_SHAFT_SKILLS_VERSION", skills.strip())
    return previous


def restore_install_flags(previous: dict[str, str | None]) -> None:
    for key, value in previous.items():
        if value is None:
            os.environ.pop(key, None)
        else:
            os.environ[key] = value


def resolve_version_pin(repository: str, pin: str | None, opener) -> str | None:
    """A release pin checks ``.sha256`` before any blob download. A 40-hex pin is the commit."""
    chosen = (pin or os.environ.get("CHAOS_ENGINE_VERSION") or "").strip()
    if not chosen:
        return None
    if COMMIT.fullmatch(chosen):
        return chosen
    if RELEASE_VERSION.fullmatch(chosen):
        document = verify_release_manifest(repository, chosen, opener)
        commit = str(document.get("commit") or "")
        if COMMIT.fullmatch(commit) is None:
            raise ValueError("CE-INSTALL-FAILED: release manifest commit is invalid")
        return commit
    raise ValueError("version must be 0.4.YYYYMMDD.N or a 40-hex commit")


def utf8_text_stream(stream) -> None:
    """cp1252 pipes encode U+2192 as ANSI unless the stream is UTF-8 first."""
    reconfigure = getattr(stream, "reconfigure", None)
    if callable(reconfigure):
        try:
            reconfigure(encoding="utf-8")
        except (AttributeError, OSError, ValueError):
            pass


def main() -> int:
    utf8_text_stream(sys.stdout)
    harden_stream_encoding(sys.stderr)
    if sys.version_info < MINIMUM_PYTHON:
        sys.stderr.write(python_floor_message())
        return 2
    if os.environ.get("CHAOS_ENGINE_ARGV_ONLY") == "1":
        print(json.dumps(sys.argv[1:]))
        return 0
    args, extra = parser().parse_known_args()
    addons_requested, addons_removed, unknown = split_addon_flags(extra)
    if unknown:
        parser().parse_args()  # argparse reports the unrecognized arguments and exits
    if (
        args.interactive
        and not args.no_input
        and os.environ.get("CI") != "1"
        and not sys.stdin.isatty()
    ):
        print("a prompt is required. fix-next: pass --yes or --no-input", file=sys.stderr)
        return 2
    flag_env = apply_install_flags(args)
    post_install_code = 0
    reporter = InstallReporter()
    if getattr(args, "verbose", False):
        reporter.enable_verbose()
    if getattr(args, "consumer", False):
        os.environ["CHAOS_ENGINE_CONSUMER"] = "1"
    try:
        args.project = lift_consumer_project(Path(args.project))
        if args.from_bundle is not None:
            return _run_bundled_install(args)
        pinned = resolve_version_pin(args.repository, args.version_pin, urllib.request.urlopen)
        if pinned:
            args.branch = pinned
        bundle_options = {
            name: not getattr(args, f"without_{name}", False)
            for name in (
                "memory",
                "mempalace",
                "graphify",
                "ponytail",
                "caveman",
            )
        }
        result = install_latest(
            args.project,
            repository=args.repository,
            branch=args.branch,
            skip_tools=args.skip_tools or os.environ.get("CHAOS_ENGINE_SKIP_TOOLS") == "1",
            with_maven_tools=args.with_maven_tools,
            maven_tools_mode=args.maven_tools_mode,
            distribution=args.distribution,
            interactive=args.interactive and os.environ.get("CHAOS_ENGINE_NO_INPUT") != "1",
            reporter=reporter,
            bundle_options=bundle_options,
            addons_requested=addons_requested,
            addons_removed=addons_removed,
            hosts=",".join(args.hosts) if args.hosts else None,
        )
        # A dry-run prints the plan and leaves the project untouched.
        if not (isinstance(result, dict) and result.get("status") == "dry-run"):
            write_install_trace(Path(args.project).resolve(), result, reporter.traces)
            record_install_source(Path(args.project).resolve(), args.repository, args.branch)
        if isinstance(result, dict) and result.get("status") not in {"upgrade-skipped", "dry-run"}:
            post_install_code = post_install_packs(args, result)
            _run_framework_offers(Path(args.project).resolve())
    except SyncKeepEdits as error:
        reporter.close()
        for path in error.paths:
            print(path, file=sys.stderr)
        print("fix-next: review those files, then rerun without --keep-edits", file=sys.stderr)
        print(f"log: {(Path(args.project) / '.chaos-engine-state' / 'logs').as_posix()}/", file=sys.stderr)
        return 3
    except BaseException as error:
        if isinstance(error, SystemExit):
            raise
        reporter.fail()
        reporter.close()
        code = classify_install_error(error)
        write_install_trace(
            Path(args.project).resolve(),
            failed_install_result(error),
            reporter.traces,
        )
        emit_install_failure(
            code,
            error,
            args.repository,
            reporter=reporter,
            project=Path(args.project).resolve(),
        )
        print(f"log: {(Path(args.project) / '.chaos-engine-state' / 'logs').as_posix()}/", file=sys.stderr)
        return 1
    finally:
        restore_install_flags(flag_env)
    reporter.close()
    if isinstance(result, dict):
        actions = list(getattr(download_source, "last_actions", []) or [])
        if actions and "summary" not in result:
            result = dict(result)
            result["summary"] = format_sync_counts(actions)
            result["sync"] = sync_counts(actions)
    isatty = getattr(sys.stdout, "isatty", None)
    stdout_tty = bool(isatty()) if callable(isatty) else True
    json_mode = bool(args.json) or os.environ.get("CHAOS_ENGINE_JSON") == "1"
    quiet_mode = bool(args.quiet) or os.environ.get("CHAOS_ENGINE_QUIET") == "1"
    want_json = json_mode or not stdout_tty
    if want_json:
        print(json.dumps(result, sort_keys=True))
    elif not quiet_mode:
        print("Next:", file=sys.stderr)
        print("  1. open a host and invoke `/chaos-engine`", file=sys.stderr)
        print("  2. doctor anytime", file=sys.stderr)
    return 1 if post_install_code else 0


if __name__ == "__main__":
    raise SystemExit(main())
