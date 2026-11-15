"""Regression tests for ShaftHQ/SHAFT_ENGINE#8070: safe edits of the Grok user config."""

from __future__ import annotations

import importlib.util
import multiprocessing
import os
import sys
import tomllib
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
_spec = importlib.util.spec_from_file_location("ce_grok_lean_config_8070", ROOT / "grok_lean_config.py")
glc = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = glc
_spec.loader.exec_module(glc)

USER_PREFIX = (
    "# my settings\n"
    'model = "fast"\n'
    "\n"
    "[profile.work]\n"
    "temperature = 0.2  # keep\n"
)

# The real-world shape from #8070: the Grok CLI appended its own tables inside
# our UI span, before the END marker.
GROK_APPENDED_INSIDE_SPAN = (
    glc.lean_compat_block()
    + "\n"
    + glc.UI_START + "\n"
    + "[ui]\nshow_thinking_blocks = true\ngroup_tool_verbs = false\n\n"
    + "[marketplace]\n"
    + "default_skills_installs_purged = true\n"
    + "official_marketplace_auto_installed = true\n\n"
    + "[[marketplace.sources]]\n"
    + 'name = "example"\n'
    + 'git = "https://example.invalid/repo.git"\n'
    + glc.UI_END + "\n"
)

MARKETPLACE_LINES = [
    "[marketplace]",
    "default_skills_installs_purged = true",
    "official_marketplace_auto_installed = true",
    "[[marketplace.sources]]",
    'name = "example"',
    'git = "https://example.invalid/repo.git"',
]


def _install(path: Path) -> None:
    glc.apply_lean_compat_file(path)
    glc.apply_grok_ui_file(path)


def _uninstall(path: Path) -> None:
    glc.remove_lean_compat_file(path)
    glc.remove_lean_skills_file(path)
    glc.remove_grok_ui_file(path)


def test_suite_never_points_at_the_real_grok_home():
    protected = os.environ.get("CHAOS_ENGINE_PROTECTED_GROK_HOME")
    assert protected, "tests/conftest.py must arm the Grok home sandbox"
    config = glc.grok_user_config_path()
    assert Path(protected) not in config.parents


def test_tables_grok_wrote_inside_our_span_survive_reinstall(tmp_path):
    path = tmp_path / "config.toml"
    path.write_text(GROK_APPENDED_INSIDE_SPAN, encoding="utf-8")
    _install(path)
    text = path.read_text(encoding="utf-8")
    data = tomllib.loads(text)
    assert data["marketplace"]["sources"] == [
        {"name": "example", "git": "https://example.invalid/repo.git"}
    ]
    assert data["marketplace"]["default_skills_installs_purged"] is True
    lines = text.splitlines()
    for line in MARKETPLACE_LINES:
        assert line in lines
    assert data["ui"]["show_thinking_blocks"] is True
    assert not text.startswith("\n"), "no leading blank lines"


def test_tables_grok_wrote_inside_our_span_survive_uninstall(tmp_path):
    path = tmp_path / "config.toml"
    path.write_text(GROK_APPENDED_INSIDE_SPAN, encoding="utf-8")
    _uninstall(path)
    text = path.read_text(encoding="utf-8")
    data = tomllib.loads(text)
    assert "compat" not in data and "ui" not in data
    assert data["marketplace"]["sources"][0]["name"] == "example"


def test_unrelated_user_content_is_preserved_byte_for_byte(tmp_path):
    path = tmp_path / "config.toml"
    path.write_text(USER_PREFIX, encoding="utf-8")
    _install(path)
    installed = path.read_text(encoding="utf-8")
    assert installed.startswith(USER_PREFIX)
    tomllib.loads(installed)
    for _ in range(3):  # repeated installs neither change nor grow the file
        _install(path)
        assert path.read_text(encoding="utf-8") == installed
    _uninstall(path)
    assert path.read_text(encoding="utf-8") == USER_PREFIX


def test_user_ui_table_keys_survive(tmp_path):
    path = tmp_path / "config.toml"
    original = '[ui]\ntheme = "dark"\n\n[marketplace]\nx = 1\n'
    path.write_text(original, encoding="utf-8")
    _install(path)
    data = tomllib.loads(path.read_text(encoding="utf-8"))
    assert data["ui"]["theme"] == "dark" and data["ui"]["show_thinking_blocks"] is True
    assert data["marketplace"] == {"x": 1}
    _uninstall(path)
    assert path.read_text(encoding="utf-8") == original


def test_crash_before_rename_leaves_the_original_intact(tmp_path, monkeypatch):
    path = tmp_path / "config.toml"
    path.write_text(USER_PREFIX, encoding="utf-8")

    def boom(*_args, **_kwargs):
        raise OSError("simulated crash between temp write and rename")

    monkeypatch.setattr(glc.os, "replace", boom)
    with pytest.raises(OSError):
        _install(path)
    assert path.read_text(encoding="utf-8") == USER_PREFIX
    assert [p.name for p in tmp_path.iterdir() if p.suffix == ".tmp"] == []


def test_crash_during_fsync_leaves_the_original_intact(tmp_path, monkeypatch):
    path = tmp_path / "config.toml"
    path.write_text(USER_PREFIX, encoding="utf-8")

    def boom(_fd):
        raise OSError("simulated power loss before the temp file is durable")

    monkeypatch.setattr(glc.os, "fsync", boom)
    with pytest.raises(OSError):
        _install(path)
    assert path.read_text(encoding="utf-8") == USER_PREFIX


def test_invalid_toml_result_is_refused(tmp_path):
    path = tmp_path / "config.toml"
    path.write_text(USER_PREFIX, encoding="utf-8")
    with pytest.raises(glc.GrokConfigWriteRefused):
        glc.update_config_file(path, lambda text: text + "[broken\n")
    assert path.read_text(encoding="utf-8") == USER_PREFIX


def test_a_torn_file_is_not_made_worse(tmp_path):
    torn = "SENGINE-GROK-LEAN:END\n\n\n" + glc.lean_compat_block()
    path = tmp_path / "config.toml"
    path.write_text(torn, encoding="utf-8")
    with pytest.raises(glc.GrokConfigWriteRefused):
        glc.apply_grok_ui_file(path)
    assert path.read_text(encoding="utf-8") == torn


def test_a_foreign_writer_mid_edit_is_not_lost(tmp_path):
    """The Grok CLI does not take our lock; a change it makes mid-edit must survive."""
    path = tmp_path / "config.toml"
    path.write_text(USER_PREFIX, encoding="utf-8")
    calls = {"n": 0}

    def merge(text: str) -> str:
        calls["n"] += 1
        if calls["n"] == 1:
            with open(path, "a", encoding="utf-8") as handle:
                handle.write("\n[marketplace]\nadded_by_grok = true\n")
        return glc.merge_grok_ui(text)

    glc.update_config_file(path, merge)
    data = tomllib.loads(path.read_text(encoding="utf-8"))
    assert calls["n"] == 2
    assert data["marketplace"] == {"added_by_grok": True}
    assert data["ui"]["show_thinking_blocks"] is True


def _hammer(path_str: str, rounds: int) -> None:
    path = Path(path_str)
    for index in range(rounds):
        if index % 2:
            _uninstall(path)
        else:
            _install(path)
            glc.apply_lean_skills_file(path)


def test_parallel_writers_never_tear_or_drop_user_content(tmp_path):
    path = tmp_path / "config.toml"
    original = USER_PREFIX + "\n[marketplace]\nkeep = true\n"
    path.write_text(original, encoding="utf-8")
    ctx = multiprocessing.get_context("spawn")
    workers = [ctx.Process(target=_hammer, args=(str(path), 20)) for _ in range(6)]
    for worker in workers:
        worker.start()
    for worker in workers:
        worker.join(120)
        assert worker.exitcode == 0
    text = path.read_text(encoding="utf-8")
    data = tomllib.loads(text)
    assert text.startswith(USER_PREFIX)
    assert data["marketplace"] == {"keep": True}
    _uninstall(path)
    assert path.read_text(encoding="utf-8") == original


def test_tripwire_refuses_and_logs_writes_to_the_protected_home(tmp_path, monkeypatch):
    real = tmp_path / "real-home" / ".grok"
    log = tmp_path / "tripwire.log"
    monkeypatch.setenv("CHAOS_ENGINE_PROTECTED_GROK_HOME", str(real))
    monkeypatch.setenv("CHAOS_ENGINE_PROTECTED_GROK_HOME_LOG", str(log))
    with pytest.raises(glc.GrokConfigWriteRefused):
        glc.apply_lean_compat_file(real / "config.toml")
    assert not (real / "config.toml").exists()
    assert str(real / "config.toml") in log.read_text(encoding="utf-8")


def test_refusal_is_an_oserror_so_doctor_heal_paths_report_it(tmp_path):
    assert issubclass(glc.GrokConfigWriteRefused, OSError)
    path = tmp_path / "config.toml"
    path.write_text(USER_PREFIX, encoding="utf-8")
    with pytest.raises(OSError):
        glc.update_config_file(path, lambda text: text + "[broken\n")


@pytest.mark.skipif(os.name == "nt", reason="symlinks need privileges on Windows")
def test_a_symlinked_config_is_edited_at_its_target(tmp_path):
    dotfiles = tmp_path / "dotfiles"
    dotfiles.mkdir()
    target = dotfiles / "grok-config.toml"
    target.write_text(USER_PREFIX, encoding="utf-8")
    home = tmp_path / ".grok"
    home.mkdir()
    link = home / "config.toml"
    link.symlink_to(target)
    _install(link)
    assert link.is_symlink()
    assert os.path.realpath(link) == str(target)
    data = tomllib.loads(target.read_text(encoding="utf-8"))
    assert data["ui"]["show_thinking_blocks"] is True
    assert data["profile"]["work"]["temperature"] == 0.2
    assert not list(home.glob(".config.toml.*.tmp"))
    _uninstall(link)
    assert link.is_symlink()
    assert target.read_text(encoding="utf-8") == USER_PREFIX


@pytest.mark.skipif(os.name == "nt", reason="symlinks need privileges on Windows")
def test_tripwire_follows_a_symlink_into_the_protected_home(tmp_path, monkeypatch):
    real = tmp_path / "real-home" / ".grok"
    real.mkdir(parents=True)
    (real / "config.toml").write_text(USER_PREFIX, encoding="utf-8")
    elsewhere = tmp_path / "sandbox"
    elsewhere.mkdir()
    (elsewhere / "config.toml").symlink_to(real / "config.toml")
    monkeypatch.setenv("CHAOS_ENGINE_PROTECTED_GROK_HOME", str(real))
    monkeypatch.delenv("CHAOS_ENGINE_PROTECTED_GROK_HOME_LOG", raising=False)
    with pytest.raises(glc.GrokConfigWriteRefused):
        glc.apply_lean_compat_file(elsewhere / "config.toml")
    assert (real / "config.toml").read_text(encoding="utf-8") == USER_PREFIX


def test_ui_pins_are_not_added_to_a_following_array_table(tmp_path):
    original = (
        "[ui]\n"
        'theme = "dark"\n'
        "\n"
        "[[marketplace.sources]]\n"
        'name = "example"\n'
        "\n"
        "[skills]\n"
        "disabled = []\n"
    )
    path = tmp_path / "config.toml"
    path.write_text(original, encoding="utf-8")
    glc.apply_grok_ui_file(path)
    data = tomllib.loads(path.read_text(encoding="utf-8"))
    assert data["ui"]["show_thinking_blocks"] is True
    assert data["ui"]["theme"] == "dark"
    assert data["marketplace"]["sources"] == [{"name": "example"}]
    assert glc.grok_ui_applied(path.read_text(encoding="utf-8"))
    glc.remove_grok_ui_file(path)
    assert tomllib.loads(path.read_text(encoding="utf-8")) == tomllib.loads(original)


def test_outside_compat_strip_keeps_a_following_array_table(tmp_path):
    original = (
        "[compat.claude]\n"
        "skills = true\n"
        "\n"
        "[[marketplace.sources]]\n"
        'name = "example"\n'
        "\n"
        "[[mcp.servers]]\n"
        'name = "srv"\n'
    )
    path = tmp_path / "config.toml"
    path.write_text(original, encoding="utf-8")
    glc.apply_lean_compat_file(path)
    data = tomllib.loads(path.read_text(encoding="utf-8"))
    assert data["marketplace"]["sources"] == [{"name": "example"}]
    assert data["mcp"]["servers"] == [{"name": "srv"}]
    glc.remove_lean_compat_file(path)
    data = tomllib.loads(path.read_text(encoding="utf-8"))
    assert data["marketplace"]["sources"] == [{"name": "example"}]
    assert data["mcp"]["servers"] == [{"name": "srv"}]


def test_a_foreign_write_after_the_temp_fsync_is_not_lost(tmp_path, monkeypatch):
    """The re-read must happen after the temp file is durable, right before the rename."""
    path = tmp_path / "config.toml"
    path.write_text(USER_PREFIX, encoding="utf-8")
    real_write_temp = glc._write_temp
    calls = {"n": 0}

    def write_temp_then_grok_writes(target, data):
        name = real_write_temp(target, data)
        calls["n"] += 1
        if calls["n"] == 1:
            with open(path, "a", encoding="utf-8") as handle:
                handle.write("\n[marketplace]\nadded_by_grok = true\n")
        return name

    monkeypatch.setattr(glc, "_write_temp", write_temp_then_grok_writes)
    glc.apply_grok_ui_file(path)
    data = tomllib.loads(path.read_text(encoding="utf-8"))
    assert calls["n"] == 2
    assert data["marketplace"] == {"added_by_grok": True}
    assert data["ui"]["show_thinking_blocks"] is True
    assert [p.name for p in tmp_path.iterdir() if p.suffix == ".tmp"] == []


def test_a_new_config_gets_a_normal_mode(tmp_path):
    path = tmp_path / ".grok" / "config.toml"
    glc.apply_grok_ui_file(path)
    if os.name != "nt":
        assert path.stat().st_mode & 0o777 == 0o644
