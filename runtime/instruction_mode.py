"""Merge inventory and confirmed replace for existing instruction files (#116)."""

from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import zipfile
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
INVENTORY_PATH = ROOT / "references" / "instruction-inventory.json"
CONFLICTS_PATH = ROOT / "references" / "instruction-conflicts.json"
STATE_DIR = ".chaos-engine-state"
INVENTORY_NAME = "instruction-inventory.json"
REPORT_NAME = "instruction-merge-report.md"
BACKUP_ROOT = "backups"
CE_SKILL_NAMES = {"chaos-engine", "chaos-engine-user"}
FENCE = re.compile(r"(?ms)^```.*?^```\s*")
OWNED_START = "<!-- CHAOSENGINE:START -->"
OWNED_END = "<!-- CHAOSENGINE:END -->"
OWNED_SPAN = re.compile(
    re.escape(OWNED_START) + r".*?" + re.escape(OWNED_END) + r"\n?",
    re.DOTALL,
)
CODEX_CAP = 32 * 1024
CLAUDE_LINE_CAP = 200


class ReplaceRefusal(RuntimeError):
    """A replace that must stop before it writes or deletes."""

    def __init__(self, code: str, exit_code: int = 2) -> None:
        super().__init__(code)
        self.code = code
        self.exit_code = exit_code


def _load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def inventory_document() -> dict:
    return _load(INVENTORY_PATH)


def conflict_document() -> dict:
    return _load(CONFLICTS_PATH)


def _glob_match(relative: str, pattern: str) -> bool:
    path = Path(relative)
    if path.match(pattern):
        return True
    parts = pattern.split("/")
    rel_parts = relative.split("/")
    return _parts_match(rel_parts, parts)


def _parts_match(rel: list[str], pattern: list[str]) -> bool:
    if not pattern:
        return not rel
    head, rest = pattern[0], pattern[1:]
    if head == "**":
        if _parts_match(rel, rest):
            return True
        return bool(rel) and _parts_match(rel[1:], pattern)
    if not rel:
        return False
    if Path(rel[0]).match(head):
        return _parts_match(rel[1:], rest)
    return False


def _ignored(relative: str) -> bool:
    name = Path(relative).name
    if name in CE_SKILL_NAMES or f"/{name}/" in f"/{relative}/" and name in CE_SKILL_NAMES:
        return False
    parts = Path(relative).parts
    if "skills" in parts:
        index = parts.index("skills")
        if index + 1 < len(parts) and parts[index + 1] in CE_SKILL_NAMES:
            return True
    if relative.startswith(".git/") or relative == ".git" or "/.git/" in f"/{relative}":
        return True
    if relative.startswith(f"{STATE_DIR}/"):
        return True
    return False


def _walk(project: Path) -> list[str]:
    found: list[str] = []
    if not project.is_dir():
        return found
    for path in project.rglob("*"):
        if not path.is_file() or path.is_symlink():
            continue
        relative = path.relative_to(project).as_posix()
        if ".git/" in f"{relative}/" or relative.startswith(".git"):
            continue
        found.append(relative)
    return found


def _class_for(relative: str, document: dict) -> tuple[str, str] | None:
    if _ignored(relative):
        return None
    for row in document.get("class_p", []):
        if _glob_match(relative, str(row["glob"])):
            return "P", str(row["host"])
    local_name = Path(relative).name
    if local_name.endswith(".local.toml") or local_name.endswith(".local.json"):
        return "P", "cross"
    for row in document.get("class_i", []):
        if _glob_match(relative, str(row["glob"])):
            return "I", str(row["host"])
    for row in document.get("unmanaged", []):
        if _glob_match(relative, str(row["glob"])):
            return "unmanaged", str(row["host"])
    return None


def classify(project: Path) -> list[dict[str, object]]:
    document = inventory_document()
    rows: list[dict[str, object]] = []
    for relative in sorted(_walk(project)):
        found = _class_for(relative, document)
        if found is None:
            continue
        kind, host = found
        path = project / relative
        data = path.read_bytes()
        rows.append(
            {
                "path": relative,
                "host": host,
                "class": kind,
                "size": len(data),
                "sha256": hashlib.sha256(data).hexdigest(),
                "git_tracked": _tracked(project, relative),
            }
        )
    return rows


def _tracked(project: Path, relative: str) -> bool:
    if not (project / ".git").exists():
        return False
    completed = subprocess.run(
        ["git", "ls-files", "--error-unmatch", "--", relative],
        cwd=project,
        capture_output=True,
        text=True,
        check=False,
    )
    return completed.returncode == 0


def write_inventory(project: Path) -> Path:
    destination = project / STATE_DIR / INVENTORY_NAME
    destination.parent.mkdir(parents=True, exist_ok=True)
    payload = {"files": classify(project)}
    text = json.dumps(payload, indent=2, sort_keys=True) + "\n"
    if destination.is_file() and destination.read_text(encoding="utf-8") == text:
        return destination
    destination.write_text(text, encoding="utf-8")
    return destination


def _outside_fences(text: str) -> str:
    return FENCE.sub("", text.replace("\r\n", "\n"))


def _outside_owned(text: str) -> str:
    """Drop the ChaosEngine primary block. Its own wording is not a conflict."""
    return OWNED_SPAN.sub("", text)


def conflicts(project: Path) -> list[dict[str, str]]:
    rules = conflict_document().get("rules", [])
    found: list[dict[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for row in classify(project):
        if row["class"] not in {"I", "P", "unmanaged"}:
            continue
        relative = str(row["path"])
        path = project / relative
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        visible = _outside_owned(_outside_fences(text))
        for rule in rules:
            if re.search(str(rule["regex"]), visible):
                key = (str(rule["id"]), relative)
                if key in seen:
                    continue
                seen.add(key)
                found.append(
                    {
                        "id": str(rule["id"]),
                        "path": relative,
                        "rule": str(rule["rule"]),
                        "fix": str(rule["fix"]),
                    }
                )
        if row["class"] == "I" and len(text.encode("utf-8")) > CODEX_CAP:
            found.append({"id": "IC-08", "path": relative, "rule": "Context budget", "fix": "Shorten the file."})
        elif row["class"] == "I" and text.count("\n") + 1 > CLAUDE_LINE_CAP:
            found.append({"id": "IC-08", "path": relative, "rule": "Context budget", "fix": "Shorten the file."})
        if relative in {"CLAUDE.md", "GEMINI.md"} and not text.startswith("@AGENTS.md"):
            found.append(
                {
                    "id": "IC-09",
                    "path": relative,
                    "rule": "One policy source",
                    "fix": "Point the file at @AGENTS.md.",
                }
            )
    return found


def write_report(project: Path) -> Path:
    rows = classify(project)
    found = conflicts(project)
    kept = sum(1 for row in rows if row["class"] in {"I", "P"})
    lines = [
        f"instructions: kept {kept} files, {len(found)} possible conflicts",
        "",
    ]
    for item in found:
        lines.append(f"- {item['id']} {item['path']}: {item['rule']} {item['fix']}")
    if not found:
        lines.append("No conflicts.")
    destination = project / STATE_DIR / REPORT_NAME
    destination.parent.mkdir(parents=True, exist_ok=True)
    text = "\n".join(lines) + "\n"
    if not destination.is_file() or destination.read_text(encoding="utf-8") != text:
        destination.write_text(text, encoding="utf-8")
    return destination


def doctor_row(project: Path) -> dict[str, object]:
    found = conflicts(project) if project.is_dir() else []
    return {"status": "warn" if found else "pass", "conflicts": len(found), "items": found}


def _git(project: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", "-C", str(project), *args],
        capture_output=True,
        text=True,
        check=False,
    )


def source_tree_kind(project: Path) -> str | None:
    if (project / "runtime" / "hosts.py").is_file() and (project / "install.py").is_file():
        return "harness"
    nested = project / "chaos-engine"
    if (nested / "runtime" / "hosts.py").is_file() or (nested / "hosts.py").is_file():
        return "harness"
    if (project / ".git").exists():
        origin = _git(project, "config", "--get", "remote.origin.url").stdout.strip()
        if "SHAFT_ENGINE" in origin:
            return "shaft"
    if (project / "shaft-engine" / "pom.xml").is_file() and (project / "pom.xml").is_file():
        return "shaft"
    return None


def _dirty_class_i(project: Path, rows: list[dict[str, object]]) -> list[str]:
    if not (project / ".git").exists():
        return []
    dirty: list[str] = []
    for row in rows:
        if row["class"] != "I":
            continue
        relative = str(row["path"])
        status = _git(project, "status", "--porcelain", "--", relative).stdout.strip()
        if status:
            dirty.append(relative)
    return dirty


def _targets(project: Path, *, include_local: bool) -> list[dict[str, object]]:
    rows = classify(project)
    selected = []
    for row in rows:
        if row["class"] == "I" or (include_local and row["class"] == "P"):
            selected.append(row)
    return selected


def plan_replace(project: Path, *, include_local: bool = False) -> list[str]:
    return [str(row["path"]) for row in _targets(project, include_local=include_local)]


def _stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _backup_dir(project: Path, stamp: str) -> Path:
    return project / STATE_DIR / BACKUP_ROOT / f"{stamp}-replace"


def _guard_targets(project: Path, paths: list[str]) -> None:
    from runtime.delete_guard import never_touch

    for relative in paths:
        hit = never_touch(project / relative)
        if hit:
            raise ReplaceRefusal(f"CE_DELETE_GUARD {hit}")


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def begin_replace(
    project: Path,
    *,
    yes: bool,
    dry_run: bool,
    consumer: bool,
    scope: str,
    allow_dirty: bool,
    force_source: bool,
    include_local: bool,
) -> dict[str, object]:
    """Backup and delete class I files, or return a dry-run plan. Writes nothing on refusal."""
    project = Path(project)
    if scope == "user":
        raise ReplaceRefusal("CE_MODE_SCOPE_CONFLICT")
    if consumer:
        raise ReplaceRefusal("CE_MODE_CONSUMER_CONFLICT")
    kind = source_tree_kind(project)
    if kind and not force_source:
        raise ReplaceRefusal("CE_MODE_REPLACE_SOURCE_TREE")
    rows = _targets(project, include_local=include_local)
    paths = [str(row["path"]) for row in rows]
    if dry_run:
        return {"status": "dry-run", "delete": paths, "wrote": False}
    if not yes:
        if not os.isatty(0):
            raise ReplaceRefusal("CE_MODE_REPLACE_NEEDS_YES")
        print("Type replace to continue.", flush=True)
        if input().strip() != "replace":
            raise ReplaceRefusal("CE_MODE_REPLACE_NEEDS_YES")
    dirty = _dirty_class_i(project, rows)
    if dirty and not allow_dirty:
        raise ReplaceRefusal("CE_MODE_REPLACE_DIRTY")
    _guard_targets(project, paths)
    stamp = _stamp()
    destination = _backup_dir(project, stamp)
    destination.mkdir(parents=True, exist_ok=False)
    manifest_files = []
    for relative in paths:
        path = project / relative
        data = path.read_bytes()
        stored = destination / "files" / relative
        stored.parent.mkdir(parents=True, exist_ok=True)
        stored.write_bytes(data)
        manifest_files.append(
            {
                "path": relative,
                "sha256": _sha256(data),
                "size": len(data),
                "mode": path.stat().st_mode & 0o777,
                "git_tracked": _tracked(project, relative),
            }
        )
        if _sha256(stored.read_bytes()) != manifest_files[-1]["sha256"]:
            raise ReplaceRefusal("CE_MODE_REPLACE_BACKUP")
    before = sorted(_walk(project))
    manifest = {"stamp": stamp, "files": manifest_files, "before": before, "created": []}
    (destination / "manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    archive = destination / "backup.zip"
    with zipfile.ZipFile(archive, "w") as handle:
        for relative in paths:
            handle.write(destination / "files" / relative, relative)
    for relative in paths:
        (project / relative).unlink()
    return {"status": "replaced", "stamp": f"{stamp}-replace", "delete": paths, "wrote": True}


def note_created(project: Path, stamp: str, created: list[str]) -> None:
    destination = project / STATE_DIR / BACKUP_ROOT / stamp
    path = destination / "manifest.json"
    manifest = json.loads(path.read_text(encoding="utf-8"))
    manifest["created"] = sorted(set(created))
    path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def list_backups(project: Path) -> list[str]:
    root = project / STATE_DIR / BACKUP_ROOT
    if not root.is_dir():
        return []
    return sorted(path.name for path in root.iterdir() if path.is_dir() and path.name.endswith("-replace"))


def relative_files(project: Path) -> list[str]:
    return _walk(project)


def restore(project: Path, stamp: str, *, dry_run: bool = False) -> dict[str, object]:
    destination = project / STATE_DIR / BACKUP_ROOT / stamp
    manifest = json.loads((destination / "manifest.json").read_text(encoding="utf-8"))
    if dry_run:
        return {"status": "dry-run", "stamp": stamp, "files": [item["path"] for item in manifest["files"]]}
    for relative in manifest.get("created", []):
        path = project / relative
        if path.is_file() and not path.is_symlink():
            path.unlink()
    for item in manifest["files"]:
        relative = str(item["path"])
        source = destination / "files" / relative
        target = project / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(source.read_bytes())
        os.chmod(target, int(item["mode"]))
    return {"status": "restored", "stamp": stamp}
