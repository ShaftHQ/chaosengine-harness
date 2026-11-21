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


# Cybernetic Red #FF3B4D. The mark's core only, and only on a truecolor terminal.
CYBERNETIC_RED = "\x1b[38;2;255;59;77m"
_COLOR_ROLES = {"ok": "32", "warn": "33", "fail": "31", "accent": "36"}


def paint(value: str, role: str, *, color: bool, intensity: bool = False) -> str:
    """Paint one semantic role. Prose stays the terminal's default foreground.

    ``dim`` and ``bold`` are intensity, so ``NO_COLOR`` keeps them. Colour roles
    use the terminal's own ANSI palette. Fixed RGB does not belong here.
    """
    if role in {"", "plain", "value"}:
        return value
    if role == "dim":
        if not intensity and not color:
            return value
        return f"\x1b[2m{value}\x1b[0m"
    if role == "bold":
        if not intensity and not color:
            return value
        return f"\x1b[1m{value}\x1b[0m"
    if not color:
        return value
    code = _COLOR_ROLES.get(role)
    if code is None:
        return value
    return f"\x1b[{code}m{value}\x1b[0m"


def paint_core(glyph: str, *, truecolor: bool) -> str:
    """Colour the mark's core. Armor and every other glyph stay unpainted."""
    if not truecolor:
        return glyph
    return f"{CYBERNETIC_RED}{glyph}\x1b[0m"


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


