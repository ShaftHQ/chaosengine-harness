#!/usr/bin/env python3
"""Skill-listing counter used by harness_index and the skill-index parity tests.

The full SHAFT guidance validator is not this module. Callers here need the
listing counter, the small frontmatter parser, and the ghost-path check for
markdown this workstream owns.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

_BLOCK_SCALAR_HEADER = re.compile(r"^[|>][+-]?\d*$")


def expand_globs(root: Path, patterns: list[str]) -> list[Path]:
    """Expand repository-relative files and globs."""
    paths: set[Path] = set()
    for pattern in patterns:
        if any(character in pattern for character in "*?["):
            paths.update(path for path in root.glob(pattern) if path.is_file())
        else:
            path = root / pattern
            if path.is_file():
                paths.add(path)
    return sorted(paths)


def parse_frontmatter(content: str) -> dict[str, str] | None:
    """Parse flat YAML frontmatter, including folded description scalars."""
    if not content.startswith("---\n"):
        return None
    marker = content.find("\n---\n", 4)
    if marker < 0:
        return None
    lines = content[4:marker].splitlines()
    values: dict[str, str] = {}
    index = 0
    while index < len(lines):
        raw_line = lines[index]
        index += 1
        if ":" not in raw_line or raw_line[:1].isspace():
            continue
        key, value = raw_line.split(":", 1)
        key = key.strip()
        value = value.strip()
        if _BLOCK_SCALAR_HEADER.match(value):
            folded = value.startswith(">")
            block_lines: list[str] = []
            while index < len(lines) and (lines[index][:1].isspace() or not lines[index].strip()):
                block_lines.append(lines[index].strip())
                index += 1
            if folded:
                paragraphs: list[str] = []
                current: list[str] = []
                for block_line in block_lines:
                    if block_line:
                        current.append(block_line)
                    elif current:
                        paragraphs.append(" ".join(current))
                        current = []
                if current:
                    paragraphs.append(" ".join(current))
                values[key] = "\n\n".join(paragraphs)
            else:
                values[key] = "\n".join(block_lines).strip()
        else:
            values[key] = value.strip("\"'")
    return values


def skill_listing_chars(root: Path, patterns: list[str]) -> int:
    """Count discovery metadata a host keeps resident for every matched skill."""
    characters = 0
    for path in expand_globs(root, patterns):
        frontmatter = parse_frontmatter(path.read_text(encoding="utf-8")) or {}
        characters += len(frontmatter.get("name", ""))
        characters += len(frontmatter.get("description", ""))
    return characters


_BACKTICK = re.compile(r"`([^`\n]+)`")
_GHOST = re.compile(r"(?:^|[\s\"'=])((?:chaos-engine/|scripts/ci/)\S+)")
_OWNED_REFERENCES = (
    "bot-entry.md",
    "router-contract.md",
    "delivery-cycle.md",
    "permanent-rules.md",
    "delegate-card.md",
    "catalog.md",
    "harness-map.md",
    "level-1-catalog.md",
    "rule-retirement.md",
    "graphify.md",
    "box-durability.md",
)


def owned_guidance_markdown(root: Path) -> list[Path]:
    """Markdown this policy stream can fix. Other references stay out of the gate."""
    paths: list[Path] = []
    skills = root / "skills"
    if skills.is_dir():
        paths.extend(skills.rglob("*.md"))
    refs = root / "references"
    for name in _OWNED_REFERENCES:
        path = refs / name
        if path.is_file():
            paths.append(path)
    if refs.is_dir():
        paths.extend(refs.glob("ce-*-SPEC.md"))
        details = refs / "details"
        if details.is_dir():
            paths.extend(details.rglob("*.md"))
    guides = root / "guides"
    if guides.is_dir():
        paths.extend(guides.glob("*.md"))
    return sorted(set(paths))


def _token_exists(root: Path, token: str) -> bool:
    token = token.rstrip(".,:;)")
    if token.startswith("chaos-engine/"):
        return (root / token[len("chaos-engine/"):]).exists()
    return (root / token).exists()


def ghost_findings(root: Path) -> list[str]:
    """Backticked chaos-engine/ or scripts/ci/ paths that are not in this tree.

    A line tagged external-example or repo-only is an intentional outside path.
    A chaos-engine/ prefix that exists at the repo root after the prefix is real.
    """
    findings: list[str] = []
    for path in owned_guidance_markdown(root):
        text = path.read_text(encoding="utf-8", errors="replace")
        relative = path.relative_to(root).as_posix()
        for number, line in enumerate(text.splitlines(), 1):
            if "external-example" in line or "repo-only" in line:
                continue
            for backtick in _BACKTICK.finditer(line):
                for hit in _GHOST.finditer(backtick.group(1)):
                    token = hit.group(1).rstrip(".,:;)")
                    if _token_exists(root, token):
                        continue
                    findings.append(f"ghost path: {relative}:{number}: {token}")
    return findings


def main(argv: list[str] | None = None) -> int:
    del argv
    root = Path(__file__).resolve().parents[2]
    findings = ghost_findings(root)
    for item in findings:
        print(item, file=sys.stderr)
    return 1 if findings else 0


if __name__ == "__main__":
    raise SystemExit(main())
