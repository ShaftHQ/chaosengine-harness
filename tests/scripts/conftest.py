"""Suite-wide guard: tests never mutate the developer's checkout (#6239).

Before collection it marks the invoking checkout (and its primary checkout)
as protected for ChaosEngine session-worktree code, disables detached store
refreshes in test subprocesses, and snapshots branch, HEAD, status, and
registered worktrees. After the run it fails the session when any of them
changed. Under xdist only the controller snapshots and compares.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import repo_state_guard  # noqa: E402

_ROOTS: list[Path] = []
_BEFORE: dict[Path, dict] = {}


def pytest_configure(config):
    os.environ.setdefault("CHAOS_ENGINE_STORE_REFRESH", "0")
    roots = repo_state_guard.checkout_roots(Path(__file__).resolve().parent)
    repo_state_guard.protect(roots)
    if hasattr(config, "workerinput"):
        return
    _ROOTS[:] = roots
    for root in roots:
        _BEFORE[root] = repo_state_guard.snapshot(root)


def pytest_sessionfinish(session, exitstatus):
    if hasattr(session.config, "workerinput"):
        return
    problems = []
    for root in _ROOTS:
        changed = repo_state_guard.differences(_BEFORE[root], repo_state_guard.snapshot(root))
        problems.extend(f"{root}: {item}" for item in changed)
    if problems:
        session.config._repo_state_guard_problems = problems
        session.exitstatus = 1


def pytest_terminal_summary(terminalreporter, exitstatus, config):
    problems = getattr(config, "_repo_state_guard_problems", None)
    if problems:
        terminalreporter.section("repo-state guard (#6239)", red=True)
        terminalreporter.line("The test run mutated the invoking checkout:", red=True)
        for item in problems:
            terminalreporter.line(f"  {item}", red=True)


# Port quarantine (#8065): tests that still depend on SHAFT_ENGINE-only modules or
# fixtures are listed in quarantine.txt. File entries are not collected; node ids
# are skipped with a reason. Remove entries as each test is ported.
def _quarantine():
    path = Path(__file__).with_name("quarantine.txt")
    entries = [line.split("#", 1)[0].strip() for line in path.read_text(encoding="utf-8").splitlines()]
    return [entry for entry in entries if entry]


_Q = _quarantine()
collect_ignore = [entry.rsplit("/", 1)[-1] for entry in _Q if "::" not in entry]


def pytest_collection_modifyitems(config, items):
    import pytest

    skipped = {entry for entry in _Q if "::" in entry}
    for item in items:
        if item.nodeid in skipped:
            item.add_marker(pytest.mark.skip(reason="port quarantine #8065: depends on SHAFT_ENGINE-only modules or fixtures"))
