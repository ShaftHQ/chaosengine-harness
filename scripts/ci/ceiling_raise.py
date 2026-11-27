#!/usr/bin/env python3
"""Flag a harness ceiling that a PR loosened against a base revision (#8032 R3).

Compares text only. A shrink passes. Paths outside the two harness ceilings
are ignored. A missing base blob is empty text, so a new positive ceiling is
a raise from zero.
"""

from __future__ import annotations

import argparse
import json
import math
import subprocess
import sys
from pathlib import Path

_ALWAYS_LOADED = "always-loaded-budget.json"
_DECISION = "docs/evidence/decision-quality-score.baseline.json"


def _is_number(value: object) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _format_ceiling(value: float) -> str:
    if value.is_integer():
        return str(int(value))
    return format(value, "g")


def _json_object(text: str) -> dict | None:
    if not text.strip():
        return {}
    try:
        loaded = json.loads(text)
    except json.JSONDecodeError:
        return None
    return loaded if isinstance(loaded, dict) else None


def _loosened(path: str, before: dict[str, float], after: dict[str, float], *, higher: bool) -> list[str]:
    lines: list[str] = []
    for key in sorted(after):
        base_value = before.get(key, 0.0)
        head_value = after[key]
        if not math.isfinite(head_value):
            lines.append(f"{path}: {key} is not finite")
            continue
        loosened = head_value > base_value if higher else head_value < base_value
        if loosened:
            lines.append(f"{path}: {key} {_format_ceiling(base_value)} -> {_format_ceiling(head_value)}")
    return lines


def findings(path: str, base_text: str, head_text: str) -> list[str]:
    """One line per loosened number. Identical text returns no lines."""
    if path not in {_ALWAYS_LOADED, _DECISION} or base_text == head_text:
        return []
    base_obj = _json_object(base_text)
    head_obj = _json_object(head_text)
    if (base_text.strip() and base_obj is None) or (head_text.strip() and head_obj is None):
        return [f"{path}: invalid ceiling document"]
    base_obj = base_obj or {}
    head_obj = head_obj or {}
    if path == _ALWAYS_LOADED:
        # bytes records the trimmed bundle. It is not a ceiling.
        return []
    scores_before = base_obj.get("scores") if isinstance(base_obj.get("scores"), dict) else {}
    scores_after = head_obj.get("scores") if isinstance(head_obj.get("scores"), dict) else {}
    before = {f"scores.{key}": float(value) for key, value in scores_before.items() if _is_number(value)}
    after = {f"scores.{key}": float(value) for key, value in scores_after.items() if _is_number(value)}
    lines = _loosened(path, before, after, higher=False)
    lines.extend(f"{path}: {key} removed" for key in sorted(set(before) - set(after)))
    if _is_number(head_obj.get("tolerance")):
        base_tolerance = float(base_obj["tolerance"]) if _is_number(base_obj.get("tolerance")) else 0.0
        lines.extend(
            _loosened(
                path,
                {"tolerance": base_tolerance},
                {"tolerance": float(head_obj["tolerance"])},
                higher=True,
            )
        )
    return lines


def _blob(root: Path, rev: str, path: str) -> str:
    completed = subprocess.run(
        ["git", "show", f"{rev}:{path}"],
        cwd=root,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    if completed.returncode == 0:
        return completed.stdout
    err = completed.stderr
    if "does not exist" in err or "exists on disk, but not in" in err:
        return ""
    raise RuntimeError(f"git could not read {rev}:{path}")


def compare(root: Path, base: str) -> list[str]:
    """Flag live ceilings that HEAD loosened against ``base``."""
    found: list[str] = []
    for path in (_ALWAYS_LOADED, _DECISION):
        head = (root / path).read_text(encoding="utf-8")
        found.extend(findings(path, _blob(root, base, path), head))
    return found


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--base", required=True, help="Git revision to compare, such as origin/main")
    parser.add_argument("--root", default=".", type=Path)
    args = parser.parse_args(argv)
    try:
        found = compare(args.root.resolve(), args.base)
    except (OSError, RuntimeError) as exc:
        print(str(exc), file=sys.stderr)
        return 1
    if found:
        print("\n".join(found), file=sys.stderr)
        return 1
    print("ceiling ratchet: pass")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
