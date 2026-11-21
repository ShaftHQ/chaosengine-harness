"""Layered installer config: flag, env, project-local, project, user, default.

Files are TOML (``tomllib``). A missing file changes nothing. A file level
applies a key only when that level's letter is in the catalog row (``U`` user,
``P`` project, ``L`` project-local). ``replace`` for ``instructions.mode`` is
refused from every file before that skip. CLI-only keys in a file are ignored
with a warning.
"""

from __future__ import annotations

import json
import os
import sys
from dataclasses import dataclass, field
from pathlib import Path

try:
    from runtime.install_options import (
        BY_KEY,
        CATALOG,
        CLI_ONLY_KEYS,
        COMPONENT_NAMES,
        HOST_IDS,
        MERGE_LIST_KEYS,
        SECRET_KEY,
        InstallOption,
    )
    from runtime.user_paths import (
        cache_dir,
        config_dir,
        data_dir,
        legacy_config_dir,
        legacy_data_dir,
        legacy_state_dir,
        prefer_existing,
        state_dir,
    )
except ImportError:  # executed from the stage-1 bootstrap embed
    from ce_install_options import (  # type: ignore
        BY_KEY,
        CATALOG,
        CLI_ONLY_KEYS,
        COMPONENT_NAMES,
        HOST_IDS,
        MERGE_LIST_KEYS,
        SECRET_KEY,
        InstallOption,
    )
    from ce_user_paths import (  # type: ignore
        cache_dir,
        config_dir,
        data_dir,
        legacy_config_dir,
        legacy_data_dir,
        legacy_state_dir,
        prefer_existing,
        state_dir,
    )


class ConfigError(ValueError):
    """A config file cannot be applied. ``code`` is the stable token."""

    def __init__(self, code: str, detail: str) -> None:
        self.code = code
        super().__init__(f"{code} {detail}")


@dataclass
class Resolved:
    values: dict[str, object]
    sources: dict[str, str]
    warnings: list[str] = field(default_factory=list)

    def to_show(self) -> dict[str, object]:
        keys = []
        for row in CATALOG:
            keys.append(
                {
                    "key": row.key,
                    "value": _jsonable(self.values[row.key]),
                    "source": self.sources[row.key],
                }
            )
        return {"keys": keys, "warnings": list(self.warnings)}


def user_config_path(explicit: Path | None = None, environ: dict[str, str] | None = None) -> Path:
    if explicit is not None:
        return Path(explicit)
    if environ is not None:
        override = environ.get("CHAOS_ENGINE_CONFIG_HOME", "").strip()
        if override:
            return Path(os.path.expandvars(os.path.expanduser(override))) / "config.toml"
    return config_dir() / "config.toml"


def project_config_path(project: Path) -> Path:
    return Path(project) / ".chaos-engine.toml"


def local_config_path(project: Path) -> Path:
    return Path(project) / ".chaos-engine.local.toml"


def _jsonable(value: object) -> object:
    if isinstance(value, tuple):
        return list(value)
    return value


def _flatten(document: dict, prefix: str = "") -> dict[str, object]:
    flat: dict[str, object] = {}
    for key, value in document.items():
        name = f"{prefix}.{key}" if prefix else str(key)
        if isinstance(value, dict):
            flat.update(_flatten(value, name))
        else:
            flat[name] = value
    return flat


def _read_toml(path: Path) -> dict[str, object]:
    import tomllib

    raw = path.read_bytes()
    if raw.startswith(b"\xef\xbb\xbf"):
        raw = raw[3:]
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as error:
        raise ConfigError("CE_CONFIG_INVALID", f"{path}:file") from error
    try:
        loaded = tomllib.loads(text)
    except tomllib.TOMLDecodeError as error:
        raise ConfigError("CE_CONFIG_INVALID", f"{path}:file") from error
    if not isinstance(loaded, dict):
        raise ConfigError("CE_CONFIG_INVALID", f"{path}:file")
    return loaded


def _truthy(value: str) -> bool | None:
    token = value.strip().casefold()
    if token in {"1", "true", "yes", "on"}:
        return True
    if token in {"0", "false", "no", "off"}:
        return False
    return None


def _csv(value: str) -> tuple[str, ...]:
    return tuple(part.strip() for part in value.split(",") if part.strip())


def _check_secret(key: str, path: Path) -> None:
    if key in BY_KEY or key == "schema":
        return
    if key == "network.ca_bundle":
        return
    leaf = key.rsplit(".", 1)[-1]
    if SECRET_KEY.search(leaf) or SECRET_KEY.search(key):
        raise ConfigError("CE_CONFIG_SECRET", f"{path}:{key}")


def _coerce(row: InstallOption, value: object, path: Path) -> object:
    if row.kind == "bool":
        if isinstance(value, bool):
            return value
        raise ConfigError("CE_CONFIG_INVALID", f"{path}:{row.key}")
    if row.kind == "int":
        if isinstance(value, bool) or not isinstance(value, int):
            raise ConfigError("CE_CONFIG_INVALID", f"{path}:{row.key}")
        if row.key == "locks.project_wait_seconds" and not 1 <= value <= 600:
            raise ConfigError("CE_CONFIG_INVALID", f"{path}:{row.key}")
        if row.key == "hooks.guard_wait_ms" and not 0 <= value <= 600_000:
            raise ConfigError("CE_CONFIG_INVALID", f"{path}:{row.key}")
        if value < 0:
            raise ConfigError("CE_CONFIG_INVALID", f"{path}:{row.key}")
        return value
    if row.kind in {"str", "path"}:
        if not isinstance(value, str):
            raise ConfigError("CE_CONFIG_INVALID", f"{path}:{row.key}")
        if row.kind == "path" and value.strip():
            return str(Path(os.path.expandvars(os.path.expanduser(value))))
        return value
    if row.kind == "choice":
        if not isinstance(value, str) or (row.choices and value not in row.choices):
            raise ConfigError("CE_CONFIG_INVALID", f"{path}:{row.key}")
        return value
    if row.kind == "list":
        if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
            raise ConfigError("CE_CONFIG_INVALID", f"{path}:{row.key}")
        if row.choices:
            unknown = [item for item in value if item not in row.choices]
            if unknown:
                raise ConfigError("CE_CONFIG_INVALID", f"{path}:{row.key}")
        return tuple(value)
    raise ConfigError("CE_CONFIG_INVALID", f"{path}:{row.key}")


def _load_file(path: Path, *, source: str, warnings: list[str]) -> dict[str, tuple[object, str]]:
    if not path.is_file():
        return {}
    try:
        if path.is_symlink():
            raise ConfigError("CE_CONFIG_INVALID", f"{path}:file")
    except OSError as error:
        raise ConfigError("CE_CONFIG_INVALID", f"{path}:file") from error
    document = _read_toml(path)
    schema = document.get("schema", 1)
    if schema != 1:
        raise ConfigError("CE_CONFIG_INVALID", f"{path}:schema")
    flat = _flatten(document)
    found: dict[str, tuple[object, str]] = {}
    for key, value in flat.items():
        if key == "schema":
            continue
        _check_secret(key, path)
        if key in CLI_ONLY_KEYS or (key in BY_KEY and BY_KEY[key].cli_only):
            warnings.append(f"ignored cli-only key {key} in {source}")
            continue
        row = BY_KEY.get(key)
        if row is None:
            warnings.append(f"ignored unknown key {key} in {source}")
            continue
        coerced = _coerce(row, value, path)
        if key == "instructions.mode" and coerced == "replace":
            raise ConfigError("CE_CONFIG_REPLACE_FROM_FILE", f"{path}:{key}")
        letter = {"user": "U", "project": "P", "project-local": "L"}.get(source)
        if letter is not None and letter not in row.levels:
            warnings.append(f"ignored {key} in {source}; level {letter} is not allowed")
            continue
        found[key] = (coerced, source)
    return found


def _marker_layers(project: Path) -> dict[str, tuple[object, str]]:
    found: dict[str, tuple[object, str]] = {}
    root = Path(project)
    mcp = root / ".chaos-engine-state" / "with-mcp"
    if mcp.is_file():
        found["mcp.publish"] = (True, f"marker:{mcp.as_posix()}")
    consumer = root / ".chaos-engine-state" / "consumer-mode"
    if consumer.is_file():
        found["install.git_visibility"] = ("excluded", f"marker:{consumer.as_posix()}")
    bundle = root / ".chaos-engine-state" / "bundle-options.json"
    if bundle.is_file():
        try:
            document = json.loads(bundle.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            document = None
        enabled = document.get("enabled") if isinstance(document, dict) else None
        if isinstance(enabled, dict):
            for name in COMPONENT_NAMES:
                if name in enabled and enabled[name] is False:
                    found[f"components.{name}"] = (False, f"marker:{bundle.as_posix()}")
    return found


def _env_value(row: InstallOption, environ: dict[str, str]) -> object | None:
    if not row.env or not row.env_kind:
        return None
    raw = environ.get(row.env[0])
    if raw is None or raw.strip() == "":
        return None
    if row.env_kind == "str":
        return raw.strip()
    if row.env_kind == "bool":
        parsed = _truthy(raw)
        if parsed is None:
            raise ConfigError("CE_CONFIG_INVALID", f"env:{row.env[0]}")
        return parsed
    if row.env_kind == "bool-default-true":
        parsed = _truthy(raw)
        if parsed is None:
            raise ConfigError("CE_CONFIG_INVALID", f"env:{row.env[0]}")
        return parsed
    if row.env_kind == "bool-invert":
        parsed = _truthy(raw)
        if parsed is None:
            raise ConfigError("CE_CONFIG_INVALID", f"env:{row.env[0]}")
        return not parsed
    if row.env_kind == "consumer":
        parsed = _truthy(raw)
        if parsed is None:
            raise ConfigError("CE_CONFIG_INVALID", f"env:{row.env[0]}")
        return "excluded" if parsed else "tracked"
    if row.env_kind == "csv":
        return _csv(raw)
    if row.env_kind == "int":
        try:
            return int(raw.strip())
        except ValueError as error:
            raise ConfigError("CE_CONFIG_INVALID", f"env:{row.env[0]}") from error
    if row.env_kind == "choice":
        if row.choices and raw.strip() not in row.choices:
            raise ConfigError("CE_CONFIG_INVALID", f"env:{row.env[0]}")
        return raw.strip()
    if row.env_kind == "keep-edits":
        parsed = _truthy(raw)
        if parsed is None:
            raise ConfigError("CE_CONFIG_INVALID", f"env:{row.env[0]}")
        return "refuse" if parsed else "copy-aside"
    return None


def _cli_value(row: InstallOption, args: object) -> object | None:
    if args is None or not row.dest:
        return None
    if row.action == "append":
        raw = getattr(args, row.dest, None)
        if not raw:
            return None
        parts: list[str] = []
        for item in raw:
            parts.extend(_csv(str(item)))
        return tuple(parts)
    if row.action in {"store_true", "secret_guard_off"}:
        if getattr(args, row.dest, False):
            return row.flag_value
        if row.enable_dest and getattr(args, row.enable_dest, False):
            if row.kind == "bool":
                return True if row.flag_value is False else False
            if row.kind == "choice" and row.key == "ui.verbosity":
                return "verbose"
            if row.kind == "choice" and row.key == "install.git_visibility":
                return "tracked"
        return None
    value = getattr(args, row.dest, None)
    if value is None or value == "":
        return None
    if row.dest in {"distribution", "branch", "version_pin", "shaft_skills_version"} and value is None:
        return None
    if row.kind == "path":
        return str(value)
    return value


def _without_env(environ: dict[str, str]) -> dict[str, object]:
    raw = environ.get("CHAOS_ENGINE_WITHOUT", "")
    if not raw.strip():
        return {}
    found = {}
    for name in _csv(raw):
        if name not in COMPONENT_NAMES:
            raise ConfigError("CE_CONFIG_INVALID", "env:CHAOS_ENGINE_WITHOUT")
        found[f"components.{name}"] = False
    return found


def resolve_config(
    project: Path | None,
    *,
    args: object = None,
    environ: dict[str, str] | None = None,
    explicit_config: Path | None = None,
) -> Resolved:
    """Resolve every catalog key. Later layers overwrite earlier ones."""
    env = os.environ if environ is None else environ
    warnings: list[str] = []
    values: dict[str, object] = {row.key: row.default for row in CATALOG}
    sources: dict[str, str] = {row.key: "default" for row in CATALOG}

    def put(key: str, value: object, source: str, *, merge: bool = False) -> None:
        if merge and key in MERGE_LIST_KEYS:
            current = values.get(key) or ()
            if not isinstance(current, tuple):
                current = tuple(current) if isinstance(current, list) else ()
            extra = value if isinstance(value, tuple) else tuple(value) if isinstance(value, list) else ()
            merged: list[str] = list(current)
            for item in extra:
                if item not in merged:
                    merged.append(str(item))
            values[key] = tuple(merged)
        else:
            values[key] = value
        sources[key] = source

    if project is not None:
        for key, (value, source) in _marker_layers(Path(project)).items():
            put(key, value, source)
        layers = (
            (user_config_path(explicit_config, env), "user"),
            (project_config_path(project), "project"),
            (local_config_path(project), "project-local"),
        )
        for path, source in layers:
            for key, (value, origin) in _load_file(path, source=source, warnings=warnings).items():
                put(key, value, origin, merge=key in MERGE_LIST_KEYS)
    elif explicit_config is not None:
        for key, (value, origin) in _load_file(Path(explicit_config), source="user", warnings=warnings).items():
            put(key, value, origin, merge=key in MERGE_LIST_KEYS)

    for key, value in _without_env(env).items():
        put(key, value, "env:CHAOS_ENGINE_WITHOUT")
    for row in CATALOG:
        try:
            env_value = _env_value(row, env)
        except ConfigError:
            raise
        if env_value is None:
            continue
        if row.kind == "int":
            env_value = _coerce(row, env_value, Path(f"env:{row.env[0]}"))
        if row.kind == "list" and row.choices:
            unknown = [item for item in env_value if item not in row.choices]
            if unknown:
                raise ConfigError("CE_CONFIG_INVALID", f"env:{row.env[0]}")
        if row.kind == "path" and isinstance(env_value, str) and env_value.strip():
            env_value = str(Path(os.path.expandvars(os.path.expanduser(env_value))))
        put(row.key, env_value, f"env:{row.env[0]}", merge=row.merge)

    for row in CATALOG:
        cli_value = _cli_value(row, args)
        if cli_value is None:
            continue
        put(row.key, cli_value, "cli", merge=False)

    return Resolved(values=values, sources=sources, warnings=warnings)


def apply_namespace(args: object, resolved: Resolved) -> None:
    """Copy non-default resolved values onto the argparse namespace."""
    for row in CATALOG:
        source = resolved.sources[row.key]
        if source == "default" or not row.dest:
            continue
        value = resolved.values[row.key]
        if row.action == "append" and isinstance(value, tuple):
            setattr(args, row.dest, list(value))
            continue
        if row.action in {"store_true", "secret_guard_off"}:
            setattr(args, row.dest, value == row.flag_value)
            if row.enable_dest:
                if row.key == "ui.verbosity":
                    setattr(args, row.enable_dest, value == "verbose")
                elif row.key == "install.git_visibility":
                    setattr(args, row.enable_dest, value == "tracked" and source == "cli")
                elif row.kind == "bool" and row.flag_value is False:
                    setattr(args, row.enable_dest, value is True)
                elif row.kind == "bool" and row.flag_value is True:
                    setattr(args, row.enable_dest, value is False)
            if row.key == "git_hooks.secret_guard" and value is False:
                os.environ["CHAOS_ENGINE_SECRET_GUARD"] = "0"
            continue
        if row.dest in {"branch", "version_pin", "distribution", "shaft_skills_version"}:
            if value in {None, "", row.default} and source == "default":
                continue
            setattr(args, row.dest, None if value in {None, ""} else value)
            continue
        if row.dest == "from_bundle":
            setattr(args, row.dest, Path(str(value)) if value else None)
            continue
        setattr(args, row.dest, value)
    bundle = resolved.values.get("network.bundle") or ""
    if resolved.sources.get("network.bundle") != "default" and bundle and not getattr(args, "from_bundle", None):
        args.from_bundle = Path(str(bundle))
    ca_bundle = resolved.values.get("network.ca_bundle") or ""
    if resolved.sources.get("network.ca_bundle") != "default" and isinstance(ca_bundle, str) and ca_bundle:
        os.environ["SSL_CERT_FILE"] = ca_bundle
        os.environ["REQUESTS_CA_BUNDLE"] = ca_bundle
        os.environ["NODE_EXTRA_CA_CERTS"] = ca_bundle
        os.environ["UV_NATIVE_TLS"] = "1"


def announce(resolved: Resolved, stream=None) -> None:
    """Print project-sourced keys, marker hints, and safety-reducing values."""
    out = stream or sys.stderr
    for row in CATALOG:
        source = resolved.sources[row.key]
        if source in {"project", "project-local"}:
            print(f"config: {row.key}={_jsonable(resolved.values[row.key])} from {source}", file=out)
        elif source.startswith("marker:"):
            print(
                f"config: {source.removeprefix('marker:')} is in use; the matching key is {row.key}",
                file=out,
            )
    for key in ("git_hooks.secret_guard",):
        if resolved.values.get(key) is False and resolved.sources.get(key) != "default":
            print(f"config: {key}=false from {resolved.sources[key]}", file=out)
    for name in COMPONENT_NAMES:
        key = f"components.{name}"
        if resolved.values.get(key) is False and resolved.sources.get(key) not in {"default", "project", "project-local"}:
            print(f"config: {key}=false from {resolved.sources[key]}", file=out)


def doctor_row(project: Path, *, environ: dict[str, str] | None = None) -> dict[str, object]:
    try:
        resolved = resolve_config(project, environ=environ)
    except ConfigError as error:
        return {"status": "warn", "code": error.code, "detail": str(error)}
    if resolved.warnings:
        return {"status": "warn", "warnings": list(resolved.warnings)}
    safety = []
    if resolved.values.get("git_hooks.secret_guard") is False and resolved.sources["git_hooks.secret_guard"] != "default":
        safety.append("git_hooks.secret_guard")
    for name in COMPONENT_NAMES:
        key = f"components.{name}"
        if resolved.values.get(key) is False and resolved.sources[key] != "default":
            safety.append(key)
    if safety:
        return {"status": "warn", "safety": safety}
    return {"status": "pass"}


def _toml_literal(value: object) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int) and not isinstance(value, bool):
        return str(value)
    if isinstance(value, (list, tuple)):
        return "[" + ", ".join(json.dumps(str(item)) for item in value) + "]"
    return json.dumps(str(value))


def config_set(path: Path, key: str, raw: str) -> None:
    """Write one key. Comments and the file's line endings stay."""
    row = BY_KEY.get(key)
    if row is None or row.cli_only or key in CLI_ONLY_KEYS:
        raise ConfigError("CE_CONFIG_INVALID", f"{path}:{key}")
    if key == "instructions.mode" and raw == "replace":
        raise ConfigError("CE_CONFIG_REPLACE_FROM_FILE", f"{path}:{key}")
    value = _parse_set_value(row, raw, path)
    _coerce(row, value if not isinstance(value, tuple) else list(value), path)
    newline = "\n"
    if path.is_file():
        original = path.read_bytes()
        if b"\r\n" in original:
            newline = "\r\n"
        bom = original.startswith(b"\xef\xbb\xbf")
        text = original.decode("utf-8-sig")
    else:
        path.parent.mkdir(parents=True, exist_ok=True)
        text = "schema = 1\n"
        bom = False
    rendered = _toml_literal(list(value) if isinstance(value, tuple) else value)
    text = _upsert_toml(text, key, rendered)
    if newline == "\r\n":
        text = text.replace("\r\n", "\n").replace("\n", "\r\n")
    payload = text.encode("utf-8")
    path.write_bytes((b"\xef\xbb\xbf" + payload) if bom else payload)
    _load_file(path, source="user", warnings=[])


def _parse_set_value(row: InstallOption, raw: str, path: Path) -> object:
    if row.kind == "bool":
        parsed = _truthy(raw)
        if parsed is None:
            raise ConfigError("CE_CONFIG_INVALID", f"{path}:{row.key}")
        return parsed
    if row.kind == "int":
        try:
            return int(raw)
        except ValueError as error:
            raise ConfigError("CE_CONFIG_INVALID", f"{path}:{row.key}") from error
    if row.kind == "list":
        return list(_csv(raw))
    return raw


def _upsert_toml(text: str, key: str, rendered: str) -> str:
    parts = key.split(".")
    leaf = parts[-1]
    table = ".".join(parts[:-1])
    lines = text.splitlines()
    assignment = f"{leaf} = {rendered}"
    if not table:
        for index, line in enumerate(lines):
            if line.startswith(f"{leaf} ") or line.startswith(f"{leaf}="):
                lines[index] = assignment
                return "\n".join(lines) + "\n"
        lines.append(assignment)
        return "\n".join(lines) + "\n"
    header = f"[{table}]"
    start = None
    for index, line in enumerate(lines):
        if line.strip() == header:
            start = index
            break
    if start is None:
        if lines and lines[-1].strip():
            lines.append("")
        lines.append(header)
        lines.append(assignment)
        return "\n".join(lines) + "\n"
    end = len(lines)
    for index in range(start + 1, len(lines)):
        stripped = lines[index].strip()
        if stripped.startswith("[") and stripped.endswith("]"):
            end = index
            break
        head = stripped.split("=", 1)[0].strip()
        if head == leaf:
            lines[index] = assignment
            return "\n".join(lines) + "\n"
    lines.insert(end, assignment)
    return "\n".join(lines) + "\n"


def config_paths(project: Path, explicit: Path | None = None) -> dict[str, object]:
    rows = (
        ("user", user_config_path(explicit)),
        ("project", project_config_path(project)),
        ("project-local", local_config_path(project)),
    )
    return {
        "paths": [
            {"level": level, "path": str(path), "exists": path.is_file()}
            for level, path in rows
        ]
    }


def run_config_command(args: object) -> int:
    """``install.py config`` implementation. Returns the process status."""
    command = getattr(args, "config_command", "")
    project = Path(getattr(args, "project", Path(".")))
    try:
        if command == "show":
            resolved = resolve_config(
                project,
                explicit_config=getattr(args, "config_path", None),
            )
            if getattr(args, "json", False):
                print(json.dumps(resolved.to_show(), sort_keys=True))
            else:
                for row in resolved.to_show()["keys"]:
                    print(f"{row['key']}={row['value']} ({row['source']})")
                for warning in resolved.warnings:
                    print(f"warning: {warning}", file=sys.stderr)
            return 0
        if command == "path":
            print(json.dumps(config_paths(project, getattr(args, "config_path", None)), sort_keys=True))
            return 0
        if command == "validate":
            target = Path(getattr(args, "file", "") or project_config_path(project))
            warnings: list[str] = []
            _load_file(target, source="project", warnings=warnings)
            for warning in warnings:
                print(f"warning: {warning}", file=sys.stderr)
            print("ok")
            return 0
        if command == "set":
            level = getattr(args, "level", "")
            if level == "user":
                path = user_config_path(getattr(args, "config_path", None))
            elif level == "project":
                path = project_config_path(project)
            elif level == "local":
                path = local_config_path(project)
            else:
                raise ConfigError("CE_CONFIG_INVALID", "level")
            config_set(path, str(getattr(args, "key", "")), str(getattr(args, "value", "")))
            print(str(path))
            return 0
        if command == "migrate-paths":
            return _migrate_paths(yes=bool(getattr(args, "yes", False)))
    except ConfigError as error:
        print(str(error), file=sys.stderr)
        return 1
    print("CE_CONFIG_INVALID unknown config command", file=sys.stderr)
    return 1


def _migrate_paths(*, yes: bool) -> int:
    moves = (
        (legacy_data_dir(), data_dir()),
        (legacy_state_dir(), state_dir()),
        (legacy_config_dir(), config_dir()),
    )
    planned = [(old, new) for old, new in moves if old != new and old.exists() and not new.exists()]
    if not planned:
        print("config migrate-paths: nothing to move")
        return 0
    for old, new in planned:
        print(f"config migrate-paths: {old} -> {new}")
    if not yes:
        print("config migrate-paths: dry-run (pass --yes to copy)")
        return 0
    import shutil

    for old, new in planned:
        new.parent.mkdir(parents=True, exist_ok=True)
        shutil.copytree(old, new)
        if not new.exists():
            raise ConfigError("CE_CONFIG_INVALID", f"migrate:{old}")
        try:
            from runtime.delete_guard import allow_listed
        except ImportError:
            allow_listed = None  # type: ignore
        if allow_listed is not None and allow_listed(old):
            print(f"config migrate-paths: left {old} (delete guard)")
            continue
        shutil.rmtree(old)
    return 0


def path_receipt() -> dict[str, str]:
    """Where each kind resolved, including a legacy directory that is still in use."""
    return {
        "config": str(prefer_existing(config_dir(), legacy_config_dir())),
        "data": str(prefer_existing(data_dir(), legacy_data_dir())),
        "state": str(prefer_existing(state_dir(), legacy_state_dir())),
        "cache": str(cache_dir()),
    }
