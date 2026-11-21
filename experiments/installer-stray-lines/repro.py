"""Print the bare tool names `plan` writes, and the source line that writes them."""

from __future__ import annotations

import importlib.util
import io
import sys
import tempfile
import unittest.mock
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def load():
    path = ROOT / "runtime" / "prerequisites.py"
    spec = importlib.util.spec_from_file_location("ce_prerequisites_repro", path)
    if spec is None or spec.loader is None:
        raise ImportError(path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def writer_line() -> int:
    lines = (ROOT / "runtime" / "prerequisites.py").read_text(encoding="utf-8").splitlines()
    in_plan = False
    for number, line in enumerate(lines, 1):
        if line.startswith("def plan("):
            in_plan = True
        elif in_plan and line.startswith("def "):
            break
        elif in_plan and line.strip() == "print(tool, file=sys.stderr, flush=True)":
            return number
    raise RuntimeError("plan() no longer prints the tool name")


def main() -> int:
    module = load()
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
            module.plan(
                project,
                windows=False,
                current_mode="report",
                cache_file=project / "cache.json",
            )
    print(f"runtime/prerequisites.py:{writer_line()}")
    sys.stdout.write(stderr.getvalue())
    return 0


if __name__ == "__main__":
    sys.exit(main())
