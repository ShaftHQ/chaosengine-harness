#!/usr/bin/env python3
"""Parse, order and validate ChaosEngine version strings.

VERSION lives at the harness repository root. ``read``, ``broadcast`` and
``check`` use that file unless ``--path`` is passed.
"""
from __future__ import annotations

import argparse
import datetime as dt
import os
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
VERSION_PATH = ROOT / "VERSION"
# Commit-date scheme <major>.<YYYYMMDD>.<index> (index is 0-based on that UTC day).
# 0.<quarter>.<YYYYMMDD>.<n> and legacy YYYY.MM.DD[.N] still parse.
COMMIT_VERSION_RE = re.compile(r"^(?P<major>[1-9]\d*)\.(?P<date>\d{8})\.(?P<index>\d+)$")
NEW_VERSION_RE = re.compile(r"^(?P<major>\d+)\.(?P<quarter>[1-4])\.(?P<date>\d{8})\.(?P<n>[1-9]\d*)$")
LEGACY_VERSION_RE = re.compile(r"^(?P<y>\d{4})\.(?P<m>\d{2})\.(?P<d>\d{2})(?:\.(?P<ln>\d+))?$")
VERSION_RE = re.compile(
    r"^(?:[1-9]\d*\.\d{8}\.\d+|\d+\.[1-4]\.\d{8}\.[1-9]\d*|\d{4}\.\d{2}\.\d{2}(?:\.\d+)?)$"
)
_EMBEDDED_RE = re.compile(r'^_EMBEDDED_VERSION = "([^"]*)"', re.MULTILINE)


def _quarter_from_yyyymmdd(date_int: int) -> int:
    """Calendar quarter 1-4 derived from a YYYYMMDD stamp (Cairo calendar day)."""
    month = (date_int // 100) % 100
    if not 1 <= month <= 12:
        raise ValueError(f"invalid month in date stamp {date_int}")
    return (month - 1) // 3 + 1


def _validated_yyyymmdd(date_int: int) -> int:
    text = f"{date_int:08d}"
    year, month, day = int(text[:4]), int(text[4:6]), int(text[6:8])
    dt.date(year, month, day)
    return date_int


def version_key(value: str) -> tuple[int, int, int]:
    """Comparable key (major, date, n); quarter is derived from the date.

    Ordering by date (not the quarter field) keeps Q4 to Q1 year rollover correct:
    ``0.4.20261231.1`` < ``0.1.20270101.1``. A commit-date version such as
    ``1.20261126.0`` sorts by major, then the validated UTC day, then the index.
    """
    text = str(value).strip()
    commit = COMMIT_VERSION_RE.fullmatch(text)
    if commit:
        date_int = _validated_yyyymmdd(int(commit["date"]))
        return int(commit["major"]), date_int, int(commit["index"])
    new = NEW_VERSION_RE.fullmatch(text)
    if new:
        date_int = int(new["date"])
        declared = int(new["quarter"])
        derived = _quarter_from_yyyymmdd(date_int)
        if declared != derived:
            raise ValueError(
                f"CE version {text!r} quarter {declared} does not match date "
                f"(expected {derived})"
            )
        return int(new["major"]), date_int, int(new["n"])
    old = LEGACY_VERSION_RE.fullmatch(text)
    if old:
        date_int = int(old["y"] + old["m"] + old["d"])
        return 0, date_int, int(old["ln"] or 0)
    raise ValueError(f"invalid CE version {text!r}")


def next_version(current: str, merge_day: str) -> str:
    """Next version for ``merge_day`` (YYYY-MM-DD).

    A commit-date version keeps its major and bumps the 0-based index on the
    same day, or resets the index on a later day. A quarter or calendar
    version transitions to ``1.<YYYYMMDD>.0``.
    """
    day = dt.date.fromisoformat(merge_day)
    major, cur_date, cur_n = version_key(current)
    stamp = int(f"{day:%Y%m%d}")
    if stamp < cur_date:
        raise ValueError("merge day is before the current CE version date")
    text = current.strip()
    if COMMIT_VERSION_RE.fullmatch(text):
        if stamp == cur_date:
            return f"{major}.{stamp}.{cur_n + 1}"
        return f"{major}.{stamp}.0"
    return f"1.{stamp}.0"


def future_version_error(value: str, today: dt.date | None = None) -> str | None:
    """Reject a version dated later than ``today``.

    ``version_key`` still orders future stamps so Q4 to Q1 comparisons stay valid.
    ``check`` uses this function.
    """
    _major, date_int, _n = version_key(value)
    day = today or dt.date.today()
    stamp = int(f"{day:%Y%m%d}")
    if date_int > stamp:
        return (
            f"CE version {value!r} is dated {date_int}, after {stamp}. "
            "Never publish a future-dated ChaosEngine version."
        )
    return None


def read_version(path: Path | None = None) -> str:
    """Return the stripped VERSION string; raise ValueError if missing or invalid."""
    target = VERSION_PATH if path is None else Path(path)
    if not target.is_file():
        raise ValueError(f"missing VERSION file: {target}")
    value = target.read_text(encoding="utf-8").strip().splitlines()[0].strip()
    if VERSION_RE.fullmatch(value) is None or version_key(value)[0] < 0:
        raise ValueError(
            f"invalid VERSION {value!r}; expected <major>.<YYYYMMDD>.<index> "
            "or 0.<quarter>.<YYYYMMDD>.<n>"
        )
    return value


def embedded_version(root: Path | None = None) -> str:
    """Return ``_EMBEDDED_VERSION`` from ``bootstrap.py``."""
    base = ROOT if root is None else Path(root)
    text = (base / "bootstrap.py").read_text(encoding="utf-8")
    match = _EMBEDDED_RE.search(text)
    if match is None:
        raise ValueError("bootstrap.py is missing _EMBEDDED_VERSION")
    return match.group(1)


def _utc_day(timestamp: int) -> str:
    moment = dt.datetime.fromtimestamp(timestamp, dt.timezone.utc)
    return f"{moment:%Y%m%d}"


def is_shallow_repository(root: Path = ROOT) -> bool:
    """True for a shallow checkout, whose truncated log cannot index a day."""
    completed = subprocess.run(
        ["git", "-C", str(root), "rev-parse", "--is-shallow-repository"],
        capture_output=True,
        text=True,
        check=False,
    )
    return completed.returncode == 0 and completed.stdout.strip() == "true"


def derive_commit_version(root: Path = ROOT, *, major: int = 1, ref: str = "HEAD") -> str:
    """``<major>.<UTC YYYYMMDD>.<0-based first-parent index on that day>``."""
    if major < 1:
        raise ValueError("major must be >= 1")
    if is_shallow_repository(root):
        raise ValueError("shallow checkout has no reliable first-parent history")
    env = {**os.environ, "TZ": "UTC"}
    show = subprocess.run(
        ["git", "-C", str(root), "show", "-s", "--format=%ct", ref],
        capture_output=True,
        text=True,
        check=False,
        env=env,
    )
    if show.returncode != 0 or not show.stdout.strip():
        detail = (show.stderr or "git show failed").strip()
        raise ValueError(detail)
    target_day = _utc_day(int(show.stdout.strip()))
    log = subprocess.run(
        ["git", "-C", str(root), "log", "--first-parent", "--format=%ct", ref],
        capture_output=True,
        text=True,
        check=False,
        env=env,
    )
    if log.returncode != 0:
        raise ValueError((log.stderr or "git log failed").strip())
    same_day = 0
    for line in log.stdout.splitlines():
        if not line.strip():
            continue
        day = _utc_day(int(line.strip()))
        if day < target_day:
            break
        if day == target_day:
            same_day += 1
    index = same_day - 1
    if index < 0:
        raise ValueError(f"no commit on {target_day} for {ref}")
    return f"{major}.{target_day}.{index}"


def sync_version_files(root: Path, version: str) -> list[str]:
    """Write ``VERSION`` and ``bootstrap.py`` ``_EMBEDDED_VERSION`` to ``version``."""
    version_key(version)
    if VERSION_RE.fullmatch(version) is None:
        raise ValueError(f"invalid VERSION {version!r}")
    changed: list[str] = []
    base = Path(root)
    version_path = base / "VERSION"
    rendered = version + "\n"
    current = version_path.read_text(encoding="utf-8") if version_path.is_file() else ""
    if current != rendered:
        version_path.write_text(rendered, encoding="utf-8")
        changed.append("VERSION")
    bootstrap = base / "bootstrap.py"
    text = bootstrap.read_text(encoding="utf-8")
    updated, count = re.subn(
        r'^_EMBEDDED_VERSION = "[^"]*"',
        f'_EMBEDDED_VERSION = "{version}"',
        text,
        count=1,
        flags=re.MULTILINE,
    )
    if count != 1:
        raise ValueError("bootstrap.py is missing _EMBEDDED_VERSION")
    if updated != text:
        bootstrap.write_text(updated, encoding="utf-8")
        changed.append("bootstrap.py")
    return changed


def upgrade_broadcast(version: str | None = None) -> str:
    """Return the canonical broadcast string ``CE upgrade <version>``."""
    value = read_version() if version is None else version.strip()
    if VERSION_RE.fullmatch(value) is None:
        raise ValueError(f"invalid VERSION {value!r}")
    return f"CE upgrade {value}"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    read = sub.add_parser("read", help="print a VERSION file")
    read.add_argument("--path", type=Path, default=None)
    broadcast = sub.add_parser("broadcast", help="print CE upgrade <version>")
    broadcast.add_argument("--path", type=Path, default=None)
    check = sub.add_parser("check", help="validate VERSION file; exit 1 on failure")
    check.add_argument("--path", type=Path, default=None)
    derive = sub.add_parser("derive", help="print the commit-date version of a git ref")
    derive.add_argument("--major", type=int, default=1)
    derive.add_argument("--ref", default="HEAD")
    derive.add_argument("--root", type=Path, default=ROOT)
    sync = sub.add_parser("sync", help="write VERSION and _EMBEDDED_VERSION")
    sync.add_argument("--version", default="")
    sync.add_argument("--major", type=int, default=1)
    sync.add_argument("--ref", default="HEAD")
    sync.add_argument("--root", type=Path, default=ROOT)
    args = parser.parse_args(argv)
    try:
        if args.command == "read":
            print(read_version(args.path))
            return 0
        if args.command == "broadcast":
            print(upgrade_broadcast(read_version(args.path)))
            return 0
        if args.command == "derive":
            print(derive_commit_version(args.root, major=args.major, ref=args.ref))
            return 0
        if args.command == "sync":
            version = args.version.strip() or derive_commit_version(args.root, major=args.major, ref=args.ref)
            changed = sync_version_files(args.root, version)
            print(version if not changed else f"{version} ({', '.join(changed)})")
            return 0
        if args.command == "check":
            value = read_version(args.path)
            future = future_version_error(value)
            if future:
                raise ValueError(future)
            if args.path is None:
                embedded = embedded_version(ROOT)
                if embedded != value:
                    raise ValueError(
                        f"_EMBEDDED_VERSION {embedded!r} != VERSION {value!r}"
                    )
            print(f"ce_version: pass {value}")
            return 0
    except ValueError as exc:
        print(f"ce_version: {exc}", file=sys.stderr)
        return 1
    return 2


if __name__ == "__main__":
    sys.exit(main())
