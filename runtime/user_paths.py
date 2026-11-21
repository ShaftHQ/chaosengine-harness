"""One resolver for ChaosEngine config, data, state, and cache directories.

Linux and macOS config stay under ``~/.config`` (``delete_guard`` already reads
that tree). Data, state, and cache use the platform directories. An existing
tree at the previous Linux-style path is kept in place; nothing is moved here.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path


def _windows() -> bool:
    return os.name == "nt"


def _darwin() -> bool:
    return sys.platform == "darwin"


def _expand(value: str) -> Path:
    return Path(os.path.expandvars(os.path.expanduser(value)))


def home_dir() -> Path:
    """Host home. ``CHAOS_ENGINE_USER_HOME`` isolates a test or a contract cell."""
    override = os.environ.get("CHAOS_ENGINE_USER_HOME", "").strip()
    if override:
        return _expand(override)
    return Path.home()


def config_dir() -> Path:
    """User config directory. ``CHAOS_ENGINE_CONFIG_HOME`` replaces the default."""
    override = os.environ.get("CHAOS_ENGINE_CONFIG_HOME", "").strip()
    if override:
        return _expand(override)
    if _windows():
        base = os.environ.get("APPDATA", "").strip()
        root = _expand(base) if base else Path.home() / "AppData" / "Roaming"
        return root / "chaos-engine"
    if _darwin():
        return Path.home() / ".config" / "chaos-engine"
    xdg = os.environ.get("XDG_CONFIG_HOME", "").strip()
    root = _expand(xdg) if xdg else Path.home() / ".config"
    return root / "chaos-engine"


def data_dir() -> Path:
    """User data directory. ``CHAOS_ENGINE_USER_DIR`` replaces the default."""
    override = os.environ.get("CHAOS_ENGINE_USER_DIR", "").strip()
    if override:
        return _expand(override)
    if _windows():
        base = os.environ.get("LOCALAPPDATA", "").strip()
        root = _expand(base) if base else Path.home() / "AppData" / "Local"
        return root / "chaos-engine"
    if _darwin():
        return Path.home() / "Library" / "Application Support" / "chaos-engine"
    xdg = os.environ.get("XDG_DATA_HOME", "").strip()
    root = _expand(xdg) if xdg else Path.home() / ".local" / "share"
    return root / "chaos-engine"


def state_dir() -> Path:
    """User state directory. ``CHAOS_ENGINE_STATE_DIR`` replaces the default."""
    override = os.environ.get("CHAOS_ENGINE_STATE_DIR", "").strip()
    if override:
        return _expand(override)
    if _windows():
        base = os.environ.get("LOCALAPPDATA", "").strip()
        root = _expand(base) if base else Path.home() / "AppData" / "Local"
        return root / "chaos-engine" / "state"
    if _darwin():
        return Path.home() / "Library" / "Application Support" / "chaos-engine" / "state"
    xdg = os.environ.get("XDG_STATE_HOME", "").strip()
    root = _expand(xdg) if xdg else Path.home() / ".local" / "state"
    return root / "chaos-engine"


def cache_dir() -> Path:
    """User cache directory. ``CHAOS_ENGINE_CACHE_DIR`` replaces the default."""
    override = os.environ.get("CHAOS_ENGINE_CACHE_DIR", "").strip()
    if override:
        return _expand(override)
    if _windows():
        base = os.environ.get("LOCALAPPDATA", "").strip()
        root = _expand(base) if base else Path.home() / "AppData" / "Local"
        return root / "chaos-engine" / "cache"
    if _darwin():
        return Path.home() / "Library" / "Caches" / "chaos-engine"
    xdg = os.environ.get("XDG_CACHE_HOME", "").strip()
    root = _expand(xdg) if xdg else Path.home() / ".cache"
    return root / "chaos-engine"


def legacy_config_dir() -> Path:
    return Path.home() / ".config" / "chaos-engine"


def legacy_data_dir() -> Path:
    return Path.home() / ".local" / "share" / "chaos-engine"


def legacy_state_dir() -> Path:
    return Path.home() / ".local" / "state" / "chaos-engine"


def download_cache_dir() -> Path:
    """Artifact cache. Linux stays ``~/.cache/chaos-engine/downloads``.

    Windows used to put downloads directly under ``%LOCALAPPDATA%\\chaos-engine``.
    That tree is still read when it is the one that exists.
    """
    preferred = cache_dir() / "downloads"
    if _windows() and not os.environ.get("CHAOS_ENGINE_CACHE_DIR", "").strip():
        base = os.environ.get("LOCALAPPDATA", "").strip()
        root = _expand(base) if base else Path.home() / "AppData" / "Local"
        return prefer_existing(preferred, root / "chaos-engine" / "downloads")
    return preferred


def prefer_existing(preferred: Path, legacy: Path) -> Path:
    """Use ``legacy`` when it already exists and ``preferred`` does not."""
    if preferred == legacy:
        return preferred
    try:
        if legacy.exists() and not preferred.exists():
            return legacy
    except OSError:
        return preferred
    return preferred
