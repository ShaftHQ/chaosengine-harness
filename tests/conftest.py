"""Suite-wide Grok home sandbox (ShaftHQ/SHAFT_ENGINE#8070).

Tests must never write the developer's real ``~/.grok/config.toml``. Before any
test runs, the controller points ``GROK_HOME`` at a throwaway directory (child
processes and xdist workers inherit it) and arms a tripwire: any ChaosEngine
config write under the real Grok home is refused and logged, and the session
fails if the log is not empty. The real file's bytes are also compared after
the run (advisory, since a Grok CLI running alongside may rewrite it).
"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

_STATE: dict[str, object] = {}


def _real_grok_home() -> Path:
    env = os.environ.get("GROK_HOME")
    return Path(env).expanduser() if env else Path.home() / ".grok"


def _read(path: Path) -> bytes | None:
    try:
        return path.read_bytes()
    except OSError:
        return None


def pytest_configure(config):
    if os.environ.get("CHAOS_ENGINE_PROTECTED_GROK_HOME"):
        return  # already armed by the controller or an outer run
    real = _real_grok_home()
    sandbox = Path(tempfile.mkdtemp(prefix="ce-test-grok-home-"))
    log = sandbox.parent / f"{sandbox.name}.tripwire.log"
    os.environ["CHAOS_ENGINE_PROTECTED_GROK_HOME"] = str(real)
    os.environ["CHAOS_ENGINE_PROTECTED_GROK_HOME_LOG"] = str(log)
    os.environ["GROK_HOME"] = str(sandbox)
    _STATE.update(real=real, log=log, before=_read(real / "config.toml"))


def pytest_sessionfinish(session, exitstatus):
    if hasattr(session.config, "workerinput") or "real" not in _STATE:
        return
    problems: list[str] = []
    log = _STATE["log"]
    hits = _read(log) or b""  # type: ignore[arg-type]
    for line in hits.decode("utf-8", "replace").splitlines():
        problems.append(f"blocked write to the real Grok home: {line}")
    real_config = _STATE["real"] / "config.toml"  # type: ignore[operator]
    if _read(real_config) != _STATE["before"]:
        # Advisory only: a Grok CLI running beside the tests may rewrite it too.
        session.config._grok_home_advisory = (
            f"{real_config} changed during the run; check that no test escaped the sandbox"
        )
    if problems:
        session.config._grok_home_problems = problems
        session.exitstatus = 1


def pytest_terminal_summary(terminalreporter, exitstatus, config):
    advisory = getattr(config, "_grok_home_advisory", None)
    if advisory:
        terminalreporter.section("grok home sandbox (#8070)", yellow=True)
        terminalreporter.line(f"  {advisory}", yellow=True)
    problems = getattr(config, "_grok_home_problems", None)
    if problems:
        terminalreporter.section("grok home sandbox (#8070)", red=True)
        for item in problems:
            terminalreporter.line(f"  {item}", red=True)
