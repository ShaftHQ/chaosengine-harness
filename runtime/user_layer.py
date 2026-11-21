"""Opt-in user layer. A project install stays the source of truth (#115)."""

from __future__ import annotations

import base64
import hashlib
import json
import os
import shutil
import stat
import sys
from pathlib import Path

from runtime.hosts import END, START, merge_instruction
from runtime.user_paths import data_dir, home_dir

USER_SKILL = "chaos-engine-user"
PROJECT_SKILL = "chaos-engine"
HOSTS = ("claude", "codex", "gemini", "copilot", "opencode", "grok", "cursor")


def user_home() -> Path:
    """Home for host files. ``CHAOS_ENGINE_USER_HOME`` isolates a test or a cell."""
    return home_dir()


def _host_dir(home: Path, name: str) -> Path:
    if name == "codex":
        override = os.environ.get("CODEX_HOME", "").strip()
        return Path(override) if override else home / ".codex"
    if name == "copilot":
        override = os.environ.get("COPILOT_HOME", "").strip()
        return Path(override) if override else home / ".copilot"
    if name == "grok":
        override = os.environ.get("GROK_HOME", "").strip()
        return Path(override) if override else home / ".grok"
    if name == "opencode":
        return home / ".config" / "opencode"
    return home / f".{name}"


def _pointer(payload: Path) -> str:
    skill = (payload / "skills" / PROJECT_SKILL / "SKILL.md").as_posix()
    return (
        f"{START}\n"
        "If this repo has `.chaos-engine/`, follow it and ignore this block; "
        f"otherwise follow `{skill}`.\n"
        f"{END}\n"
    )


def _skill_text() -> str:
    return (
        "---\n"
        f"name: {USER_SKILL}\n"
        "description: Personal ChaosEngine pointer. A project install wins.\n"
        "---\n\n"
        "If this repo has `.chaos-engine/`, follow that project pin. "
        "Otherwise follow the user-payload ChaosEngine skill.\n"
    )


def _stable_command(launch: Path, host: str, event: str) -> str:
    return f"{sys.executable} {launch} {host} {event} --layer user"


def _hook_document(command: str) -> str:
    document = {
        "hooks": {
            "PreToolUse": [
                {"matcher": "*", "hooks": [{"type": "command", "command": command}]}
            ],
            "SessionStart": [
                {"hooks": [{"type": "command", "command": command.replace("PreToolUse", "SessionStart")}]}
            ],
        }
    }
    return json.dumps(document, indent=2, sort_keys=True) + "\n"


def _merge_json_hooks(path: Path, command: str) -> bytes:
    document: dict = {"hooks": {}}
    if path.is_file():
        try:
            loaded = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return path.read_bytes()
        if isinstance(loaded, dict):
            document = loaded
    hooks = document.setdefault("hooks", {})
    if not isinstance(hooks, dict):
        return path.read_bytes() if path.is_file() else b""
    for event in ("PreToolUse", "SessionStart"):
        groups = hooks.setdefault(event, [])
        if not isinstance(groups, list):
            continue
        text = command if event == "PreToolUse" else command.replace("PreToolUse", "SessionStart")
        if any(text in json.dumps(group) for group in groups):
            continue
        entry = {"hooks": [{"type": "command", "command": text}]}
        if event == "PreToolUse":
            entry["matcher"] = "*"
        groups.append(entry)
    return (json.dumps(document, indent=2, sort_keys=True) + "\n").encode()


def _write_merge(
    path: Path,
    block: str,
    records: list[dict[str, object]],
    prior: dict[str, dict[str, object]],
) -> None:
    previous = path.read_bytes() if path.is_file() and not path.is_symlink() else None
    merged = merge_instruction(previous, block, relative=path.name)
    _store(path, previous, merged, records, prior)


def _store(
    path: Path,
    previous: bytes | None,
    data: bytes,
    records: list[dict[str, object]],
    prior: dict[str, dict[str, object]] | None = None,
) -> None:
    remembered = (prior or {}).get(str(path))
    if remembered is not None:
        records.append(remembered)
    else:
        records.append(
            {
                "path": str(path),
                "existed": previous is not None,
                "pre_sha256": hashlib.sha256(previous).hexdigest() if previous is not None else None,
                "pre_b64": base64.b64encode(previous).decode("ascii") if previous is not None else None,
            }
        )
    if previous == data:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)


def _copy_payload(source: Path, payload: Path) -> None:
    payload.mkdir(parents=True, exist_ok=True)
    hooks = source / "hooks"
    if hooks.is_dir():
        shutil.copytree(hooks, payload / "hooks", dirs_exist_ok=True)
    for relative in ("skills/chaos-engine/SKILL.md", "install.py"):
        origin = source / relative
        if not origin.is_file():
            continue
        target = payload / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        if not target.is_file() or target.read_bytes() != origin.read_bytes():
            shutil.copyfile(origin, target)


def _write_launcher(data: Path) -> Path:
    current = data / "current"
    current.mkdir(parents=True, exist_ok=True)
    launch = current / "launch.py"
    text = (
        "#!/usr/bin/env python3\n"
        "import json, os, sys\n"
        "from pathlib import Path\n"
        "root = Path(__file__).resolve().parents[1]\n"
        "receipt = json.loads((root / 'user-receipt.json').read_text(encoding='utf-8'))\n"
        "payload = root / 'payload' / receipt['commit']\n"
        "os.environ['CHAOS_ENGINE_USER_PAYLOAD'] = str(payload)\n"
        "target = payload / 'hooks' / 'launch.py'\n"
        "os.execv(sys.executable, [sys.executable, str(target), *sys.argv[1:]])\n"
    )
    if not launch.is_file() or launch.read_text(encoding="utf-8") != text:
        launch.write_text(text, encoding="utf-8")
    launch.chmod(launch.stat().st_mode | stat.S_IEXEC)
    return launch


def _windows_shim_py() -> str:
    """Standalone walker. A project ``.chaos-engine/install.py`` wins over the payload."""
    return (
        "import json, os, subprocess, sys\n"
        "from pathlib import Path\n"
        "root = Path(__file__).resolve().parents[1]\n"
        "directory = Path.cwd()\n"
        "while True:\n"
        "    candidate = directory / '.chaos-engine' / 'install.py'\n"
        "    if candidate.is_file():\n"
        "        raise SystemExit(subprocess.call([sys.executable, str(candidate), *sys.argv[1:]]))\n"
        "    if directory.parent == directory:\n"
        "        break\n"
        "    directory = directory.parent\n"
        "receipt = json.loads((root / 'user-receipt.json').read_text(encoding='utf-8'))\n"
        "target = root / 'payload' / receipt['commit'] / 'install.py'\n"
        "raise SystemExit(subprocess.call([sys.executable, str(target), *sys.argv[1:]]))\n"
    )


def _write_shim(data: Path) -> Path:
    destination_dir = data / "bin"
    destination_dir.mkdir(parents=True, exist_ok=True)
    if os.name == "nt":
        script = destination_dir / "chaosengine-harness.py"
        body = _windows_shim_py()
        if not script.is_file() or script.read_text(encoding="utf-8") != body:
            script.write_text(body, encoding="utf-8")
        destination = destination_dir / "chaosengine-harness.cmd"
        interpreter = str(Path(sys.executable))
        text = f'@echo off\r\n"{interpreter}" "%~dp0chaosengine-harness.py" %*\r\nexit /b %ERRORLEVEL%\r\n'
        if not destination.is_file() or destination.read_text(encoding="utf-8") != text:
            destination.write_text(text, encoding="utf-8")
        return destination
    destination = destination_dir / "chaosengine-harness"
    text = """#!/bin/sh
set -eu
ROOT=$(CDPATH= cd -- "$(dirname "$0")/.." && pwd)
dir=$PWD
while [ "$dir" != "/" ]; do
  if [ -f "$dir/.chaos-engine/install.py" ]; then
    exec python3 "$dir/.chaos-engine/install.py" "$@"
  fi
  dir=$(dirname "$dir")
done
COMMIT=$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1], encoding="utf-8"))["commit"])' "$ROOT/user-receipt.json")
exec python3 "$ROOT/payload/$COMMIT/install.py" "$@"
"""
    if not destination.is_file() or destination.read_text(encoding="utf-8") != text:
        destination.write_text(text, encoding="utf-8")
    destination.chmod(0o755)
    return destination


def _selected_hosts(hosts: list[str] | tuple[str, ...] | None) -> tuple[str, ...]:
    if not hosts:
        return HOSTS
    chosen = []
    for item in hosts:
        for part in str(item).split(","):
            name = part.strip()
            if name and name not in chosen:
                chosen.append(name)
    return tuple(chosen)


def install_user_layer(
    *,
    home: Path,
    project: Path,
    source: Path,
    commit: str,
    hosts: list[str] | tuple[str, ...] | None = None,
    hooks: bool = True,
    dry_run: bool = False,
) -> dict[str, object]:
    """Write the user-layer home files. The project directory is not touched."""
    del project
    selected = _selected_hosts(hosts)
    data = data_dir()
    prior: dict[str, dict[str, object]] = {}
    receipt_path = data / "user-receipt.json"
    if receipt_path.is_file():
        try:
            previous_receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            previous_receipt = {}
        for item in previous_receipt.get("files", []):
            if isinstance(item, dict) and item.get("path"):
                prior[str(item["path"])] = item
    payload = data / "payload" / commit
    planned = ["user-receipt.json", "current/launch.py", "bin/chaosengine-harness"]
    if dry_run:
        return {"status": "dry-run", "scope": "user", "files": planned, "root": str(data)}
    _copy_payload(source, payload)
    launch = _write_launcher(data)
    shim = _write_shim(data)
    records: list[dict[str, object]] = []
    claude_written = False
    if "claude" in selected:
        _write_merge(_host_dir(home, "claude") / "CLAUDE.md", _pointer(payload), records, prior)
        skill = home / ".claude" / "skills" / USER_SKILL / "SKILL.md"
        _store(skill, skill.read_bytes() if skill.is_file() else None, _skill_text().encode(), records, prior)
        if hooks:
            settings = home / ".claude" / "settings.json"
            command = _stable_command(launch, "claude", "PreToolUse")
            previous = settings.read_bytes() if settings.is_file() else None
            _store(settings, previous, _merge_json_hooks(settings, command), records, prior)
        claude_written = True
    if "codex" in selected:
        codex = _host_dir(home, "codex")
        if (codex / "AGENTS.override.md").is_file():
            print("CE_USER_CODEX_OVERRIDE Codex reads only AGENTS.override.md", flush=True)
        _write_merge(codex / "AGENTS.md", _pointer(payload), records, prior)
        skill = home / ".agents" / "skills" / USER_SKILL / "SKILL.md"
        _store(skill, skill.read_bytes() if skill.is_file() else None, _skill_text().encode(), records, prior)
        if hooks:
            hooks_path = codex / "hooks.json"
            command = _stable_command(launch, "codex", "PreToolUse")
            previous = hooks_path.read_bytes() if hooks_path.is_file() else None
            _store(hooks_path, previous, _merge_json_hooks(hooks_path, command), records, prior)
    if "cursor" in selected and "codex" not in selected:
        skill = home / ".agents" / "skills" / USER_SKILL / "SKILL.md"
        _store(skill, skill.read_bytes() if skill.is_file() else None, _skill_text().encode(), records, prior)
    if "gemini" in selected:
        gemini = home / ".gemini"
        _write_merge(gemini / "GEMINI.md", _pointer(payload), records, prior)
        if hooks:
            settings = gemini / "settings.json"
            command = _stable_command(launch, "gemini", "PreToolUse")
            previous = settings.read_bytes() if settings.is_file() else None
            _store(settings, previous, _merge_json_hooks(settings, command), records, prior)
    if "copilot" in selected:
        copilot = _host_dir(home, "copilot")
        _write_merge(copilot / "copilot-instructions.md", _pointer(payload), records, prior)
        if hooks:
            hook = copilot / "hooks" / "chaos-engine-user.json"
            command = _stable_command(launch, "copilot", "PreToolUse")
            previous = hook.read_bytes() if hook.is_file() else None
            _store(hook, previous, _hook_document(command).encode(), records, prior)
    if "opencode" in selected:
        opencode = _host_dir(home, "opencode")
        plugin = opencode / "plugins" / "chaos-engine-user.js"
        body = (
            "/* ChaosEngine user layer. A project .chaos-engine install wins. */\n"
        ).encode()
        _store(plugin, plugin.read_bytes() if plugin.is_file() else None, body, records, prior)
        agents = opencode / "AGENTS.md"
        if not (agents.is_file() or (home / ".claude" / "CLAUDE.md").is_file()):
            _write_merge(agents, _pointer(payload), records, prior)
    if "grok" in selected and hooks:
        grok = _host_dir(home, "grok")
        hook = grok / "hooks" / "chaos-engine-user.json"
        command = _stable_command(launch, "grok", "PreToolUse")
        previous = hook.read_bytes() if hook.is_file() else None
        _store(hook, previous, _hook_document(command).encode(), records, prior)
        if not claude_written:
            _write_merge(grok / "rules" / "chaos-engine-user.md", _pointer(payload), records, prior)
    receipt = {
        "scope": "user",
        "commit": commit,
        "files": records,
        "shim": str(shim),
        "launch": str(launch),
    }
    receipt_path = data / "user-receipt.json"
    receipt_path.parent.mkdir(parents=True, exist_ok=True)
    receipt_path.write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return {"status": "installed", "scope": "user", "root": str(data), "files": [item["path"] for item in records]}


def uninstall_user_layer(home: Path | None = None) -> dict[str, object]:
    """Restore every recorded home file. Project installs are not opened."""
    del home
    receipt_path = data_dir() / "user-receipt.json"
    if not receipt_path.is_file():
        return {"status": "absent", "scope": "user"}
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    for item in receipt.get("files", []):
        path = Path(str(item["path"]))
        if item.get("existed") and item.get("pre_b64"):
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(base64.b64decode(str(item["pre_b64"])))
        elif path.is_file() and not path.is_symlink():
            path.unlink()
    commit = str(receipt.get("commit") or "")
    payload = data_dir() / "payload" / commit
    if payload.is_dir():
        shutil.rmtree(payload)
    receipt_path.unlink()
    return {"status": "uninstalled", "scope": "user"}


def project_skill_wins(project: Path) -> Path:
    """The project skill name is ``chaos-engine``. The user skill never uses that name."""
    candidates = (
        project / ".claude" / "skills" / PROJECT_SKILL / "SKILL.md",
        project / ".agents" / "skills" / PROJECT_SKILL / "SKILL.md",
        project / ".chaos-engine" / "skills" / PROJECT_SKILL / "SKILL.md",
    )
    for path in candidates:
        if path.is_file():
            return path
    return candidates[-1]
