"""Suite-wide Grok home sandbox (ShaftHQ/SHAFT_ENGINE#8070).

Tests must never write the developer's real ``~/.grok/config.toml``. Every
process, including an xdist worker, gets its own ``GROK_HOME``. A tripwire
refuses writes under the real Grok home. The session fails when that log is
not empty or the real ``config.toml`` bytes change.
"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

import pytest

_STATE: dict[str, object] = {}


def _real_grok_home() -> Path:
    env = os.environ.get("GROK_HOME")
    return Path(env).expanduser() if env else Path.home() / ".grok"


def _read(path: Path) -> bytes | None:
    try:
        return path.read_bytes()
    except OSError:
        return None


def grok_sandbox_env(environ: dict[str, str], *, worker_id: str | None, real_home: Path) -> dict[str, str]:
    """Return env updates. Workers do not share the controller sandbox."""
    updated = dict(environ)
    if not updated.get("CHAOS_ENGINE_PROTECTED_GROK_HOME"):
        updated["CHAOS_ENGINE_PROTECTED_GROK_HOME"] = str(real_home)
    tag = worker_id or "main"
    sandbox = Path(tempfile.mkdtemp(prefix=f"ce-test-grok-home-{tag}-"))
    updated["GROK_HOME"] = str(sandbox)
    if not updated.get("CHAOS_ENGINE_PROTECTED_GROK_HOME_LOG"):
        updated["CHAOS_ENGINE_PROTECTED_GROK_HOME_LOG"] = str(sandbox.parent / f"{sandbox.name}.tripwire.log")
    return updated


def grok_byte_problems(before: bytes | None, after: bytes | None, log: bytes) -> list[str]:
    """A real config.toml byte change fails the session. It is not advisory."""
    problems = [
        f"blocked write to the real Grok home: {line}"
        for line in log.decode("utf-8", "replace").splitlines()
        if line
    ]
    if before != after:
        problems.append("real Grok config.toml bytes changed during the run")
    return problems


_HARNESS_ENV_EXACT = frozenset({
    "CHAOS_ENGINE_SECRET_GUARD",
    "CHAOS_ENGINE_TOKEN_BUDGET",
    "CHAOS_ENGINE_APPLY_UPDATE",
    "CHAOS_ENGINE_VERSION",
    "CHAOS_ENGINE_COPY_PROMPT",
    "NO_COLOR",
    "CI",
})


def _harness_env_key(name: str) -> bool:
    """Harness toggles a test may set. Never the Grok-home sandbox keys."""
    if name == "GROK_HOME" or name.startswith("CHAOS_ENGINE_PROTECTED_GROK_HOME"):
        return False
    if name in _HARNESS_ENV_EXACT or name.startswith("CHAOS_ENGINE_TEST_"):
        return True
    return False


@pytest.fixture(autouse=True)
def _isolate_harness_env():
    """Restore harness toggles after each test so one test cannot leak them."""
    before = {key: os.environ[key] for key in os.environ if _harness_env_key(key)}
    try:
        yield
    finally:
        for key in [key for key in os.environ if _harness_env_key(key)]:
            if key not in before:
                os.environ.pop(key, None)
        os.environ.update(before)


def pytest_configure(config):
    worker = getattr(config, "workerinput", None)
    worker_id = None
    if isinstance(worker, dict):
        worker_id = str(worker.get("workerid") or "worker")
    real = _real_grok_home()
    updated = grok_sandbox_env(dict(os.environ), worker_id=worker_id, real_home=real)
    os.environ.update(updated)
    if worker is None and "real" not in _STATE:
        _STATE.update(
            real=real,
            log=Path(updated["CHAOS_ENGINE_PROTECTED_GROK_HOME_LOG"]),
            before=_read(real / "config.toml"),
        )


def pytest_sessionfinish(session, exitstatus):
    if hasattr(session.config, "workerinput") or "real" not in _STATE:
        return
    log = _STATE["log"]
    hits = _read(log) or b""  # type: ignore[arg-type]
    real_config = _STATE["real"] / "config.toml"  # type: ignore[operator]
    problems = grok_byte_problems(_STATE["before"], _read(real_config), hits)  # type: ignore[arg-type]
    if problems:
        session.config._grok_home_problems = problems
        session.exitstatus = 1


def pytest_terminal_summary(terminalreporter, exitstatus, config):
    problems = getattr(config, "_grok_home_problems", None)
    if problems:
        terminalreporter.section("grok home sandbox (#8070)", red=True)
        for item in problems:
            terminalreporter.line(f"  {item}", red=True)
