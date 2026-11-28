#!/usr/bin/env python3
"""Export and import learned heuristics and repeat-failure notes.

Derived indexes (graphify-out, mempalace) are not part of the bundle.
A secret-pattern hit refuses the write. Client-name denylist tokens are scrubbed.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess  # nosec B404 - fixed git argv, no shell.
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from runtime.client_name_scrub import load_denylist  # noqa: E402
from runtime.heuristics import load_index  # noqa: E402
from runtime.memory_provenance import filter_retrievable  # noqa: E402
from runtime.secret_guard import ASSIGNMENT, TOKEN  # noqa: E402

SCHEMA_VERSION = 1
HEURISTICS_RELATIVE = Path(".chaos-engine-state") / "heuristics" / "index.json"
NOTES_DIRNAME = "repeat-failure-pdca"
OMITTED = ("graphify-out", "mempalace")


class SecretHit(Exception):
    """The bundle matched a secret pattern. Nothing was written."""


def _secret_hit(text: str) -> bool:
    data = text.encode("utf-8", errors="replace")
    if TOKEN.search(data):
        return True
    return any(
        re.search(rb"\d", match.group(2)) and re.search(rb"[A-Za-z]", match.group(2))
        for match in ASSIGNMENT.finditer(data)
    )


def _scrub(value: Any, tokens: tuple[str, ...]) -> Any:
    if isinstance(value, str):
        scrubbed = value
        for token in tokens:
            scrubbed = re.compile(re.escape(token), re.IGNORECASE).sub("[redacted-client]", scrubbed)
        return scrubbed
    if isinstance(value, list):
        return [_scrub(item, tokens) for item in value]
    if isinstance(value, dict):
        return {str(key): _scrub(item, tokens) for key, item in value.items()}
    return value


def _version(project: Path) -> str:
    path = project / "VERSION"
    if not path.is_file():
        path = ROOT / "VERSION"
    if not path.is_file():
        return "unknown"
    return path.read_text(encoding="utf-8").strip() or "unknown"


def _source_sha(project: Path) -> str:
    completed = subprocess.run(  # nosec B603
        ["git", "-C", str(project), "rev-parse", "HEAD"],
        capture_output=True,
        text=True,
        check=False,
    )
    sha = (completed.stdout or "").strip()
    if completed.returncode != 0 or not sha:
        return "unknown"
    return sha


def _notes(project: Path) -> dict[str, Any]:
    directory = project / ".chaos-engine-state" / NOTES_DIRNAME
    found: dict[str, Any] = {}
    if not directory.is_dir():
        return found
    for path in sorted(directory.glob("*.json")):
        try:
            document = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError):
            continue
        if isinstance(document, dict):
            found[path.name] = document
    return found


def heuristic_hits(project: Path, query: str) -> list[str]:
    """Retrievable heuristic ids whose text contains query. Quarantine stays out."""
    items = load_index(project).get("items") or []
    needle = query.casefold()
    hits = []
    for item in filter_retrievable(items if isinstance(items, list) else []):
        if needle in str(item.get("text") or "").casefold():
            hits.append(str(item.get("id") or ""))
    return sorted(item for item in hits if item)


def build_bundle(project: Path) -> dict[str, Any]:
    """Learned state only. graphify-out and mempalace are not read."""
    project = Path(project)
    bundle = {
        "schema_version": SCHEMA_VERSION,
        "version": _version(project),
        "source_sha": _source_sha(project),
        "heuristics": load_index(project),
        "repeat_failure_notes": _notes(project),
    }
    for name in OMITTED:
        if name in bundle:
            raise RuntimeError(f"{name} must not be exported")
    return bundle


def export_bundle(project: Path, out: Path, *, environ: dict[str, str] | None = None) -> dict[str, Any]:
    bundle = build_bundle(project)
    tokens = load_denylist(project, environ=environ)
    scrubbed = _scrub(bundle, tokens)
    payload = json.dumps(scrubbed, indent=2, sort_keys=True) + "\n"
    raw = json.dumps(bundle, sort_keys=True)
    if _secret_hit(raw) or _secret_hit(payload):
        raise SecretHit("export refused: secret pattern")
    for name in OMITTED:
        if f'"{name}"' in payload:
            raise SecretHit(f"export refused: {name} leaked into the bundle")
    out = Path(out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(payload, encoding="utf-8")
    return scrubbed


def import_bundle(project: Path, bundle_path: Path) -> dict[str, Any]:
    """Restore heuristics and notes. Trust is not promoted."""
    text = Path(bundle_path).read_text(encoding="utf-8")
    if _secret_hit(text):
        raise SecretHit("import refused: secret pattern")
    document = json.loads(text)
    if not isinstance(document, dict) or document.get("schema_version") != SCHEMA_VERSION:
        raise ValueError("unsupported state bundle")
    for name in OMITTED:
        if name in document:
            raise ValueError(f"{name} is not importable")
    heuristics = document.get("heuristics")
    if not isinstance(heuristics, dict):
        raise ValueError("heuristics must be an object")
    project = Path(project)
    index = project / HEURISTICS_RELATIVE
    index.parent.mkdir(parents=True, exist_ok=True)
    index.write_text(json.dumps(heuristics, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    notes = document.get("repeat_failure_notes") or {}
    if not isinstance(notes, dict):
        raise ValueError("repeat_failure_notes must be an object")
    directory = project / ".chaos-engine-state" / NOTES_DIRNAME
    directory.mkdir(parents=True, exist_ok=True)
    for name, note in notes.items():
        if not isinstance(note, dict) or "/" in name or name.startswith("."):
            raise ValueError("invalid note name")
        (directory / name).write_text(json.dumps(note, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return document


def main(arguments: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    export_parser = sub.add_parser("export")
    export_parser.add_argument("--out", required=True, type=Path)
    export_parser.add_argument("--project", type=Path, default=None)
    import_parser = sub.add_parser("import")
    import_parser.add_argument("file", type=Path)
    import_parser.add_argument("--project", type=Path, default=None)
    args = parser.parse_args(arguments)
    project = args.project or Path.cwd()
    try:
        if args.command == "export":
            export_bundle(project, args.out)
        else:
            import_bundle(project, args.file)
    except (SecretHit, ValueError, OSError) as exc:
        print(str(exc), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
