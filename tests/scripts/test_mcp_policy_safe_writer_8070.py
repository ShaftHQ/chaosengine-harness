"""mcp_policy host-config rewrites use the #8070 safe writer."""

from __future__ import annotations

import importlib.util
import json
import os
import sys
import tomllib
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
_spec = importlib.util.spec_from_file_location("ce_mcp_policy_8070", ROOT / "mcp_policy.py")
mp = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = mp
_spec.loader.exec_module(mp)

GROK_WITH_GITHUB = (
    'model = "fast"\n'
    "\n"
    "[mcp_servers.github]\n"
    'command = "github-mcp"\n'
    "\n"
    "[mcp_servers.other]\n"
    'command = "other"\n'
    "\n"
    "[[marketplace.sources]]\n"
    'name = "example"\n'
)


def _home(tmp_path: Path, monkeypatch) -> Path:
    home = tmp_path / "home"
    (home / ".grok").mkdir(parents=True)
    for var in ("GROK_HOME", "CODEX_HOME", "CLAUDE_CONFIG", "GEMINI_HOME", "COPILOT_HOME", "XDG_CONFIG_HOME"):
        monkeypatch.delenv(var, raising=False)
    return home


def test_github_strip_keeps_other_tables_and_parses(tmp_path, monkeypatch):
    home = _home(tmp_path, monkeypatch)
    config = home / ".grok" / "config.toml"
    config.write_text(GROK_WITH_GITHUB, encoding="utf-8")
    result = mp.repair_user_github_mcp(home, gh_healthy=True)
    assert result["stripped"] == [{"host": "grok", "path": str(config), "ids": ["github"]}]
    data = tomllib.loads(config.read_text(encoding="utf-8"))
    assert "github" not in data["mcp_servers"]
    assert data["mcp_servers"]["other"] == {"command": "other"}
    assert data["marketplace"]["sources"] == [{"name": "example"}]


def test_github_strip_crash_before_rename_leaves_the_original(tmp_path, monkeypatch):
    home = _home(tmp_path, monkeypatch)
    config = home / ".grok" / "config.toml"
    config.write_text(GROK_WITH_GITHUB, encoding="utf-8")
    writer = mp._safe_writer()
    glc = sys.modules[writer.__module__]

    def boom(*_args, **_kwargs):
        raise OSError("simulated crash between temp write and rename")

    monkeypatch.setattr(glc.os, "replace", boom)
    with pytest.raises(OSError):
        mp.repair_user_github_mcp(home, gh_healthy=True)
    assert config.read_text(encoding="utf-8") == GROK_WITH_GITHUB
    assert [p.name for p in config.parent.iterdir() if p.suffix == ".tmp"] == []


@pytest.mark.skipif(os.name == "nt", reason="symlinks need privileges on Windows")
def test_symlinked_host_config_is_edited_at_its_target(tmp_path, monkeypatch):
    home = _home(tmp_path, monkeypatch)
    target = tmp_path / "dotfiles" / "grok.toml"
    target.parent.mkdir()
    target.write_text(GROK_WITH_GITHUB, encoding="utf-8")
    link = home / ".grok" / "config.toml"
    link.symlink_to(target)
    mp.repair_user_github_mcp(home, gh_healthy=True)
    assert link.is_symlink()
    assert "github" not in tomllib.loads(target.read_text(encoding="utf-8"))["mcp_servers"]


def test_tripwire_refuses_mcp_policy_writes_under_the_protected_home(tmp_path, monkeypatch):
    home = _home(tmp_path, monkeypatch)
    config = home / ".grok" / "config.toml"
    config.write_text(GROK_WITH_GITHUB, encoding="utf-8")
    monkeypatch.setenv("CHAOS_ENGINE_PROTECTED_GROK_HOME", str(home / ".grok"))
    monkeypatch.delenv("CHAOS_ENGINE_PROTECTED_GROK_HOME_LOG", raising=False)
    with pytest.raises(OSError):
        mp.repair_user_github_mcp(home, gh_healthy=True)
    assert config.read_text(encoding="utf-8") == GROK_WITH_GITHUB


def test_nothing_to_strip_creates_no_lock_file(tmp_path, monkeypatch):
    home = _home(tmp_path, monkeypatch)
    config = home / ".grok" / "config.toml"
    config.write_text('model = "fast"\n', encoding="utf-8")
    result = mp.repair_user_github_mcp(home, gh_healthy=True)
    assert result["unchangedFiles"] == [str(config)]
    assert sorted(p.name for p in config.parent.iterdir()) == ["config.toml"]


def test_deja_json_strip_writes_valid_json(tmp_path, monkeypatch):
    home = _home(tmp_path, monkeypatch)
    claude = home / ".claude.json"
    claude.write_text(
        json.dumps({"mcpServers": {"deja": {"command": "deja"}, "keep": {"command": "k"}}}),
        encoding="utf-8",
    )
    removed = mp._strip_deja_file(claude)
    assert removed
    data = json.loads(claude.read_text(encoding="utf-8"))
    assert "deja" not in data["mcpServers"]
    assert data["mcpServers"]["keep"] == {"command": "k"}
