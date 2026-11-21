"""Session-start release check.

Never downloads a release and never rewrites the installed tree. A caller that
passes ``confirm`` and ``apply`` is the only path that can apply an update.
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable
from pathlib import Path

_RELEASE = "https://api.github.com/repos/ShaftHQ/chaosengine-harness/releases/latest"
_VERSION = re.compile(r"^v?(\d+)\.(\d+)\.(\d+)(?:\.(\d+))?$")


def _parts(value: str) -> tuple[int, ...] | None:
    match = _VERSION.fullmatch(value.strip())
    if match is None:
        return None
    return tuple(int(part) for part in match.groups() if part is not None)


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


def session_start_update_check(
    *,
    fetcher: Callable[[], str] | None = None,
    installed: str | None = None,
    confirm: bool = False,
    apply: Callable[[str], None] | None = None,
    version_file: Path | None = None,
) -> str:
    """Report whether a newer ChaosEngine release exists.

    ``up-to-date`` leaves the installed version untouched. A failed fetch
    returns ``update check failed`` and does not raise. ``apply`` runs only
    when ``confirm`` is true and the remote version is newer.
    """
    current = installed if installed is not None else _installed_text(version_file)
    try:
        remote = (fetcher or _default_fetcher)().strip()
        current_parts = _parts(current)
        remote_parts = _parts(remote)
        if current_parts is None or remote_parts is None:
            raise ValueError("unreadable version")
    except Exception:
        return "update check failed"
    if remote_parts <= current_parts:
        return "up-to-date"
    if not confirm or apply is None:
        return f"update available: {remote}"
    try:
        apply(remote)
    except Exception:
        return "update check failed"
    return f"update confirmed: {remote}"
