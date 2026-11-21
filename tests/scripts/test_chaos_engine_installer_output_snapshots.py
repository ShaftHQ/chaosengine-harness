"""Pin today's installer transcript before later slices change it (#129).

The helper drives the shipped ``InstallReporter`` success and failure paths.
``UPDATE_GOLDEN=1`` rewrites ``tests/scripts/golden/installer-output/``.
A difference from those files is a failure. Durations come from a fake clock.
The project directory is a fixed Linux path so wrapping does not depend on
the checkout location. POSIX capture uses ``pty.openpty`` with output
processing off. Windows uses a plain ``isatty`` stream; the two agree on Linux.
"""

from __future__ import annotations

import importlib.util
import io
import os
import pty
import re
import select
import sys
import tempfile
import termios
import threading
import unittest.mock
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[2]
GOLDEN = ROOT / "tests" / "scripts" / "golden" / "installer-output"
PROJECT_ROOT = Path("/tmp/ce-golden-project")
EMPTY_PATH = Path("/tmp/ce-golden-empty")
COMMIT = "0123456789abcdef0123456789abcdef01234567"
MODES = ("tty", "log", "ci", "json", "quiet")
WIDTHS = (50, 80, 120)
CURSOR_UP = re.compile(r"\x1b\[\d+F")


def load_bootstrap():
    spec = importlib.util.spec_from_file_location("ce_bootstrap_snapshots", ROOT / "bootstrap.py")
    if spec is None or spec.loader is None:
        raise ImportError("cannot load bootstrap.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


BOOTSTRAP = load_bootstrap()


class _Clock:
    def __init__(self) -> None:
        self.n = 0

    def __call__(self) -> float:
        self.n += 1
        return 1_700_000_000.0 + self.n


class _SilentThread:
    """The live ticker waits on wall time. Golden frames are the synchronous ones."""

    def __init__(self, *args, **kwargs) -> None:
        self.ident = None

    def start(self) -> None:
        return None

    def join(self, timeout=None) -> None:
        return None


class _PlainTty(io.StringIO):
    encoding = "utf-8"

    def isatty(self) -> bool:
        return True


def case_name(mode: str, width: int, no_color: bool, ascii_mode: bool, outcome: str) -> str:
    color = "nocolor" if no_color else "color"
    glyphs = "ascii" if ascii_mode else "unicode"
    return f"{outcome}-{mode}-w{width}-{color}-{glyphs}"


def project_for(name: str) -> Path:
    del name
    PROJECT_ROOT.mkdir(parents=True, exist_ok=True)
    return PROJECT_ROOT


def environment(width: int, mode: str, no_color: bool, ascii_mode: bool) -> dict[str, str]:
    env = {
        "PATH": str(EMPTY_PATH),
        "HOME": "/tmp/ce-golden-home",
        "TERM": "xterm-256color",
        "COLUMNS": str(width),
        "LINES": "40",
        "LANG": "C.UTF-8",
        "LC_ALL": "C.UTF-8",
        "PYTHONIOENCODING": "utf-8",
    }
    if no_color:
        env["NO_COLOR"] = "1"
    if ascii_mode:
        env["CHAOS_ENGINE_ASCII"] = "1"
    if mode == "ci":
        env["CI"] = "true"
    if mode == "json":
        env["CHAOS_ENGINE_JSON"] = "1"
    if mode == "quiet":
        env["CHAOS_ENGINE_QUIET"] = "1"
    return env


def normalize(text: str, project: Path) -> str:
    resolved = str(project.resolve())
    text = text.replace(resolved, "<project>")
    text = text.replace(project.as_posix(), "<project>")
    root = str(PROJECT_ROOT)
    text = text.replace(root, "<root>")
    text = text.replace(PROJECT_ROOT.as_posix(), "<root>")
    text = text.replace("\r\n", "\n").replace("\r", "")
    return text


def _play(stream, project: Path, outcome: str) -> None:
    reporter = BOOTSTRAP.InstallReporter(stream=stream, clock=_Clock())
    reporter.announce(project, "ShaftHQ/chaosengine-harness", "main")
    reporter.start("Resolve source", remaining=("Download source", "Install core"))
    reporter.complete("Resolve source", remaining=("Download source", "Install core"))
    reporter.start("Download source", remaining=("Install core",))
    if outcome == "failure":
        reporter.fail()
        reporter.close()
        return
    reporter.complete("Download source", remaining=())
    reporter.success(
        project,
        {
            "status": "healthy",
            "commit": COMMIT,
            "components": {"core": {"status": "healthy", "taskImpact": "required"}},
        },
        {"grok": {"status": "activated"}},
        repository="ShaftHQ/chaosengine-harness",
    )


def _prepare_slave(fd: int, width: int) -> None:
    attrs = termios.tcgetattr(fd)
    attrs[1] &= ~termios.OPOST
    attrs[3] &= ~termios.ECHO
    termios.tcsetattr(fd, termios.TCSANOW, attrs)
    if sys.platform != "win32":
        import fcntl
        import struct

        fcntl.ioctl(fd, termios.TIOCSWINSZ, struct.pack("HHHH", 40, width, 0, 0))


def capture_pty(width: int, drive) -> str:
    master, slave = pty.openpty()
    try:
        _prepare_slave(slave, width)
        chunks: list[bytes] = []
        stop = threading.Event()

        def read_master() -> None:
            while not stop.is_set():
                ready, _, _ = select.select([master], [], [], 0.05)
                if not ready:
                    continue
                try:
                    blob = os.read(master, 65536)
                except OSError:
                    return
                if not blob:
                    return
                chunks.append(blob)

        reader = threading.Thread(target=read_master, daemon=True)
        reader.start()
        stream = os.fdopen(slave, "w", encoding="utf-8", newline="\n", closefd=True)
        try:
            drive(stream)
            stream.flush()
        finally:
            stream.close()
        stop.set()
        reader.join(timeout=2)
        while True:
            ready, _, _ = select.select([master], [], [], 0.05)
            if not ready:
                break
            try:
                blob = os.read(master, 65536)
            except OSError:
                break
            if not blob:
                break
            chunks.append(blob)
        return b"".join(chunks).decode("utf-8")
    finally:
        try:
            os.close(master)
        except OSError:
            pass


def capture_plain(drive) -> str:
    stream = _PlainTty()
    drive(stream)
    return stream.getvalue()


def render(mode: str, width: int, no_color: bool, ascii_mode: bool, outcome: str) -> str:
    name = case_name(mode, width, no_color, ascii_mode, outcome)
    project = project_for(name)
    env = environment(width, mode, no_color, ascii_mode)
    EMPTY_PATH.mkdir(parents=True, exist_ok=True)
    Path("/tmp/ce-golden-home").mkdir(parents=True, exist_ok=True)

    def drive(stream) -> None:
        with unittest.mock.patch.dict(os.environ, env, clear=True), unittest.mock.patch(
            "threading.Thread", _SilentThread
        ), unittest.mock.patch.object(
            BOOTSTRAP.InstallReporter, "_enable_windows_vt", return_value=True
        ):
            _play(stream, project, outcome)

    if mode == "tty" and os.name != "nt":
        text = capture_pty(width, drive)
    else:
        text = capture_plain(drive) if mode == "tty" else _capture_pipe(drive)
    return normalize(text, project)


def _capture_pipe(drive) -> str:
    stream = io.StringIO()
    drive(stream)
    return stream.getvalue()


CASES = tuple(
    (mode, width, no_color, ascii_mode, outcome)
    for mode in MODES
    for width in WIDTHS
    for no_color in (False, True)
    for ascii_mode in (False, True)
    for outcome in ("success", "failure")
)


@pytest.mark.parametrize(
    ("mode", "width", "no_color", "ascii_mode", "outcome"),
    CASES,
    ids=[case_name(*case) for case in CASES],
)
def test_installer_output_snapshot(mode, width, no_color, ascii_mode, outcome):
    if os.name == "nt":
        pytest.skip("golden files are pinned from the Linux pty path")
    text = render(mode, width, no_color, ascii_mode, outcome)
    path = GOLDEN / f"{case_name(mode, width, no_color, ascii_mode, outcome)}.txt"
    if os.environ.get("UPDATE_GOLDEN") == "1":
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8", newline="\n")
        return
    assert path.is_file(), f"missing golden {path.name}; regenerate with UPDATE_GOLDEN=1"
    assert text == path.read_text(encoding="utf-8")
    if mode != "tty":
        assert "\x1b[" not in text


def test_plain_tty_matches_pty_capture():
    if os.name == "nt":
        pytest.skip("pty capture is the POSIX path")
    plain = render("tty", 80, False, False, "success")
    # render() already used the pty for tty. Drive the plain stream with the same inputs.
    project = project_for(case_name("tty", 80, False, False, "success"))
    env = environment(80, "tty", False, False)

    def drive(stream) -> None:
        with unittest.mock.patch.dict(os.environ, env, clear=True), unittest.mock.patch(
            "threading.Thread", _SilentThread
        ):
            _play(stream, project, "success")

    assert normalize(capture_plain(drive), project) == plain


def test_no_color_tty_redraws_in_place():
    if os.name == "nt":
        pytest.skip("redraw capture uses the POSIX pty")
    text = render("tty", 80, True, False, "success")
    assert CURSOR_UP.search(text), "NO_COLOR=1 TTY appended frames instead of redrawing"
    assert not re.search(r"\x1b\[[0-9;]*m", text), "NO_COLOR=1 TTY frame used SGR colour"


def test_plan_prints_bare_tool_names_on_stderr():
    """E2 repro: a .git checkout whose config names github.com must not write bare tool names.

    Captured probe output stays on the trace the helper returns (#131).
    """
    spec = importlib.util.spec_from_file_location(
        "ce_prerequisites_snapshots", ROOT / "runtime" / "prerequisites.py"
    )
    module = importlib.util.module_from_spec(spec)
    assert spec is not None and spec.loader is not None
    spec.loader.exec_module(module)
    with tempfile.TemporaryDirectory() as tmp:
        project = Path(tmp)
        git_dir = project / ".git"
        git_dir.mkdir()
        (git_dir / "config").write_text(
            '[remote "origin"]\n\turl = https://github.com/ShaftHQ/chaosengine-harness.git\n',
            encoding="utf-8",
        )
        stderr = io.StringIO()
        with unittest.mock.patch("sys.stderr", stderr):
            rows = module.plan(
                project,
                windows=False,
                current_mode="report",
                cache_file=project / "cache.json",
            )
    bare = [line.strip() for line in stderr.getvalue().splitlines()]
    assert "git" not in bare and "gh" not in bare and "node" not in bare
    assert {"git", "gh", "node"} <= {row["tool"] for row in rows}
    for record in rows.trace:
        assert set(record) >= {"argv", "returncode", "stdout", "stderr"}

    class _Done:
        returncode = 0
        stdout = "git version captured\n"
        stderr = ""

    done = module.ce_ui.run_captured(["git", "--version"], runner=lambda argv, **_kwargs: _Done())
    assert done.trace[0]["stdout"] == "git version captured\n"
    assert done.trace[0]["argv"] == ["git", "--version"]
