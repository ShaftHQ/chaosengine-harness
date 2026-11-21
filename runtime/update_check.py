"""Report a newer ChaosEngine release. Apply it only after confirmation."""

from __future__ import annotations

import re
from pathlib import Path

_VERSION = re.compile(r"(\d+(?:\.\d+)+)")


def session_start_update_check(fetcher, installed_version, confirm: bool) -> str:
    """Return ``up-to-date``, ``unavailable``, ``newer:<version>``, or ``applied:<version>``.

    A fetcher failure is ``unavailable`` and writes nothing. A newer release is
    reported and written only when ``confirm`` is true and the payload names files.
    """
    try:
        payload = fetcher()
    except Exception:
        return "unavailable"
    version, root, files = _payload(payload)
    if not _is_newer(version, str(installed_version or "")):
        return "up-to-date"
    if not confirm:
        return "newer:" + version
    _apply_files(root, files)
    return "applied:" + version


def _payload(payload: object) -> tuple[str, object, dict]:
    if isinstance(payload, str):
        return payload.strip(), None, {}
    if isinstance(payload, dict):
        version = str(payload.get("version") or payload.get("tag_name") or "").strip()
        if version[:1].casefold() == "v" and version[1:2].isdigit():
            version = version[1:]
        files = payload.get("files")
        return version, payload.get("root"), files if isinstance(files, dict) else {}
    return "", None, {}


def _version_key(value: str) -> tuple[int, ...] | None:
    match = _VERSION.search(value or "")
    if match is None:
        return None
    return tuple(int(part) for part in match.group(1).split("."))


def _is_newer(latest: str, installed: str) -> bool:
    new = _version_key(latest)
    old = _version_key(installed)
    if new is None or old is None:
        return False
    return new > old


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
