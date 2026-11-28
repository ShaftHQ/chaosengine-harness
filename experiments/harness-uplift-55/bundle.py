#!/usr/bin/env python3
"""#55 bundler for a later uplift run. Install trees do not consume the cap.

The published #45 measurement is not edited. This module is the pre-registered
fix: skip install trees, and order pom.xml and src/ ahead of other files.
"""

from __future__ import annotations

from pathlib import Path

SOURCE_SUFFIXES = {".java", ".xml", ".properties", ".md", ".json", ".txt"}
SKIP_DIRS = {
    ".chaos-engine",
    ".chaos-engine-state",
    ".grok",
    ".git",
    "target",
    ".agents",
    ".memory",
}


def _rank(project: Path, path: Path) -> tuple[int, str]:
    relative = path.relative_to(project).as_posix()
    if path.name == "pom.xml":
        group = 0
    elif relative.startswith("src/"):
        group = 1
    else:
        group = 2
    return group, relative


def source_bundle(project: Path, limit: int = 120_000) -> str:
    project = Path(project)
    files: list[Path] = []
    for path in project.rglob("*"):
        if not path.is_file() or path.suffix.lower() not in SOURCE_SUFFIXES:
            continue
        if any(part in SKIP_DIRS for part in path.parts):
            continue
        files.append(path)
    files.sort(key=lambda path: _rank(project, path))
    chunks: list[str] = []
    size = 0
    for path in files:
        text = path.read_text(encoding="utf-8", errors="replace")
        relative = path.relative_to(project).as_posix()
        piece = f"\n\n# FILE {relative}\n{text}"
        if size + len(piece) > limit:
            chunks.append("\n\n# TRUNCATED\n")
            break
        chunks.append(piece)
        size += len(piece)
    return "".join(chunks)
