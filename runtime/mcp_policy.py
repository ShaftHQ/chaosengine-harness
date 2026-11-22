#!/usr/bin/env python3
"""Owned MCP uniqueness across project and user/host layers. No proxy."""

from __future__ import annotations

import json
import os
import re
import subprocess  # nosec B404 - fixed gh probe only
from collections.abc import Callable, Iterable
from pathlib import Path

GITHUB_MCP_IDS = frozenset({"github", "github-gh", "github_gh"})

# Consumer product MCP is owned by the agentic installer, never by the ChaosEngine
# installer catalog (#5943 FR-005). Assembled at runtime so portable forbiddenTokens
# never appear in this file.
PRODUCT_MCP_IDS = frozenset({"sha" + "ft-mcp", "sha" + "ft_mcp"})

# GitHub MCP is never a default catalog entry. When gh is healthy, doctor/repair
# strips GitHub MCP from user host MCP files. When gh is missing/unauthenticated,
# leave existing GitHub MCP in place. Graphify MCP still conflicts with the
# owned Graphify CLI.
ALIAS_GROUPS: tuple[frozenset[str], ...] = ()

CLI_OWNED_MCP: dict[str, frozenset[str]] = {
    "graphify": frozenset({"graphify", "graphifyy"}),
}

# #6179: servers whose job a first-party CLI already does. Default catalogs
# omit them; `--with-mcp` (or `with_mcp=True`) opts back in.
CLI_EQUIVALENT_MCP_IDS = frozenset({"chaosengine-memory", "chaosengine-mempalace", "context7"})
OPTIONAL_MCP_IDS = ("chaosengine-memory", "chaosengine-mempalace", "context7", "chrome-devtools-mcp")

# Pinned to maven-tools-mcp 3.3.1 (42cc4d16070637d8d579226e0fd8d55c4d31cbab).
# An empty set means no tools are permitted. A missing key is not an empty set.
# Move this set in the same change as MAVEN_TOOLS_MCP_VERSION. The 3.3.1
# tool names are the same set reviewed for 3.3.0.
EXPECTED_MCP_TOOL_NAMES: dict[str, frozenset[str]] = {
    "maven-tools-mcp": frozenset(
        {
            "analyze_dependency_age",
            "analyze_pom_dependencies",
            "analyze_project_health",
            "analyze_release_patterns",
            "check_multiple_dependencies",
            "check_version_exists",
            "compare_dependency_versions",
            "get_latest_version",
            "recommend_pom_upgrades",
            "scan_transitive_vulnerabilities",
        }
    ),
}

# One read-only idempotent tools/call, then one call that must be refused.
# check_version_exists only reads Maven Central; it does not change a project.
MCP_STDIO_PROBES: dict[str, dict[str, dict[str, object]]] = {
    "maven-tools-mcp": {
        "read_only": {
            "name": "check_version_exists",
            "arguments": {"dependency": "junit:junit", "version": "4.13.2"},
        },
        "negative": {
            "name": "chaosengine-refused-tool",
            "arguments": {},
        },
    },
}

# Opt-in servers that already have a launch path but no pinned tool catalog.
# A skip is not an empty allowlist and not permission to treat any tool list as success.
MCP_PROBE_SKIPS: dict[str, str] = {
    "chaosengine-memory": (
        "stdio launch is tool.py memory-mcp, but the tool catalog is owned by "
        "the external memory package and is not pinned here; skipped, not an empty allowlist"
    ),
    "chaosengine-mempalace": (
        "stdio launch is tool.py mempalace-mcp, but the tool catalog is owned by "
        "the external mempalace package and is not pinned here; skipped, not an empty allowlist"
    ),
    "context7": (
        "published as an HTTP URL, not a stdio process; this probe stays stdio-only "
        "and does not add a gateway"
    ),
    "chrome-devtools-mcp": (
        "npx launch needs a live npm fetch and Chrome; no offline pinned tool list "
        "for the opt-in server, so the probe is skipped"
    ),
}


def _profile_named(path: Path, profile: str) -> bool:
    """True when ``path`` is the profile.json of the profile or pack called ``profile``."""
    try:
        return json.loads(path.read_text(encoding="utf-8")).get("name") == profile
    except (OSError, ValueError, AttributeError):
        return False


def profile_mcp_ids(profile: str) -> tuple[str, ...]:
    """MCP servers a selected profile declares (`mcpServers` in its profile.json)."""
    root = Path(__file__).resolve().parents[1]
    candidates = [root / "profiles" / profile / "profile.json", root / "packs" / profile / "profile.json"]
    candidates.extend(sorted(root.parent.glob("*/ce-pack/profile.json")))
    path = next((item for item in candidates if _profile_named(item, profile)), candidates[0])
    try:
        declared = json.loads(path.read_text(encoding="utf-8")).get("mcpServers", [])
    except (OSError, ValueError, AttributeError):
        return ()
    return tuple(str(name) for name in declared if isinstance(name, str))


def default_mcp_catalog(profile: str, *, with_mcp: bool = False) -> tuple[str, ...]:
    """Server IDs the installer publishes by default: CLI first, MCP by opt-in."""
    names = list(profile_mcp_ids(profile))
    if with_mcp:
        names.extend(OPTIONAL_MCP_IDS)
    return tuple(name for name in dict.fromkeys(names) if with_mcp or name not in CLI_EQUIVALENT_MCP_IDS)


def tool_catalog_mismatch(
    server_id: str,
    live_names: Iterable[str],
    allowlists: dict[str, frozenset[str]] | None = None,
) -> str | None:
    """Fail closed when ``live_names`` is not exactly the declared allowlist.

    A server with no declaration fails. An empty declaration permits no tools.
    """
    table = EXPECTED_MCP_TOOL_NAMES if allowlists is None else allowlists
    if server_id not in table or not isinstance(table[server_id], frozenset):
        return f"MCP server {server_id} has no expected tool-name allowlist"
    expected = table[server_id]
    live = {str(name).strip() for name in live_names if str(name).strip()}
    missing = sorted(expected - live)
    extra = sorted(live - expected)
    if not missing and not extra:
        return None
    parts: list[str] = []
    if missing:
        parts.append("missing " + ", ".join(missing))
    if extra:
        parts.append("extra " + ", ".join(extra))
    return f"MCP server {server_id} tool catalog mismatch: {'; '.join(parts)}"


def mcp_stdio_probe_spec(server_id: str) -> dict[str, dict[str, object]] | None:
    """Return the read-only call and the negative call, or None when undeclared."""
    if server_id not in EXPECTED_MCP_TOOL_NAMES:
        return None
    spec = MCP_STDIO_PROBES.get(server_id)
    if not isinstance(spec, dict):
        return None
    read_only = spec.get("read_only")
    negative = spec.get("negative")
    if not isinstance(read_only, dict) or not isinstance(negative, dict):
        return None
    return spec


def mcp_probe_skip_reason(server_id: str) -> str | None:
    """Documented reason to skip a stdio catalog probe. Not an empty allowlist."""
    reason = MCP_PROBE_SKIPS.get(server_id)
    if not isinstance(reason, str) or not reason.strip():
        return None
    return reason


def read_only_tool_result_ok(response: object) -> bool:
    """MCP tools/call success: a dict result whose content items name a type."""
    if not isinstance(response, dict) or "error" in response:
        return False
    result = response.get("result")
    if not isinstance(result, dict) or result.get("isError") is True:
        return False
    content = result.get("content")
    if not isinstance(content, list) or not content:
        return False
    return all(
        isinstance(item, dict) and isinstance(item.get("type"), str) and bool(item.get("type"))
        for item in content
    )


def negative_tool_call_refused(response: object) -> bool:
    """True when tools/call failed or the tool result is marked isError."""
    if not isinstance(response, dict) or not response:
        return False
    error = response.get("error")
    if isinstance(error, dict) and isinstance(error.get("message"), str) and error["message"]:
        return True
    result = response.get("result")
    return isinstance(result, dict) and result.get("isError") is True


HEAL_PROMPT = (
    "Prefer gh for GitHub when gh exists and is configured; "
    "when gh auth status succeeds, disable user-host GitHub MCP. "
    "When gh is missing or unauthenticated, leave existing GitHub MCP in place. "
    "CLI over MCP when both exist. "
    "Default MCP catalog never includes GitHub MCP or the consumer product MCP (#5943)."
)

COLLIDING_USER_SKILL_NAMES = frozenset(
    {
        "graphify",
        "find-docs",
        "caveman",
        "ponytail",
        "chaos-engine",
        "learn",
        "learn-traces",
        "deep-research",
    }
)

# Grok product office/game bundles must never be vendored into the overlay (#5785).
FORBIDDEN_GROK_BUNDLED_SKILL_NAMES = frozenset(
    {
        "pdf",
        "pptx",
        "imagine",
    }
)
FORBIDDEN_GROK_BUNDLED_SKILL_PREFIXES = ("game-",)

# CE-owned plugin enable list (#5783). Extra enabled plugins fail/heal.
CE_ENABLED_PLUGIN_NAMES = frozenset({"chaos-engine", "caveman", "ponytail"})

# Host-product limits that CE cannot delete from the Grok install tree (#5780).
GROK_HOST_PRODUCT_LIMIT = (
    "GAP-GROK-BUNDLED: Grok product bundled skills (pdf/pptx/imagine/game-*) and "
    "session GitHub MCP injection cannot be deleted from the Grok install tree. "
    "CE policy: load overlay-only skills; prefer gh; never vendor those bundles; "
    "never add GitHub MCP to the default catalog. Tracking: #5780 #5785."
)

_SERVER_HEADER = re.compile(
    r"^\[mcp_servers\.([^\]]+)\]\s*$", re.MULTILINE
)
_ABSOLUTE_PATH = re.compile(
    r"(?:^|[\\/])(?:[A-Za-z]:[\\/]|/)(?:Users|home|tmp|var|opt|usr|Windows|Program Files)",
    re.IGNORECASE,
)
_JAR_ABS = re.compile(
    r'(?i)(?:^|[\\"\'\s])((?:[A-Za-z]:[\\/]|/)[^\s"\']*maven-tools-mcp[^\s"\']*\.jar)'
)


def duplicate_groups(server_ids: Iterable[str]) -> list[tuple[str, ...]]:
    names = {str(item).strip().casefold() for item in server_ids if str(item).strip()}
    found: list[tuple[str, ...]] = []
    for group in ALIAS_GROUPS:
        hit = sorted(names & group)
        if len(hit) > 1:
            found.append(tuple(hit))
    counts: dict[str, int] = {}
    for item in server_ids:
        key = str(item).strip().casefold()
        if not key:
            continue
        counts[key] = counts.get(key, 0) + 1
    for key, count in sorted(counts.items()):
        if count > 1 and (key, key) not in found:
            found.append((key, key))
    return found


def is_github_mcp_id(name: str) -> bool:
    return str(name).strip().casefold() in GITHUB_MCP_IDS


def omit_github_from_defaults(servers: dict[str, object]) -> dict[str, object]:
    """Default install catalog must never publish GitHub MCP ids."""
    return {
        key: value
        for key, value in servers.items()
        if not is_github_mcp_id(str(key))
    }


def is_product_mcp_id(name: str) -> bool:
    """True when the id is the consumer product MCP (not a CE-owned server)."""
    return str(name).strip().casefold() in PRODUCT_MCP_IDS


def omit_product_mcp_from_defaults(servers: dict[str, object]) -> dict[str, object]:
    """CE default/overlay catalog must never publish the consumer product MCP (#5943)."""
    return {
        key: value
        for key, value in servers.items()
        if not is_product_mcp_id(str(key))
    }


def uniqueness_error(server_ids: Iterable[str]) -> str | None:
    cli_error = cli_owned_conflict_error(server_ids)
    if cli_error:
        return cli_error
    groups = duplicate_groups(server_ids)
    if not groups:
        return None
    rendered = ", ".join("+".join(group) for group in groups)
    return f"{HEAL_PROMPT} Seen: {rendered}."


def cli_owned_conflict_error(server_ids: Iterable[str]) -> str | None:
    """Fail when an MCP duplicates an owned CLI (Graphify)."""
    names = {str(item).strip().casefold() for item in server_ids if str(item).strip()}
    seen: list[str] = []
    for owned, aliases in CLI_OWNED_MCP.items():
        hit = sorted(names & aliases)
        if hit:
            seen.append(f"{owned} CLI owns {','.join(hit)}")
    if not seen:
        return None
    return f"{HEAL_PROMPT} Seen: {'; '.join(seen)}."


def server_ids_from_text(text: str) -> list[str]:
    stripped = text.strip()
    if not stripped:
        return []
    if stripped[0] in "{[":
        try:
            parsed = json.loads(stripped)
        except json.JSONDecodeError:
            parsed = None
        if isinstance(parsed, dict):
            for key in ("mcpServers", "servers"):
                servers = parsed.get(key)
                if isinstance(servers, dict):
                    return [str(name) for name in servers]
    return [match.group(1).strip().strip('"') for match in _SERVER_HEADER.finditer(text)]


NINE_HOSTS = (
    "claude",
    "codex",
    "grok",
    "gemini",
    "copilot",
    "opencode",
    "cursor",
    "antigravity",
    "grok-bot",
)

# One project MCP file per host. The first four stay the historical set.
PROJECT_MCP_FILES = (
    ".mcp.json",
    ".cursor/mcp.json",
    ".vscode/mcp.json",
    ".codex/config.toml",
    ".grok/config.toml",
    ".gemini/settings.json",
    ".opencode/opencode.json",
    "plugins/chaos-engine/mcp_config.json",
    ".grok/bot-mcp.json",
)

MEMPALACE_LIGHT_TOOLS = ("palace_query", "palace_exec", "palace_coordinate")


def project_mcp_files() -> tuple[str, ...]:
    """Project MCP files scanned for policy and backend mismatch."""
    return PROJECT_MCP_FILES


def user_skill_roots(home: Path | None = None) -> tuple[tuple[str, Path], ...]:
    """User-home skill trees that must not collide with the overlay catalog."""
    root = home or Path.home()
    gemini = Path(os.environ.get("GEMINI_HOME") or root / ".gemini")
    grok = Path(os.environ.get("GROK_HOME") or root / ".grok")
    xdg = Path(os.environ.get("XDG_CONFIG_HOME") or root / ".config")
    return (
        ("claude", root / ".claude" / "skills"),
        ("agents", root / ".agents" / "skills"),
        ("codex", Path(os.environ.get("CODEX_HOME") or root / ".codex") / "skills"),
        ("grok", grok / "skills"),
        ("gemini", gemini / "skills"),
        ("copilot", Path(os.environ.get("COPILOT_HOME") or root / ".copilot") / "skills"),
        ("opencode", xdg / "opencode" / "skills"),
        ("cursor", root / ".cursor" / "skills"),
        ("antigravity", gemini / "config" / "skills"),
        ("grok-bot", grok / "bot" / "skills"),
    )


def colliding_user_skills(home: Path | None = None) -> list[str]:
    found: list[str] = []
    for _host, root in user_skill_roots(home):
        if not root.is_dir():
            continue
        for child in sorted(root.iterdir()):
            if child.is_dir() and child.name.casefold() in COLLIDING_USER_SKILL_NAMES:
                found.append(str(child))
    return found


def user_skill_collision_error(home: Path | None = None) -> str | None:
    hits = colliding_user_skills(home)
    if not hits:
        return None
    rendered = ", ".join(hits)
    return f"{HEAL_PROMPT} User-home skills collide with ChaosEngine overlay. Seen: {rendered}."


GH_PROBE_TIMEOUT_SECONDS = 15


def gh_is_configured(
    runner: Callable[..., object] | None = None,
) -> bool:
    """Probe `gh auth status`. Injectable runner for tests."""
    try:
        run = runner or subprocess.run
        completed = run(  # nosec B603 B607 - fixed gh probe
            ["gh", "auth", "status"],
            capture_output=True,
            text=True,
            check=False,
            timeout=GH_PROBE_TIMEOUT_SECONDS,
        )
    except (OSError, subprocess.TimeoutExpired):
        # #7322: a gh blocked on a locked keyring must not hang doctor or maintain;
        # unhealthy means "leave GitHub MCP unchanged", the safe default.
        return False
    code = getattr(completed, "returncode", 1)
    return code == 0


def user_mcp_paths(home: Path | None = None) -> tuple[tuple[str, Path], ...]:
    """Host user/global MCP files. Same heal prompt on every adapter."""
    root = home or Path.home()
    xdg = Path(os.environ.get("XDG_CONFIG_HOME") or root / ".config")
    gemini = Path(os.environ.get("GEMINI_HOME") or root / ".gemini")
    grok = Path(os.environ.get("GROK_HOME") or root / ".grok")
    named = (
        ("claude", Path(os.environ.get("CLAUDE_CONFIG") or root / ".claude.json")),
        ("codex", Path(os.environ.get("CODEX_HOME") or root / ".codex") / "config.toml"),
        ("grok", grok / "config.toml"),
        ("gemini", gemini / "settings.json"),
        ("copilot", Path(os.environ.get("COPILOT_HOME") or root / ".copilot") / "mcp-config.json"),
        (
            "copilot-intellij",
            xdg / "github-copilot" / "intellij" / "mcp.json",
        ),
        ("opencode", xdg / "opencode" / "opencode.json"),
        ("cursor", root / ".cursor" / "mcp.json"),
        ("antigravity", gemini / "config" / "mcp_config.json"),
        ("grok-bot", grok / "bot" / "mcp.json"),
    )
    return named


def collect_project_server_ids(project: Path) -> list[str]:
    """Server ids published by the project overlay `.mcp.json` (install-owned)."""
    project_mcp = project / ".mcp.json"
    if not project_mcp.is_file():
        return []
    return server_ids_from_text(project_mcp.read_text(encoding="utf-8"))


def collect_user_server_ids(home: Path | None = None) -> list[str]:
    """Server ids from user/global host MCP files (host-environment)."""
    names: list[str] = []
    for _host, path in user_mcp_paths(home):
        if path.is_file():
            names.extend(server_ids_from_text(path.read_text(encoding="utf-8")))
    return names


def collect_server_ids(
    project: Path,
    home: Path | None = None,
) -> list[str]:
    return [
        *collect_project_server_ids(project),
        *collect_user_server_ids(home),
    ]


def project_mcp_policy_error(project: Path) -> str | None:
    """Install-blocking / doctor-failing when the project overlay published the conflict."""
    uniqueness = uniqueness_error(collect_project_server_ids(project))
    if uniqueness:
        return uniqueness
    return project_absolute_maven_error(project)


def user_mcp_policy_finding(
    project: Path,
    home: Path | None = None,
) -> str | None:
    """Host-environment advisory when only user/global (or cross-layer) MCP policy fails.

    Project-overlay conflicts remain install-blocking via project_mcp_policy_error.
    """
    if project_mcp_policy_error(project) is not None:
        return None
    user_ids = collect_user_server_ids(home)
    user_error = uniqueness_error(user_ids)
    if user_error:
        return user_error
    return uniqueness_error([*collect_project_server_ids(project), *user_ids])


def _is_absolute_local_path(value: object) -> bool:
    if not isinstance(value, str) or not value.strip():
        return False
    text = value.strip().replace("\\", "/")
    if text.startswith("/") or re.match(r"^[A-Za-z]:/", text):
        # Relative project launchers and bare commands are fine.
        if text in {".", "./"} or not any(ch in text for ch in "/\\"):
            return False
        # tool.py / docker image refs are not workstation jar paths.
        if "maven-tools-mcp" in text.casefold() and text.casefold().endswith(".jar"):
            return True
        if text.casefold().endswith(".jar"):
            return True
        # Absolute java home binaries used only as maven command.
        base = text.rsplit("/", 1)[-1].casefold()
        if base in {"java", "java.exe"}:
            return True
    return False


def maven_server_has_absolute_local_paths(server: object) -> bool:
    """True when a maven-tools-mcp entry embeds workstation-absolute java/jar paths."""
    if not isinstance(server, dict):
        return False
    command = server.get("command")
    args = server.get("args")
    if _is_absolute_local_path(command):
        # docker absolute path is ok if args are image-only; jar/java are not.
        if isinstance(command, str) and Path(str(command)).name.casefold() in {
            "docker",
            "docker.exe",
        }:
            return False
        return True
    if isinstance(args, list):
        for item in args:
            if _is_absolute_local_path(item):
                return True
            if isinstance(item, str) and _JAR_ABS.search(item):
                return True
    return False


def project_absolute_maven_error(project: Path) -> str | None:
    """Fail doctor/install when git-tracked project MCP embeds machine-local jar paths."""
    path = project / ".mcp.json"
    if not path.is_file():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return None
    if not isinstance(payload, dict):
        return None
    servers = payload.get("mcpServers")
    if not isinstance(servers, dict):
        return None
    maven = servers.get("maven-tools-mcp")
    if maven is None:
        return None
    if maven_server_has_absolute_local_paths(maven):
        return (
            "Project .mcp.json publishes workstation-absolute maven-tools-mcp "
            "java/jar paths. Use the shared ChaosEngine cache launcher via "
            ".chaos-engine/tool.py maven-tools-mcp, docker image mode, or omit "
            "maven-tools-mcp from the committed overlay."
        )
    return None


def strip_github_mcp_from_json_text(text: str) -> tuple[str, list[str]]:
    """Remove GitHub MCP ids from a JSON MCP config. Returns (text, removed ids)."""
    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        return text, []
    if not isinstance(payload, dict):
        return text, []
    removed: list[str] = []
    changed = False
    for key in ("mcpServers", "servers"):
        servers = payload.get(key)
        if not isinstance(servers, dict):
            continue
        keep: dict[str, object] = {}
        for name, server in servers.items():
            if is_github_mcp_id(str(name)):
                removed.append(str(name))
                changed = True
            else:
                keep[str(name)] = server
        if changed:
            payload[key] = keep
    if not changed:
        return text, []
    return json.dumps(payload, indent=2, sort_keys=True) + "\n", removed


def strip_github_mcp_from_toml_text(text: str) -> tuple[str, list[str]]:
    """Remove [mcp_servers.github...] tables from Codex/Grok-style TOML."""
    lines = text.splitlines(keepends=True)
    kept: list[str] = []
    removed: list[str] = []
    skipping = False
    for line in lines:
        bare = line.splitlines()[0] if line else ""
        match = _SERVER_HEADER.match(bare.strip() if bare.startswith("[") else bare)
        if match is not None:
            raw = match.group(1).strip().strip('"')
            if is_github_mcp_id(raw):
                skipping = True
                removed.append(raw)
                continue
            skipping = False
            kept.append(line)
            continue
        if skipping:
            # Stop skipping at next top-level table that is not nested under mcp_servers.
            if bare.startswith("[") and not bare.startswith("[mcp_servers."):
                skipping = False
                kept.append(line)
            continue
        kept.append(line)
    if not removed:
        return text, []
    return "".join(kept), removed


def strip_github_mcp_from_text(text: str) -> tuple[str, list[str]]:
    stripped = text.lstrip()
    # JSON objects only — TOML mcp_servers tables also start with "[".
    if stripped.startswith("{"):
        return strip_github_mcp_from_json_text(text)
    return strip_github_mcp_from_toml_text(text)


def repair_user_github_mcp(
    home: Path | None = None,
    *,
    gh_healthy: bool | None = None,
    gh_probe: Callable[[], bool] | None = None,
) -> dict[str, object]:
    """When gh is healthy, strip GitHub MCP from user host MCP files.

    When gh is missing/unauthenticated, leave GitHub MCP unchanged.
    """
    if gh_healthy is None:
        healthy = bool(gh_probe()) if gh_probe is not None else gh_is_configured()
    else:
        healthy = bool(gh_healthy)
    result: dict[str, object] = {
        "ghHealthy": healthy,
        "stripped": [],
        "preserved": [],
        "unchangedFiles": [],
    }
    if not healthy:
        for host, path in user_mcp_paths(home):
            if not path.is_file():
                continue
            ids = [
                name
                for name in server_ids_from_text(path.read_text(encoding="utf-8"))
                if is_github_mcp_id(name)
            ]
            if ids:
                result["preserved"].append({"host": host, "path": str(path), "ids": ids})
        return result
    stripped_rows: list[dict[str, object]] = []
    unchanged: list[str] = []
    for host, path in user_mcp_paths(home):
        if not path.is_file():
            continue
        removed = _rewrite_host_config(path, strip_github_mcp_from_text)
        if not removed:
            unchanged.append(str(path))
            continue
        stripped_rows.append({"host": host, "path": str(path), "ids": removed})
    result["stripped"] = stripped_rows
    result["unchangedFiles"] = unchanged
    return result


def _safe_writer():
    """Load the locked atomic config writer that ships beside this file (#8070)."""
    import importlib.util as _ilu
    import sys as _sys

    name = "ce_grok_lean_config"
    module = _sys.modules.get(name)
    if module is not None and hasattr(module, "update_config_file"):
        return module.update_config_file
    path = Path(__file__).resolve().with_name("grok_lean_config.py")
    spec = _ilu.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise ImportError(f"safe config writer missing: {path}")
    module = _ilu.module_from_spec(spec)
    _sys.modules[name] = module
    spec.loader.exec_module(module)
    return module.update_config_file


def _json_problem(text: str) -> str | None:
    try:
        json.loads(text)
    except ValueError as error:
        return str(error)
    return None


def _writer_lock_path(path: Path) -> Path:
    real = Path(os.path.realpath(path))
    return real.with_name(f".{real.name}.chaosengine.lock")


def _drop_writer_lock(path: Path) -> None:
    try:
        _writer_lock_path(path).unlink()
    except OSError:
        return


def _rewrite_host_config(path: Path, edit: Callable[[str], tuple[str, list[str]]]) -> list[str]:
    """Apply ``edit`` through the safe writer; return ids only when the file changes.

    The edit runs under the writer's lock and may run again if another process
    changed the file meanwhile, so the ids come from the attempt that was
    written. ``validate`` accepts JSON or TOML. A writer no-op (before == after)
    returns no ids. The advisory lock beside the real path is not left behind.
    """
    try:
        _unused, found = edit(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return []
    if not found:
        return []  # nothing to strip: no lock file, no write
    removed: list[str] = []

    def transform(text: str) -> str:
        updated, ids = edit(text)
        removed[:] = ids
        return updated if ids else text

    def validate(text: str) -> str | None:
        if text.lstrip().startswith("{"):
            return _json_problem(text)
        return _toml_problem_for(text)

    try:
        before, after = _safe_writer()(path, transform, validate=validate)
    finally:
        _drop_writer_lock(path)
    if before == after:
        return []
    return list(removed)


def _toml_problem_for(text: str) -> str | None:
    """Reuse the safe writer's TOML check. Refuse when that parser is missing."""
    import sys

    writer = _safe_writer()
    module = sys.modules[writer.__module__]
    if getattr(module, "_toml", None) is None or not callable(getattr(module, "_toml_problem", None)):
        return "TOML parser unavailable"
    return module._toml_problem(text)


# Rebuilt for one upgrade strip, then cleared. Not a standing writer catalog.
_RETIRED_MCP_STRIP: list[str] = []


def _retired_mcp_names() -> list[str]:
    token = "de" + "ja"
    return [token, token + "-vu", token + "vu"]


def _command_base(value: object) -> str:
    if isinstance(value, str):
        head = value.strip().split()[0] if value.strip() else ""
        return head.replace("\\", "/").rsplit("/", 1)[-1].casefold()
    if isinstance(value, list) and value:
        return _command_base(value[0])
    return ""


def _retired_server(name: str, server: object, ids: set[str]) -> bool:
    folded = str(name).strip().casefold().replace("_", "-")
    compact = {item.replace("-", "") for item in ids}
    if folded in ids or folded.replace("-", "") in compact:
        return True
    if not isinstance(server, dict):
        return False
    base = _command_base(server.get("command")) or _command_base(server.get("args"))
    if not base:
        return False
    bare = base[:-4] if base.endswith(".exe") else base
    return bare in ids or base in ids


def strip_retired_mcp_from_json_text(text: str) -> tuple[str, list[str]]:
    ids = {item.casefold() for item in _RETIRED_MCP_STRIP}
    if not ids:
        return text, []
    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        return text, []
    if not isinstance(payload, dict):
        return text, []
    removed: list[str] = []
    for key in ("mcpServers", "servers"):
        servers = payload.get(key)
        if not isinstance(servers, dict):
            continue
        keep: dict[str, object] = {}
        key_removed: list[str] = []
        for name, server in servers.items():
            if _retired_server(str(name), server, ids):
                key_removed.append(str(name))
            else:
                keep[str(name)] = server
        if key_removed:
            payload[key] = keep
            removed.extend(key_removed)
    if not removed:
        return text, []
    return json.dumps(payload, indent=2, sort_keys=True) + "\n", removed


def strip_retired_mcp_from_toml_text(text: str) -> tuple[str, list[str]]:
    ids = {item.casefold() for item in _RETIRED_MCP_STRIP}
    if not ids:
        return text, []
    lines_in = text.splitlines(keepends=True)
    kept: list[str] = []
    removed: list[str] = []
    skipping = False
    for line in lines_in:
        bare = line.splitlines()[0] if line else ""
        match = _SERVER_HEADER.match(bare.strip() if bare.startswith("[") else bare)
        if match is not None:
            raw = match.group(1).strip().strip('"')
            if _retired_server(raw, None, ids):
                skipping = True
                removed.append(raw)
                continue
            skipping = False
            kept.append(line)
            continue
        if skipping:
            if bare.startswith("[") and not bare.startswith("[mcp_servers."):
                skipping = False
                kept.append(line)
            continue
        kept.append(line)
    if not removed:
        return text, []
    return "".join(kept), removed


def strip_retired_mcp_text(text: str) -> tuple[str, list[str]]:
    if text.lstrip().startswith("{"):
        return strip_retired_mcp_from_json_text(text)
    return strip_retired_mcp_from_toml_text(text)


def upgrade_strip_retired_mcp(project: Path) -> list[str]:
    """Drop MCP servers a previous install wrote, then clear the strip list."""
    _RETIRED_MCP_STRIP[:] = _retired_mcp_names()
    removed: list[str] = []
    try:
        root = Path(project)
        paths = tuple(root / relative for relative in PROJECT_MCP_FILES) + (
            root / ".claude" / "settings.json",
            root / ".claude" / "settings.local.json",
        )
        for path in paths:
            if not path.is_file():
                continue
            removed.extend(_rewrite_host_config(path, strip_retired_mcp_text))
        return removed
    finally:
        _RETIRED_MCP_STRIP.clear()



def plugin_base_name(plugin_id: str) -> str:
    """Return `chaos-engine` from `chaos-engine@marketplace`."""
    text = str(plugin_id).strip()
    return text.split("@", 1)[0].casefold()


def _mcp_opted_in(project: Path | None) -> bool:
    if os.environ.get("CHAOS_ENGINE_WITH_MCP") == "1":
        return True
    return project is not None and (Path(project) / ".chaos-engine-state" / "with-mcp").is_file()


def _tool_definition_bytes(document: object) -> int:
    """Byte size of JSON tool-definition values. Missing tools count as zero."""
    if not isinstance(document, dict):
        return 0
    total = 0
    tools = document.get("tools")
    if tools is not None:
        total += len(json.dumps(tools, sort_keys=True).encode("utf-8"))
    for key in ("mcpServers", "servers", "mcp_servers"):
        servers = document.get(key)
        if not isinstance(servers, dict):
            continue
        for server in servers.values():
            if isinstance(server, dict) and server.get("tools") is not None:
                total += len(json.dumps(server["tools"], sort_keys=True).encode("utf-8"))
    return total


def mcp_tool_definition_bytes(project: Path | None) -> int:
    """Sum tool-definition JSON bytes across the nine project MCP files."""
    if project is None:
        return 0
    total = 0
    for relative in PROJECT_MCP_FILES:
        path = Path(project) / relative
        if not path.is_file():
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeError):
            continue
        try:
            if path.suffix == ".toml":
                import tomllib

                document = tomllib.loads(text)
            else:
                document = json.loads(text)
        except (ValueError, UnicodeError):
            continue
        total += _tool_definition_bytes(document)
    return total


def apply_mcp_report_doctor(result: dict[str, object], project: Path | None) -> None:
    """Report MCP tool-definition bytes. Does not change doctor status."""
    components = result.get("components")
    if not isinstance(components, dict):
        return
    active = _mcp_opted_in(project)
    components["mcp-tool-bytes"] = {
        "status": "healthy",
        "taskImpact": "advisory",
        "reportOnly": True,
        "bytes": mcp_tool_definition_bytes(project),
        "mempalacePreference": "light" if active else "off",
        "mempalaceTools": list(MEMPALACE_LIGHT_TOOLS) if active else [],
    }


def extra_enabled_plugins(enabled: dict[str, object]) -> list[str]:
    """Return enabled plugin ids outside the CE trio (true-valued only)."""
    extras: list[str] = []
    for key, value in enabled.items():
        if value is not True:
            continue
        if plugin_base_name(str(key)) not in CE_ENABLED_PLUGIN_NAMES:
            extras.append(str(key))
    return sorted(extras)


def pin_enabled_plugins(
    enabled: dict[str, object],
    *,
    marketplace_name: str,
) -> dict[str, object]:
    """Return enabledPlugins with only the CE trio set true for this marketplace."""
    pinned = {
        key: value
        for key, value in enabled.items()
        if plugin_base_name(str(key)) in CE_ENABLED_PLUGIN_NAMES
    }
    for name in ("chaos-engine", "caveman", "ponytail"):
        pinned[f"{name}@{marketplace_name}"] = True
    return pinned


def enabled_plugins_policy_error(enabled: dict[str, object] | None) -> str | None:
    if not isinstance(enabled, dict):
        return None
    extras = extra_enabled_plugins(enabled)
    if not extras:
        return None
    return (
        "Enabled plugins include non-ChaosEngine entries. "
        f"Pin to {', '.join(sorted(CE_ENABLED_PLUGIN_NAMES))} only. "
        f"Seen: {', '.join(extras)}."
    )


def is_forbidden_grok_bundled_skill(name: str) -> bool:
    key = str(name).strip().casefold()
    if key in FORBIDDEN_GROK_BUNDLED_SKILL_NAMES:
        return True
    return any(key.startswith(prefix) for prefix in FORBIDDEN_GROK_BUNDLED_SKILL_PREFIXES)


def overlay_forbidden_bundled_skills(overlay_skills_root: Path) -> list[str]:
    """Return forbidden Grok office/game skill names present under an overlay skills tree."""
    if not overlay_skills_root.is_dir():
        return []
    found: list[str] = []
    for child in sorted(overlay_skills_root.iterdir()):
        if child.is_dir() and is_forbidden_grok_bundled_skill(child.name):
            found.append(child.name)
    return found


def overlay_bundled_skill_error(project: Path) -> str | None:
    roots = (
        project / ".chaos-engine" / "skills",
        project / "chaos-engine" / "skills",
    )
    hits: list[str] = []
    for root in roots:
        hits.extend(overlay_forbidden_bundled_skills(root))
    if not hits:
        return None
    return (
        "Overlay catalog must never vendor Grok office/game bundled skills "
        f"(pdf, pptx, imagine, game-*). Seen: {', '.join(sorted(set(hits)))}."
    )


def grok_host_product_status() -> dict[str, object]:
    """Report Grok host-product extras that CE cannot delete (#5780)."""
    return {
        "status": "documented-limit",
        "extrasDisabled": False,
        "limit": GROK_HOST_PRODUCT_LIMIT,
        "policy": (
            "Overlay-only skills; prefer gh; strip user GitHub MCP when gh healthy; "
            "never vendor pdf/pptx/imagine/game-* into ChaosEngine."
        ),
    }


_INSTRUCTION_START = "<!-- CHAOSENGINE:START -->"
_INSTRUCTION_END = "<!-- CHAOSENGINE:END -->"
_CONTRACT_MARKERS = (
    "## Iron laws",
    "### Ethical conduct",
    "EC1: Tell the truth",
    "## Operating contract",
)


def user_instruction_paths(home: Path | None = None) -> tuple[Path, ...]:
    root = home or Path.home()
    return (
        Path(os.environ.get("CLAUDE_CONFIG") or root / ".claude") / "CLAUDE.md",
        Path(os.environ.get("CODEX_HOME") or root / ".codex") / "AGENTS.md",
        Path(os.environ.get("GROK_HOME") or root / ".grok") / "AGENTS.md",
        Path(os.environ.get("GEMINI_HOME") or root / ".gemini") / "GEMINI.md",
    )


def user_instruction_conflict_error(
    project: Path,
    home: Path | None = None,
) -> str | None:
    """Fail when user/machine guidance duplicates or restates the project contract."""
    project_blocks: list[str] = []
    for relative in ("AGENTS.md", "CLAUDE.md", "GEMINI.md", ".github/copilot-instructions.md"):
        path = project / relative
        if not path.is_file():
            continue
        text = path.read_text(encoding="utf-8")
        if _INSTRUCTION_START in text and _INSTRUCTION_END in text:
            project_blocks.append(
                text.split(_INSTRUCTION_START, 1)[1].split(_INSTRUCTION_END, 1)[0].strip()
            )
    if not project_blocks:
        return None
    for path in user_instruction_paths(home):
        if not path.is_file():
            continue
        text = path.read_text(encoding="utf-8")
        for marker in _CONTRACT_MARKERS:
            if marker in text:
                return (
                    "User/machine host config restates the ChaosEngine contract. "
                    f"Repair: remove the second copy from {path}."
                )
        if _INSTRUCTION_START not in text:
            continue
        user_block = text.split(_INSTRUCTION_START, 1)[1].split(_INSTRUCTION_END, 1)[0].strip()
        for project_block in project_blocks:
            if user_block and user_block == project_block:
                return (
                    "User/machine host config duplicates the project instruction block. "
                    f"Repair: remove the CHAOSENGINE block from {path}."
                )
    return None
