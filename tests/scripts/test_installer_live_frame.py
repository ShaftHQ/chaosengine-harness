"""Live installer frame: one header, no ghost row, hidden cursor, stable badges (#154).

Also the Python 3.14 ``return``-in-``finally`` ban and the certificate fix-next (#143).
"""

from __future__ import annotations

import ast
import importlib.util
import io
import os
import pty
import re
import select
import signal
import subprocess
import sys
import textwrap
import time
import unittest.mock
from pathlib import Path

import pytest

from vt_screen import Screen


ROOT = Path(__file__).resolve().parents[2]
GOLDEN = ROOT / "tests" / "scripts" / "golden" / "installer-frame"
OPS = (
    "Resolve source",
    "Download source",
    "Install core",
    "Provision dependencies",
    "Verify installation",
    "Activate clients",
)
COMMIT = "ab" * 20
LONG_URL = "https://example.invalid/chaos-engine/" + ("a" * 240)
NOTE = "injected-provision-note"
CURSOR_MODE = re.compile(r"\x1b\[\?25([lh])")
COLOR_SGR = re.compile(r"\x1b\[([0-9;]*)m")
WIDTHS = (60, 80, 120, 200)


def load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise ImportError(path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


BOOTSTRAP = load("ce_bootstrap_live_frame", ROOT / "bootstrap.py")
UI = load("ce_ui_live_frame", ROOT / "runtime" / "ce_ui.py")
MARK = load("ce_brand_mark_live_frame", ROOT / "scripts" / "ci" / "render_brand_mark.py")


class _Tty(io.StringIO):
    encoding = "utf-8"

    def isatty(self) -> bool:
        return True


class _EncodedTty(_Tty):
    def __init__(self, encoding: str) -> None:
        super().__init__()
        self.encoding = encoding


def _env(width: int, **extra: str) -> dict[str, str]:
    env = {
        "PATH": "/tmp/ce-frame-empty",
        "HOME": "/tmp/ce-frame-home",
        "TERM": "xterm-256color",
        "COLUMNS": str(width),
        "LINES": "48",
        "LANG": "C.UTF-8",
        "LC_ALL": "C.UTF-8",
    }
    env.update(extra)
    return env


def _remaining(current: str) -> tuple[str, ...]:
    index = OPS.index(current)
    return OPS[index + 1 :]


def _screen(stream: io.StringIO, columns: int) -> str:
    screen = Screen(columns)
    screen.feed(stream.getvalue())
    return screen.text()


def _header_lines(screen: str) -> list[str]:
    version = BOOTSTRAP.product_version()
    needle = f"ChaosEngine {version}"
    return [line for line in screen.splitlines() if needle in line]


def _assert_frame(screen: str, columns: int) -> None:
    assert len(_header_lines(screen)) == 1, screen
    for name in OPS:
        count = sum(name in line for line in screen.splitlines())
        assert count == 1, f"{name} appeared {count} times\n{screen}"
    for line in screen.splitlines():
        assert len(line) <= columns - 1, (len(line), columns, line)
    for line in screen.splitlines():
        if "Elapsed" in line:
            assert line.startswith("      └─") or line.startswith("      +-"), line


def _label_column(screen: str, name: str) -> int:
    for line in screen.splitlines():
        index = line.find(name)
        if index >= 0:
            return index
    raise AssertionError(f"{name} missing\n{screen}")


def _play(width: int, *, environ: dict[str, str] | None = None, stream=None):
    """Drive the six-step sequence. Returns shots taken before close."""
    env = environ or _env(width)
    tty = stream or _Tty()
    shots: list[tuple[str, str]] = []

    def shot(name: str) -> None:
        shots.append((name, _screen(tty, int(env["COLUMNS"]))))

    with unittest.mock.patch.dict(os.environ, env, clear=True), unittest.mock.patch.object(
        BOOTSTRAP.threading.Thread, "start", lambda self: None
    ), unittest.mock.patch("sys.stderr", tty):
        reporter = BOOTSTRAP.InstallReporter(stream=tty, clock=lambda: 1_700_000_000.0, environ=env)
        try:
            shots = _drive(reporter, tty, shots, shot, width)
        finally:
            reporter.close()
        return shots, tty.getvalue()


def _drive(reporter, tty, shots, shot, width):
    reporter.announce(Path("/tmp/ce-frame-project"), "ShaftHQ/chaosengine-harness", "main")
    reporter.start("Resolve source", remaining=_remaining("Resolve source"))
    shot("start")
    reporter.note_commit(COMMIT)
    shot("note-commit")
    reporter.complete("Resolve source", remaining=_remaining("Resolve source"))
    shot("complete-resolve")
    reporter.start("Download source", remaining=_remaining("Download source"))
    columns = []
    for frame in range(10):
        reporter._frame = frame
        reporter._render_locked()
        columns.append(_label_column(_screen(tty, width), "Download source"))
    assert len(set(columns)) == 1, columns
    done_column = _label_column(_screen(tty, width), "Resolve source")
    pending_column = _label_column(_screen(tty, width), "Activate clients")
    assert done_column == pending_column == columns[0]
    reporter.begin_download(4096, detail=LONG_URL)
    shot("begin-download")
    reporter.detail = LONG_URL + "/tree"
    reporter.trace("detail")
    shot("detail")
    reporter.complete("Download source", remaining=_remaining("Download source"))
    shot("complete-download")
    reporter.start("Install core", remaining=_remaining("Install core"))
    reporter.complete("Install core", remaining=_remaining("Install core"))
    shot("complete-core")
    reporter.start(
        "Provision dependencies",
        remaining=_remaining("Provision dependencies"),
        detail="provision detail",
    )
    shot("provision-detail")
    print(NOTE, file=sys.stderr)
    shot("stray-stderr")
    reporter.complete("Provision dependencies", remaining=_remaining("Provision dependencies"))
    shot("shrink")
    reporter.start("Verify installation", remaining=_remaining("Verify installation"))
    shot("grow")
    reporter.fail("download timed out")
    shot("fail")
    failed_column = _label_column(_screen(tty, width), "Verify installation")
    assert failed_column == columns[0]
    return shots


def _blob(shots: list[tuple[str, str]]) -> str:
    return "\n".join(f"===== {name}\n{screen}" for name, screen in shots)


@pytest.mark.parametrize("width", WIDTHS)
def test_live_frame_screen_after_each_transition(width: int) -> None:
    shots, text = _play(width)
    assert text.count("\x1b[?25l") == 1
    modes = CURSOR_MODE.findall(text)
    assert modes and modes[-1] == "h"
    assert "\x1b[J" in text
    for _name, screen in shots:
        _assert_frame(screen, width)
    stray = shots[[name for name, _screen in shots].index("stray-stderr")][1]
    assert stray.count(NOTE) == 1
    note_at = next(index for index, line in enumerate(stray.splitlines()) if NOTE in line)
    header_at = next(
        index for index, line in enumerate(stray.splitlines()) if line == _header_lines(stray)[0]
    )
    assert note_at < header_at
    wide = UI.BRAND_MARK_WIDE[0][0].rstrip()
    stack = UI.BRAND_MARK_STACK[0][0].rstrip()
    final = shots[-1][1]
    if width >= 84:
        assert any(line.startswith(wide) for line in final.splitlines())
        assert not any(line == stack for line in final.splitlines())
    else:
        assert any(line == stack or line.startswith(stack) for line in final.splitlines())
        assert not any(line.startswith(wide) for line in final.splitlines())
    path = GOLDEN / f"frame-w{width}.txt"
    blob = _blob(shots)
    if os.environ.get("UPDATE_FRAME_GOLDEN") == "1":
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(blob, encoding="utf-8", newline="\n")
        return
    assert path.is_file(), f"missing {path.name}"
    assert path.read_text(encoding="utf-8") == blob


def test_narrow_lang_c_and_ascii_use_one_line_identity() -> None:
    wide = UI.BRAND_MARK_WIDE[0][0]
    for extra, width in (
        ({}, 50),
        ({"LANG": "C", "LC_ALL": "C"}, 120),
        ({"CHAOS_ENGINE_ASCII": "1"}, 120),
    ):
        shots, text = _play(width, environ=_env(width, **extra))
        assert "\x1b[?25l" in text
        for _name, screen in shots:
            assert len(_header_lines(screen)) == 1
            assert "[ChaosEngine " in screen
            assert wide not in screen
            for line in screen.splitlines():
                assert len(line) <= width - 1


@pytest.mark.parametrize("kind", ["log", "pipe", "dumb", "json"])
def test_log_pipe_dumb_and_json_have_no_cursor_moves(kind: str) -> None:
    env = _env(80)
    if kind == "dumb":
        env["TERM"] = "dumb"
        stream: io.StringIO = _Tty()
    elif kind == "json":
        env["CHAOS_ENGINE_JSON"] = "1"
        stream = _Tty()
    else:
        stream = io.StringIO()
    with unittest.mock.patch.dict(os.environ, env, clear=True), unittest.mock.patch.object(
        BOOTSTRAP.threading.Thread, "start", lambda self: None
    ):
        reporter = BOOTSTRAP.InstallReporter(stream=stream, clock=lambda: 1.0, environ=env)
        reporter.announce(Path("/tmp/ce-frame-project"), "ShaftHQ/chaosengine-harness", "main")
        reporter.start("Resolve source", remaining=("Download source",))
        reporter.complete("Resolve source", remaining=())
        reporter.complete("Resolve source", remaining=())
        reporter.close()
    text = stream.getvalue()
    assert "\x1b[" not in text
    assert text.count("DONE  Resolve source") == 1
    header = f"ChaosEngine {BOOTSTRAP.product_version()}"
    assert text.count(header) <= 1


def test_no_color_has_no_sgr_colour() -> None:
    _shots, text = _play(80, environ=_env(80, NO_COLOR="1"))
    assert "\x1b[?25l" in text
    assert "38;2;" not in text
    for code in COLOR_SGR.findall(text):
        assert code in {"0", "1", "2", "22"}, code


def test_non_tty_stray_stderr_does_not_reprint_the_header(capsys: pytest.CaptureFixture[str]) -> None:
    env = _env(80)
    stream = io.StringIO()
    with unittest.mock.patch.dict(os.environ, env, clear=True), unittest.mock.patch.object(
        BOOTSTRAP.threading.Thread, "start", lambda self: None
    ):
        reporter = BOOTSTRAP.InstallReporter(stream=stream, clock=lambda: 1.0, environ=env)
        reporter.start(
            "Provision dependencies",
            remaining=("Verify installation", "Activate clients"),
        )
        print("provision-stray-once", file=sys.stderr)
        reporter.complete(
            "Provision dependencies",
            remaining=("Verify installation", "Activate clients"),
        )
        reporter.close()
    text = stream.getvalue()
    captured = capsys.readouterr().err
    header = f"ChaosEngine {BOOTSTRAP.product_version()}"
    assert text.count(header) == 1
    assert text.count("DONE  Provision dependencies") == 1
    assert "\x1b[?25" not in text
    assert captured.count("provision-stray-once") == 1


def test_windows_vt_on_and_vt_off(monkeypatch: pytest.MonkeyPatch) -> None:
    env = _env(80)
    real_detect = BOOTSTRAP.detect_capabilities

    def detect_nt(stream=None, environ=None, *, vt=None):
        with unittest.mock.patch.object(BOOTSTRAP.os, "name", "nt"):
            return real_detect(stream, environ, vt=vt)

    monkeypatch.setattr(BOOTSTRAP, "detect_capabilities", detect_nt)

    def drive(vt: bool) -> tuple[str, str]:
        stream = _Tty()
        with unittest.mock.patch.dict(os.environ, env, clear=True), unittest.mock.patch.object(
            BOOTSTRAP.threading.Thread, "start", lambda self: None
        ), unittest.mock.patch.object(
            BOOTSTRAP.InstallReporter, "_enable_windows_vt", lambda self: vt
        ):
            reporter = BOOTSTRAP.InstallReporter(stream=stream, clock=lambda: 1.0, environ=env)
            reporter.start("Resolve source", remaining=("Download source",))
            reporter.complete("Resolve source", remaining=())
            screen = _screen(stream, 80)
            reporter.close()
        return stream.getvalue(), screen

    enabled, screen = drive(True)
    assert enabled.count("\x1b[?25l") == 1
    assert "\x1b[?25h" in enabled
    assert "\x1b[J" in enabled
    assert len(_header_lines(screen)) == 1

    disabled, _screen_off = drive(False)
    assert "\x1b" not in disabled
    header = f"ChaosEngine {BOOTSTRAP.product_version()}"
    assert disabled.count(header) == 1
    assert disabled.count("DONE  Resolve source") == 1


@pytest.mark.parametrize("encoding", ["cp437", "cp1252"])
def test_legacy_code_pages_use_ascii(encoding: str) -> None:
    stream = _EncodedTty(encoding)
    env = _env(100)
    with unittest.mock.patch.dict(os.environ, env, clear=True), unittest.mock.patch.object(
        BOOTSTRAP.threading.Thread, "start", lambda self: None
    ):
        reporter = BOOTSTRAP.InstallReporter(stream=stream, clock=lambda: 1.0, environ=env)
        reporter.start("Resolve source", remaining=())
        reporter.close()
    text = stream.getvalue()
    text.encode(encoding)
    assert "[ChaosEngine " in text
    assert "⠋" not in text
    assert "▗" not in text
    assert "✓" not in text


def test_mark_aspect_is_within_ten_percent_of_the_symbol() -> None:
    layers = MARK.load_layers((ROOT / "assets" / "brand" / "symbol-primary.svg").read_text(encoding="utf-8"))
    left, top, right, bottom = MARK.ink_box(layers)
    ink = (right - left) / (bottom - top)
    assert abs(ink - 0.80) / 0.80 < 0.05
    for rows, cols in (MARK.WIDE, MARK.STACK):
        screen_ratio = cols / (rows * 2)
        assert abs(screen_ratio - ink) / ink <= 0.10
    assert len(UI.BRAND_MARK_WIDE) == MARK.WIDE[0] == 8
    assert len(UI.BRAND_MARK_WIDE[0][0]) == MARK.WIDE[1] == 13
    assert len(UI.BRAND_MARK_STACK) == MARK.STACK[0] == 5
    assert len(UI.BRAND_MARK_STACK[0][0]) == MARK.STACK[1] == 8
    assert len(BOOTSTRAP.BRAND_MARK_WIDE) == 8
    assert len(BOOTSTRAP.BRAND_MARK_STACK) == 5


def test_bootstrap_has_no_return_break_or_continue_in_finally() -> None:
    tree = ast.parse((ROOT / "bootstrap.py").read_text(encoding="utf-8"))
    offenders: list[int] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Try):
            continue
        for item in node.finalbody:
            for sub in ast.walk(item):
                if isinstance(sub, (ast.Return, ast.Break, ast.Continue)):
                    offenders.append(sub.lineno)
    assert offenders == []


def test_certificate_fix_next_names_the_macos_command() -> None:
    error = RuntimeError(
        "dependency setup blocked: context7 (stable-channel lookup failed: "
        "SSL certificate verification failed)"
    )
    hint = BOOTSTRAP.next_fix_hint(
        "CE-INSTALL-FAILED",
        error,
        "python3 .chaos-engine/install.py",
    )
    assert "SSL certificate verification failed" in hint
    assert "SSL_CERT_FILE" in hint
    assert "repair --project . --component hosts" not in hint
    with unittest.mock.patch.object(BOOTSTRAP.sys, "platform", "linux"):
        linux = BOOTSTRAP.next_fix_hint(
            "CE-INSTALL-FAILED",
            error,
            "python3 .chaos-engine/install.py",
        )
    assert "Install Certificates.command" not in linux
    with unittest.mock.patch.object(BOOTSTRAP.sys, "platform", "darwin"):
        darwin = BOOTSTRAP.next_fix_hint(
            "CE-INSTALL-FAILED",
            error,
            "python3 .chaos-engine/install.py",
        )
    assert "Install Certificates.command" in darwin
    assert "SSL certificate verification failed" in darwin


def _cursor_script(body: str) -> str:
    return textwrap.dedent(
        f"""
        import os, sys
        sys.path.insert(0, {str(ROOT)!r})
        import importlib.util
        spec = importlib.util.spec_from_file_location("ce_cursor_child", {str(ROOT / "bootstrap.py")!r})
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        os.environ["TERM"] = "xterm-256color"
        os.environ["COLUMNS"] = "80"
        os.environ["LANG"] = "C.UTF-8"
        reporter = module.InstallReporter(clock=lambda: 1.0)
        reporter.start("Resolve source", remaining=("Download source",))
        sys.stdout.write("READY\\n")
        sys.stdout.flush()
        {body}
        """
    )


def _run_cursor_child(tmp_path: Path, body: str, sig: signal.Signals | None) -> bytes:
    script = tmp_path / "cursor_child.py"
    script.write_text(_cursor_script(body), encoding="utf-8")
    master, slave = pty.openpty()
    env = os.environ.copy()
    for key in (
        "CI",
        "GITHUB_ACTIONS",
        "CHAOS_ENGINE_JSON",
        "CHAOS_ENGINE_QUIET",
        "CHAOS_ENGINE_ASCII",
        "NO_COLOR",
    ):
        env.pop(key, None)
    env.update(
        {
            "TERM": "xterm-256color",
            "COLUMNS": "80",
            "LINES": "48",
            "LANG": "C.UTF-8",
            "LC_ALL": "C.UTF-8",
            "PYTHONUNBUFFERED": "1",
        }
    )
    proc = subprocess.Popen(
        [sys.executable, "-u", str(script)],
        stdin=slave,
        stdout=slave,
        stderr=slave,
        start_new_session=True,
        env=env,
    )
    os.close(slave)
    blob = b""
    sent = sig is None
    deadline = time.monotonic() + 8
    try:
        while time.monotonic() < deadline:
            ready, _, _ = select.select([master], [], [], 0.2)
            if ready:
                try:
                    chunk = os.read(master, 65536)
                except OSError:
                    break
                if not chunk:
                    break
                blob += chunk
            if not sent and b"READY" in blob and proc.poll() is None:
                os.kill(proc.pid, sig)
                sent = True
            if proc.poll() is not None:
                while True:
                    ready, _, _ = select.select([master], [], [], 0.1)
                    if not ready:
                        break
                    try:
                        chunk = os.read(master, 65536)
                    except OSError:
                        break
                    if not chunk:
                        break
                    blob += chunk
                break
        return blob
    finally:
        if proc.poll() is None:
            proc.kill()
            proc.wait(timeout=5)
        os.close(master)


def test_keyboard_interrupt_restores_the_cursor(tmp_path: Path) -> None:
    output = _run_cursor_child(tmp_path, "raise KeyboardInterrupt", None)
    assert b"\x1b[?25l" in output
    assert b"\x1b[?25h" in output
    assert output.rfind(b"\x1b[?25h") > output.rfind(b"\x1b[?25l")


def test_sigterm_restores_the_cursor(tmp_path: Path) -> None:
    output = _run_cursor_child(tmp_path, "import time; time.sleep(30)", signal.SIGTERM)
    assert b"\x1b[?25l" in output
    assert b"\x1b[?25h" in output
    assert output.rfind(b"\x1b[?25h") > output.rfind(b"\x1b[?25l")


def test_resize_keeps_one_header_and_the_step_count() -> None:
    env = _env(120)
    stream = _Tty()
    screen = Screen(120)
    with unittest.mock.patch.dict(os.environ, env, clear=True), unittest.mock.patch.object(
        BOOTSTRAP.threading.Thread, "start", lambda self: None
    ):
        reporter = BOOTSTRAP.InstallReporter(stream=stream, clock=lambda: 1.0, environ=env)
        reporter.start("Resolve source", remaining=_remaining("Resolve source"))
        chunk = stream.getvalue()
        screen.feed(chunk)
        cursor = len(chunk)
        _assert_frame(screen.text(), 120)
        env["COLUMNS"] = "80"
        os.environ["COLUMNS"] = "80"
        screen.set_columns(80)
        reporter.complete("Resolve source", remaining=_remaining("Resolve source"))
        screen.feed(stream.getvalue()[cursor:])
        _assert_frame(screen.text(), 80)
        reporter.close()
