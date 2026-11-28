#!/usr/bin/env python3
"""Harness pre-push helpers that live in this repo.

``ce_version_bump_failures`` is the VERSION gate. The push hook calls
``overlay_pre_push_failures(project)`` with no changed-path list; an empty
list does not invent a diff, so a push is not blocked until a caller passes
paths. Full SHAFT overlay checks are not in this tree.
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

VERSION_FILE = "VERSION"
_CE_UI_PATHS = frozenset({"bootstrap.py", "runtime/ce_ui.py"})
_RETRIEVE_PATHS = frozenset({"bootstrap.py", "runtime/retrieve.py"})


def ce_version_bump_failures(root: Path, paths: list[str]) -> list[str]:
    """Require VERSION when harness paths change.

    A path list that already contains ``VERSION`` passes. ``.chaos-engine-state/no-version-bump``
    waives the check for a local run. An empty list is not a diff.
    """
    normalized = [item.replace("\\", "/").removeprefix("./") for item in paths if item]
    if not normalized or VERSION_FILE in normalized:
        return []
    if (root / ".chaos-engine-state" / "no-version-bump").is_file():
        return []
    return [
        "ce-version-bump: harness paths changed without VERSION; "
        "bump VERSION or add <!-- chaos-engine:no-version-bump --> / label ce-no-version-bump"
    ]


def _load_sync_ce_ui(root: Path):
    path = root / "scripts" / "ci" / "sync_ce_ui.py"
    if not path.is_file():
        return None
    spec = importlib.util.spec_from_file_location("ce_sync_ce_ui_fast", path)
    if spec is None or spec.loader is None:
        return None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def ce_ui_sync_failures(root: Path) -> list[str]:
    """Fail when ``bootstrap.py`` no longer matches ``runtime/ce_ui.py``."""
    module = _load_sync_ce_ui(root)
    source = root / "runtime" / "ce_ui.py"
    target = root / "bootstrap.py"
    if module is None or not source.is_file() or not target.is_file():
        return []
    try:
        drifted = not module.matches(target, source)
    except SystemExit as error:
        return [f"ce_ui inline drift: {error}"]
    if not drifted:
        return []
    return ["ce_ui inline drift: run python3 scripts/ci/sync_ce_ui.py"]


def retrieve_router_sync_failures(root: Path) -> list[str]:
    """Fail when bootstrap inlines a retrieve-router block that drifted.

    No generated block means there is nothing to compare. The check only
    reads the two files.
    """
    bootstrap = root / "bootstrap.py"
    retrieve = root / "runtime" / "retrieve.py"
    if not bootstrap.is_file() or not retrieve.is_file():
        return []
    text = bootstrap.read_text(encoding="utf-8")
    start = "# >>> generated: retrieve_router\n"
    end = "# <<< generated: retrieve_router\n"
    if start not in text or end not in text:
        return []
    begin = text.index(start) + len(start)
    finish = text.index(end)
    if finish < begin:
        return ["retrieve router inline drift: markers out of order"]
    inline = text[begin:finish]
    body = retrieve.read_text(encoding="utf-8")
    if inline.strip() and inline not in body and body not in inline:
        return ["retrieve router inline drift: re-sync runtime/retrieve.py into bootstrap.py"]
    return []


def _normalized_paths(paths: list[str] | None) -> list[str]:
    return [item.replace("\\", "/").removeprefix("./") for item in (paths or []) if item]


def overlay_pre_push_failures(root: Path, paths: list[str] | None = None) -> list[str]:
    """Hook entry. No path list means the caller did not supply a diff."""
    normalized = _normalized_paths(paths)
    failures = ce_version_bump_failures(root, normalized)
    if not normalized:
        return failures
    if any(item in _CE_UI_PATHS for item in normalized):
        failures.extend(ce_ui_sync_failures(root))
    if any(item in _RETRIEVE_PATHS for item in normalized):
        failures.extend(retrieve_router_sync_failures(root))
    failures.extend(_docs_drift_failures(root, normalized))
    return failures


def _docs_drift_failures(root: Path, paths: list[str]) -> list[str]:
    """Run the docs-drift gate when the diff touches a scanned file."""
    path = root / "scripts" / "ci" / "docs_drift.py"
    if not path.is_file():
        return []
    spec = importlib.util.spec_from_file_location("ce_docs_drift_pre_push", path)
    if spec is None or spec.loader is None:
        return []
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.gate_findings(root, paths)


def main(argv: list[str] | None = None) -> int:
    """Fast CLI: ``overlay_pre_push.py <root>`` prints failures, if any."""
    args = list(sys.argv[1:] if argv is None else argv)
    root = Path(args[0]) if args else Path.cwd()
    paths = args[1:] or None
    failures = overlay_pre_push_failures(root, paths)
    for item in failures:
        print(item, file=sys.stderr)
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
