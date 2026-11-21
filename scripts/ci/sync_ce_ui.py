#!/usr/bin/env python3
"""Inline runtime/ce_ui.py into bootstrap.py between the generated markers."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / "runtime" / "ce_ui.py"
TARGET = ROOT / "bootstrap.py"
START = "# >>> generated: ce_ui\n"
END = "# <<< generated: ce_ui\n"


def payload_text(source: Path | None = None) -> str:
    text = (source or SOURCE).read_text(encoding="utf-8")
    if text.startswith("#!"):
        text = text.split("\n", 1)[1]
    if not text.endswith("\n"):
        text += "\n"
    return text


def splice(bootstrap: str, payload: str) -> str:
    if START not in bootstrap or END not in bootstrap:
        raise SystemExit("bootstrap.py is missing the ce_ui markers")
    start = bootstrap.index(START)
    end = bootstrap.index(END)
    if end < start:
        raise SystemExit("ce_ui markers are out of order")
    return bootstrap[:start] + START + payload + END + bootstrap[end + len(END) :]


def matches(target: Path | None = None, source: Path | None = None) -> bool:
    target = target or TARGET
    original = target.read_text(encoding="utf-8")
    return splice(original, payload_text(source)) == original


def rewrite(target: Path | None = None, source: Path | None = None) -> bool:
    target = target or TARGET
    original = target.read_text(encoding="utf-8")
    updated = splice(original, payload_text(source))
    if updated == original:
        return False
    target.write_text(updated, encoding="utf-8")
    return True


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="exit 1 when the inline copy differs")
    args = parser.parse_args(argv)
    if args.check:
        if not matches():
            print("ce_ui inline drift: run python3 scripts/ci/sync_ce_ui.py", file=sys.stderr)
            return 1
        return 0
    print("updated" if rewrite() else "unchanged")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
