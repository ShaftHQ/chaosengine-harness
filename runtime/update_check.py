"""Session-start release check.

A newer release is reported and left unapplied until the caller confirms.
A failed fetch does not raise and does not change files.
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable
from pathlib import Path

_RELEASE = "https://api.github.com/repos/ShaftHQ/chaosengine-harness/releases/latest"
_VERSION = re.compile(r"^v?(\d+(?:\.\d+)*)$")


def _parts(value: str) -> tuple[int, ...] | None:
    match = _VERSION.fullmatch(value.strip())
    if match is None:
        return None
    return tuple(int(part) for part in match.group(1).split("."))


def _installed_text(version_file: Path | None) -> str:
    path = version_file or Path(__file__).resolve().parents[1] / "VERSION"
    try:
        return path.read_text(encoding="utf-8").strip()
    except OSError:
        return ""


def _default_fetcher() -> str:
    import urllib.request

    request = urllib.request.Request(
        _RELEASE,
        headers={
            "Accept": "application/vnd.github+json",
            "User-Agent": "chaosengine-update-check",
        },
    )
    with urllib.request.urlopen(request, timeout=5) as response:  # nosec B310 - fixed GitHub releases URL
        payload = json.loads(response.read().decode("utf-8"))
    tag = payload.get("tag_name") if isinstance(payload, dict) else None
    if not isinstance(tag, str) or not tag.strip():
        raise ValueError("release tag missing")
    return tag.strip()


def _parsed(payload: object) -> tuple[str, object, dict]:
    if isinstance(payload, str):
        return payload.strip(), None, {}
    if isinstance(payload, dict):
        version = str(payload.get("version") or payload.get("tag_name") or "").strip()
        files = payload.get("files")
        return version, payload.get("root"), files if isinstance(files, dict) else {}
    return "", None, {}


def _apply_files(root: object, files: dict) -> None:
    if not root or not files:
        return
    base = Path(str(root)).resolve()
    if not base.is_dir():
        return
    for name, content in files.items():
        relative = Path(str(name))
        if relative.is_absolute() or any(part == ".." for part in relative.parts):
            continue
        target = (base / relative).resolve()
        try:
            target.relative_to(base)
        except ValueError:
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(str(content), encoding="utf-8")


def session_start_update_check(
    fetcher: Callable[[], object] | None = None,
    installed_version: str | None = None,
    confirm: bool = False,
    *,
    installed: str | None = None,
    apply: Callable[[str], None] | None = None,
    version_file: Path | None = None,
) -> str:
    """Report whether a newer ChaosEngine release exists.

    ``up-to-date`` leaves files untouched. A failed fetch returns
    ``update check failed``. ``update confirmed`` is returned only after
    ``apply`` runs or a confirmed payload's files are written.
    """
    current = installed if installed is not None else installed_version
    if current is None:
        current = _installed_text(version_file)
    try:
        payload = (fetcher or _default_fetcher)()
        remote, root, files = _parsed(payload)
        current_parts = _parts(str(current))
        remote_parts = _parts(remote)
        if current_parts is None or remote_parts is None:
            raise ValueError("unreadable version")
    except Exception:
        return "update check failed"
    if remote_parts <= current_parts:
        return "up-to-date"
    if not confirm:
        return f"update available: {remote}"
    try:
        if apply is not None:
            apply(remote)
        elif files:
            _apply_files(root, files)
        else:
            return f"update available: {remote}"
    except Exception:
        return "update check failed"
    return f"update confirmed: {remote}"
