"""Shared helpers used by the installer, hosts, bootstrap, and dependencies.

Callers re-export these names. Bootstrap keeps inline copies for a curl|bash
run that has not downloaded ``runtime/`` yet, then rebinds when this file exists.
"""

from __future__ import annotations

import hashlib
import os
import re
import sys
from pathlib import Path

MINIMUM_PYTHON = (3, 11)
_BRANCH_PATTERN = re.compile(r"[^\x00-\x20\x7f~^:?*\\\[\]]+")


def runtime_module(root: Path, name: str) -> Path:
    """Prefer runtime/<name>; fall back to a flat file from an older tree."""
    nested = root / "runtime" / name
    if nested.is_file():
        return nested
    return root / name


def file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


_file_sha256 = file_sha256


def is_link_or_reparse(path: Path) -> bool:
    if path.is_symlink():
        return True
    try:
        attributes = getattr(os.lstat(path), "st_file_attributes", 0)
    except FileNotFoundError:
        return False
    return bool(attributes & 0x400)


def valid_branch(branch: str) -> bool:
    parts = branch.split("/")
    return (
        _BRANCH_PATTERN.fullmatch(branch) is not None
        and not branch.startswith("-")
        and not branch.startswith("/")
        and not branch.endswith(("/", "."))
        and "//" not in branch
        and ".." not in branch
        and "@{" not in branch
        and branch != "HEAD"
        and all(part and not part.startswith(".") and not part.endswith(".lock") for part in parts)
    )


def python_floor_message(version: tuple[int, ...] | None = None) -> str:
    """What is missing, why, and the one fix (#7766)."""
    found = ".".join(str(part) for part in (version or sys.version_info)[:3])
    return (
        f"ChaosEngine requires Python {MINIMUM_PYTHON[0]}.{MINIMUM_PYTHON[1]} or newer; found {found}. "
        "Hooks and the installer refuse an older interpreter. "
        "Rerun the install one-liner, which provisions a supported Python through uv before any prompt.\n"
    )
