"""Installer option catalog and the flags both entry points share.

``bootstrap.py`` and ``install.py install`` call :func:`add_install_flags`.
``--repository`` and ``--project`` stay on the entry point that owns them.
"""

from __future__ import annotations

import argparse
import os
from dataclasses import dataclass
from pathlib import Path


HOST_IDS = (
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
HOST_ALIASES = {
    "agy": "antigravity",
}
COMPONENT_NAMES = (
    "memory",
    "mempalace",
    "graphify",
    "ponytail",
    "caveman",
    "icm-architect",
)
ADDON_IDS = (
    "design-skills",
    "shaft-engine-users",
    "shaft-core-developers",
)
MCP_SERVER_IDS = (
    "chaosengine-memory",
    "chaosengine-mempalace",
    "context7",
    "chrome-devtools-mcp",
)
CLI_ONLY_KEYS = frozenset({
    "dry_run",
    "yes",
    "json",
    "if_changed",
    "force",
})
MERGE_LIST_KEYS = frozenset({
    "addons.enabled",
    "stores.graphify.extra_ignore",
})
SECRET_KEY = __import__("re").compile(r"token|secret|password|key", __import__("re").IGNORECASE)


@dataclass(frozen=True)
class InstallOption:
    """One catalog row. ``key`` is the TOML key; empty when the row is CLI-only."""

    key: str
    default: object
    kind: str
    levels: str
    help: str
    env: tuple[str, ...] = ()
    env_kind: str = ""
    flags: tuple[str, ...] = ()
    dest: str = ""
    action: str = "store"
    choices: tuple[str, ...] = ()
    flag_value: object = None
    enable_flags: tuple[str, ...] = ()
    enable_dest: str = ""
    cli_only: bool = False
    merge: bool = False
    metavar: str = ""


def _opt(**kwargs: object) -> InstallOption:
    return InstallOption(**kwargs)  # type: ignore[arg-type]


def _components() -> list[InstallOption]:
    rows: list[InstallOption] = []
    for name in COMPONENT_NAMES:
        dest = name.replace("-", "_")
        rows.append(
            InstallOption(
                key=f"components.{name}",
                default=True,
                kind="bool",
                levels="UPL",
                help=f"Set false to disable default-on {name}. --without-{name} / --with-{name}.",
                flags=(f"--without-{name}",),
                dest=f"without_{dest}",
                action="store_true",
                flag_value=False,
                enable_flags=(f"--with-{name}",),
                enable_dest=f"with_{dest}",
            )
        )
    return rows


def build_catalog() -> tuple[InstallOption, ...]:
    """Every user-facing option. Defaults match the installer with no config file."""
    rows: list[InstallOption] = [
        _opt(
            key="source.repository",
            default="ShaftHQ/chaosengine-harness",
            kind="str",
            levels="UP",
            help="GitHub repository owner/name. Also CHAOS_ENGINE_REPOSITORY.",
            env=("CHAOS_ENGINE_REPOSITORY",),
            env_kind="str",
        ),
        _opt(
            key="source.ref",
            default="main",
            kind="str",
            levels="UP",
            help="Git ref to install. Also CHAOS_ENGINE_BRANCH.",
            env=("CHAOS_ENGINE_BRANCH",),
            env_kind="str",
            flags=("--branch",),
            dest="branch",
        ),
        _opt(
            key="source.version",
            default="latest",
            kind="str",
            levels="UP",
            help="Release 0.4.YYYYMMDD.N or a 40-hex commit. Also CHAOS_ENGINE_VERSION.",
            env=("CHAOS_ENGINE_VERSION",),
            env_kind="str",
            flags=("--version",),
            dest="version_pin",
        ),
        _opt(
            key="source.channel",
            default="main",
            kind="choice",
            levels="UP",
            help="Update channel: main or release.",
            env=("CHAOS_ENGINE_CHANNEL",),
            env_kind="choice",
            flags=("--channel",),
            dest="channel",
            choices=("main", "release"),
        ),
        _opt(
            key="network.offline",
            default=False,
            kind="bool",
            levels="UL",
            help="Use only the cache or --from-bundle. Also CHAOS_ENGINE_OFFLINE.",
            env=("CHAOS_ENGINE_OFFLINE",),
            env_kind="bool",
            flags=("--offline",),
            dest="offline",
            action="store_true",
            flag_value=True,
        ),
        _opt(
            key="network.bundle",
            default="",
            kind="path",
            levels="UL",
            help="Offline bundle zip. Also CHAOS_ENGINE_FROM_BUNDLE.",
            env=("CHAOS_ENGINE_FROM_BUNDLE",),
            env_kind="str",
            flags=("--from-bundle",),
            dest="from_bundle",
            metavar="ZIP",
        ),
        _opt(
            key="network.ca_bundle",
            default="",
            kind="path",
            levels="UL",
            help="PEM bundle for TLS interception. Also CHAOS_ENGINE_CA_BUNDLE. Exported as SSL_CERT_FILE.",
            env=("CHAOS_ENGINE_CA_BUNDLE",),
            env_kind="str",
            flags=("--ca-bundle",),
            dest="ca_bundle",
            metavar="PEM",
        ),
        _opt(
            key="network.use_gh_token",
            default=True,
            kind="bool",
            levels="U",
            help="Read gh auth token for downloads. CHAOS_ENGINE_GH_AUTH=0 turns it off.",
            env=("CHAOS_ENGINE_GH_AUTH",),
            env_kind="bool-default-true",
        ),
        _opt(
            key="install.scope",
            default="project",
            kind="choice",
            levels="U",
            help=(
                "Where to install. project: this folder (default, shared through git). "
                "user: every folder on this machine, no repo files. both: project and user."
            ),
            env=("CHAOS_ENGINE_SCOPE",),
            env_kind="choice",
            flags=("--scope",),
            dest="scope",
            choices=("project", "user", "both"),
        ),
        _opt(
            key="install.distribution",
            default="portable",
            kind="str",
            levels="P",
            help="Distribution id. Also CHAOS_ENGINE_DISTRIBUTION.",
            env=("CHAOS_ENGINE_DISTRIBUTION",),
            env_kind="str",
            flags=("--distribution",),
            dest="distribution",
        ),
        _opt(
            key="install.git_visibility",
            default="tracked",
            kind="choice",
            levels="UL",
            help="tracked, or excluded (consumer mode, CHAOS_ENGINE_CONSUMER=1).",
            env=("CHAOS_ENGINE_CONSUMER",),
            env_kind="consumer",
            flags=("--consumer",),
            dest="consumer",
            action="store_true",
            flag_value="excluded",
            enable_flags=("--tracked",),
            enable_dest="tracked",
            choices=("tracked", "excluded"),
        ),
        _opt(
            key="instructions.mode",
            default="merge",
            kind="choice",
            levels="UPL",
            help=(
                "How to treat existing agent instructions. merge (default): keep them and "
                "make ChaosEngine the primary driver. replace: back up, then delete them "
                "and install ChaosEngine's set (needs --yes when not interactive)."
            ),
            env=("CHAOS_ENGINE_MODE",),
            env_kind="choice",
            flags=("--mode",),
            dest="instructions_mode",
            choices=("merge", "replace"),
        ),
        _opt(
            key="instructions.placement",
            default="top",
            kind="choice",
            levels="P",
            help="Where the instruction block sits. Also CHAOS_ENGINE_INSTRUCTIONS_PLACEMENT.",
            env=("CHAOS_ENGINE_INSTRUCTIONS_PLACEMENT",),
            env_kind="choice",
            flags=("--instructions-placement",),
            dest="instructions_placement",
            choices=("top", "bottom"),
        ),
        _opt(
            key="hosts.enabled",
            default=(),
            kind="list",
            levels="UPL",
            help="Client ids to complete (comma-separated). Empty infers. Also CHAOS_ENGINE_HOST.",
            env=("CHAOS_ENGINE_HOST",),
            env_kind="csv",
            flags=("--hosts",),
            dest="hosts",
            action="append",
            choices=HOST_IDS,
        ),
        _opt(
            key="hosts.infer",
            default=True,
            kind="bool",
            levels="UP",
            help="Infer the host from the environment. --no-infer-hosts turns it off.",
            env=("CHAOS_ENGINE_INFER_HOSTS",),
            env_kind="bool-default-true",
            flags=("--no-infer-hosts",),
            dest="no_infer_hosts",
            action="store_true",
            flag_value=False,
        ),
        _opt(
            key="hosts.portable_files",
            default="all",
            kind="choice",
            levels="P",
            help="Write portable files for all hosts, or only enabled ones.",
            env=("CHAOS_ENGINE_PORTABLE_HOSTS",),
            env_kind="choice",
            flags=("--portable-hosts",),
            dest="portable_hosts",
            choices=("all", "enabled"),
        ),
        _opt(
            key="hosts.grok.lean_skills",
            default=False,
            kind="bool",
            levels="U",
            help="Disable Grok bundled game-* and imagine skills. Also CHAOS_ENGINE_LEAN_GROK_SKILLS=1.",
            env=("CHAOS_ENGINE_LEAN_GROK_SKILLS",),
            env_kind="bool",
            flags=("--lean-grok-skills",),
            dest="lean_grok_skills",
            action="store_true",
            flag_value=True,
        ),
        _opt(
            key="hosts.register_plugins",
            default=True,
            kind="bool",
            levels="UL",
            help="Register Codex and Claude plugins. --no-register-plugins turns it off.",
            env=("CHAOS_ENGINE_REGISTER_PLUGINS",),
            env_kind="bool-default-true",
            flags=("--no-register-plugins",),
            dest="no_register_plugins",
            action="store_true",
            flag_value=False,
        ),
        *_components(),
        _opt(
            key="addons.enabled",
            default=(),
            kind="list",
            levels="UPL",
            help="Optional add-on ids. Lists merge across levels. Also CHAOS_ENGINE_ADDONS.",
            env=("CHAOS_ENGINE_ADDONS",),
            env_kind="csv",
            merge=True,
            choices=ADDON_IDS,
        ),
        _opt(
            key="addons.auto_detect",
            default=True,
            kind="bool",
            levels="P",
            help="Detect a project pack. --no-auto-addons turns it off.",
            env=("CHAOS_ENGINE_NO_AUTO_ADDONS",),
            env_kind="bool-invert",
            flags=("--no-auto-addons",),
            dest="no_auto_addons",
            action="store_true",
            flag_value=False,
        ),
        _opt(
            key="packs.shaft_skills_version",
            default="auto",
            kind="str",
            levels="P",
            help="SHAFT skills tag. Also CHAOS_ENGINE_SHAFT_SKILLS_VERSION.",
            env=("CHAOS_ENGINE_SHAFT_SKILLS_VERSION",),
            env_kind="str",
            flags=("--shaft-skills-version",),
            dest="shaft_skills_version",
        ),
        _opt(
            key="packs.post_install",
            default=True,
            kind="bool",
            levels="PL",
            help="Run the project pack postInstall. --skip-pack-post-install turns it off.",
            env=("CHAOS_ENGINE_PACK_POST_INSTALL",),
            env_kind="bool-default-true",
            flags=("--skip-pack-post-install",),
            dest="skip_pack_post_install",
            action="store_true",
            flag_value=False,
        ),
        _opt(
            key="mcp.publish",
            default=False,
            kind="bool",
            levels="UPL",
            help="Publish CLI-equivalent MCP servers. Also CHAOS_ENGINE_WITH_MCP.",
            env=("CHAOS_ENGINE_WITH_MCP",),
            env_kind="bool",
            flags=("--with-mcp",),
            dest="with_mcp",
            action="store_true",
            flag_value=True,
            enable_flags=("--without-mcp",),
            enable_dest="without_mcp",
        ),
        _opt(
            key="mcp.servers",
            default=(),
            kind="list",
            levels="UPL",
            help="MCP server ids when publish is on. Also CHAOS_ENGINE_MCP_SERVERS.",
            env=("CHAOS_ENGINE_MCP_SERVERS",),
            env_kind="csv",
            flags=("--mcp-servers",),
            dest="mcp_servers",
            metavar="IDS",
            choices=MCP_SERVER_IDS,
        ),
        _opt(
            key="mcp.maven_tools.enabled",
            default=False,
            kind="bool",
            levels="PL",
            help="Install Maven Tools MCP. Also CHAOS_ENGINE_WITH_MAVEN_TOOLS.",
            env=("CHAOS_ENGINE_WITH_MAVEN_TOOLS",),
            env_kind="bool",
            flags=("--with-maven-tools",),
            dest="with_maven_tools",
            action="store_true",
            flag_value=True,
        ),
        _opt(
            key="mcp.maven_tools.mode",
            default="native",
            kind="choice",
            levels="UL",
            help="Maven Tools runtime. Also CHAOS_ENGINE_MAVEN_TOOLS_MODE.",
            env=("CHAOS_ENGINE_MAVEN_TOOLS_MODE",),
            env_kind="choice",
            flags=("--maven-tools-mode",),
            dest="maven_tools_mode",
            choices=("native", "docker"),
        ),
        _opt(
            key="provision.tools",
            default=True,
            kind="bool",
            levels="UL",
            help="Provision uv, Python, Node, and the stores. --skip-tools turns it off.",
            env=("CHAOS_ENGINE_SKIP_TOOLS",),
            env_kind="bool-invert",
            flags=("--skip-tools",),
            dest="skip_tools",
            action="store_true",
            flag_value=False,
        ),
        _opt(
            key="provision.prerequisites",
            default="auto",
            kind="choice",
            levels="UL",
            help="Prerequisites: auto, report, skip, or provision. --skip-prerequisites selects skip.",
            env=("CHAOS_ENGINE_PREREQUISITES",),
            env_kind="choice",
            flags=("--skip-prerequisites",),
            dest="skip_prerequisites",
            action="store_true",
            flag_value="skip",
            choices=("auto", "report", "skip", "provision"),
        ),
        _opt(
            key="paths.modify_user_path",
            default=True,
            kind="bool",
            levels="U",
            help="Change the user PATH on Windows. --no-modify-path turns it off.",
            env=("CHAOS_ENGINE_MODIFY_PATH",),
            env_kind="bool-default-true",
            flags=("--no-modify-path",),
            dest="no_modify_path",
            action="store_true",
            flag_value=False,
        ),
        _opt(
            key="paths.bin_dir",
            default="",
            kind="path",
            levels="U",
            help="Shim directory. Also CHAOS_ENGINE_SHIM_DIR. Empty uses the platform default.",
            env=("CHAOS_ENGINE_SHIM_DIR",),
            env_kind="str",
            flags=("--bin-dir",),
            dest="bin_dir",
            metavar="DIR",
        ),
        _opt(
            key="paths.cache_dir",
            default="",
            kind="path",
            levels="U",
            help="Download cache directory. Also CHAOS_ENGINE_CACHE_DIR.",
            env=("CHAOS_ENGINE_CACHE_DIR",),
            env_kind="str",
        ),
        _opt(
            key="paths.data_dir",
            default="",
            kind="path",
            levels="U",
            help="User data directory. Also CHAOS_ENGINE_USER_DIR.",
            env=("CHAOS_ENGINE_USER_DIR",),
            env_kind="str",
        ),
        _opt(
            key="cache.max_mb",
            default=0,
            kind="int",
            levels="U",
            help="Download cache cap in MiB. 0 is unlimited. Eviction is not active.",
            env=("CHAOS_ENGINE_CACHE_MAX_MB",),
            env_kind="int",
        ),
        _opt(
            key="edits.policy",
            default="copy-aside",
            kind="choice",
            levels="UPL",
            help="copy-aside keeps edited owned files. refuse exits before replacing them (--keep-edits).",
            env=("CHAOS_ENGINE_KEEP_EDITS",),
            env_kind="keep-edits",
            flags=("--keep-edits",),
            dest="keep_edits",
            action="store_true",
            flag_value="refuse",
            choices=("copy-aside", "refuse"),
        ),
        _opt(
            key="backups.keep",
            default=20,
            kind="int",
            levels="UP",
            help="How many backup stamps to keep. 0 is unlimited.",
            env=("CHAOS_ENGINE_BACKUP_KEEP",),
            env_kind="int",
            flags=("--backup-keep",),
            dest="backup_keep",
            metavar="N",
        ),
        _opt(
            key="git_hooks.secret_guard",
            default=True,
            kind="bool",
            levels="UPL",
            help="Wire the secret guard into git hooks. --no-secret-guard turns it off.",
            env=("CHAOS_ENGINE_SECRET_GUARD",),
            env_kind="bool-default-true",
            flags=("--no-secret-guard",),
            dest="no_secret_guard",
            action="secret_guard_off",
            flag_value=False,
        ),
        _opt(
            key="locks.project_wait_seconds",
            default=30,
            kind="int",
            levels="U",
            help="Seconds to wait for the project lock (1-600). Also CHAOS_ENGINE_LOCK_WAIT_SECONDS.",
            env=("CHAOS_ENGINE_LOCK_WAIT_SECONDS",),
            env_kind="int",
        ),
        _opt(
            key="hooks.guard_wait_ms",
            default=60000,
            kind="int",
            levels="UP",
            help="Guard wait in milliseconds (0-600000). Also CHAOS_ENGINE_GUARD_WAIT_MS.",
            env=("CHAOS_ENGINE_GUARD_WAIT_MS",),
            env_kind="int",
        ),
        _opt(
            key="stores.schedule",
            default=True,
            kind="bool",
            levels="U",
            help="Install the daily store-refresh timer. --no-store-schedule turns it off.",
            env=("CHAOS_ENGINE_STORE_SCHEDULE",),
            env_kind="bool-default-true",
            flags=("--no-store-schedule",),
            dest="no_store_schedule",
            action="store_true",
            flag_value=False,
        ),
        _opt(
            key="stores.schedule_at",
            default="03:15",
            kind="str",
            levels="U",
            help="Daily refresh clock time HH:MM. Also CHAOS_ENGINE_STORE_SCHEDULE_AT.",
            env=("CHAOS_ENGINE_STORE_SCHEDULE_AT",),
            env_kind="str",
        ),
        _opt(
            key="stores.refresh_on_session",
            default=True,
            kind="bool",
            levels="UL",
            help="Refresh a stale store when a session starts. CHAOS_ENGINE_STORE_REFRESH=0 turns it off.",
            env=("CHAOS_ENGINE_STORE_REFRESH",),
            env_kind="bool-default-true",
        ),
        _opt(
            key="stores.stall_seconds",
            default=120,
            kind="int",
            levels="U",
            help="Store-stall timeout in seconds. Also CHAOS_ENGINE_STALL_SECONDS.",
            env=("CHAOS_ENGINE_STALL_SECONDS",),
            env_kind="int",
        ),
        _opt(
            key="stores.graphify.extra_ignore",
            default=(),
            kind="list",
            levels="P",
            help="Extra Graphify ignore patterns. Merged with the harness ignores; it cannot remove them.",
            merge=True,
        ),
        _opt(
            key="stores.mempalace.mine",
            default="",
            kind="str",
            levels="UP",
            help="MemPalace mine mode. Also CHAOS_ENGINE_MEMPALACE_MINE.",
            env=("CHAOS_ENGINE_MEMPALACE_MINE",),
            env_kind="str",
        ),
        _opt(
            key="stores.mempalace.full",
            default="",
            kind="str",
            levels="UP",
            help="MemPalace full mine. Also CHAOS_ENGINE_MEMPALACE_FULL.",
            env=("CHAOS_ENGINE_MEMPALACE_FULL",),
            env_kind="str",
        ),
        _opt(
            key="stores.mempalace.collection",
            default="",
            kind="str",
            levels="UP",
            help="MemPalace collection. Also CHAOS_ENGINE_MEMPALACE_COLLECTION.",
            env=("CHAOS_ENGINE_MEMPALACE_COLLECTION",),
            env_kind="str",
        ),
        _opt(
            key="session.resume_stale_days",
            default=7,
            kind="int",
            levels="U",
            help="Days before a session resume is stale. Also CHAOS_ENGINE_RESUME_STALE_DAYS.",
            env=("CHAOS_ENGINE_RESUME_STALE_DAYS",),
            env_kind="int",
        ),
        _opt(
            key="ui.interactive",
            default=False,
            kind="bool",
            levels="U",
            help="Ask before each install operation.",
            flags=("--interactive",),
            dest="interactive",
            action="store_true",
            flag_value=True,
        ),
        _opt(
            key="ui.verbosity",
            default="normal",
            kind="choice",
            levels="U",
            help="quiet, normal, or verbose.",
            choices=("quiet", "normal", "verbose"),
            flags=("-q", "--quiet"),
            dest="quiet",
            action="store_true",
            flag_value="quiet",
            enable_flags=("--verbose",),
            enable_dest="verbose",
        ),
        _opt(
            key="ui.color",
            default="auto",
            kind="choice",
            levels="U",
            help="Colour mode. NO_COLOR and --no-color win over always. Also CHAOS_ENGINE_COLOR.",
            env=("CHAOS_ENGINE_COLOR",),
            env_kind="choice",
            flags=("--color",),
            dest="color",
            choices=("auto", "always", "never"),
        ),
        _opt(
            key="ui.ascii",
            default=False,
            kind="bool",
            levels="U",
            help="Force ASCII glyphs. Also CHAOS_ENGINE_ASCII=1.",
            env=("CHAOS_ENGINE_ASCII",),
            env_kind="bool",
            flags=("--ascii",),
            dest="ascii",
            action="store_true",
            flag_value=True,
        ),
        _opt(key="dry_run", default=False, kind="bool", levels="", help="Print the plan and write nothing.", flags=("-n", "--dry-run"), dest="dry_run", action="store_true", flag_value=True, cli_only=True),
        _opt(key="yes", default=False, kind="bool", levels="", help="Do not prompt. CI=1 and a non-interactive stdin imply this.", flags=("--yes", "--no-input"), dest="no_input", action="store_true", flag_value=True, cli_only=True),
        _opt(key="json", default=False, kind="bool", levels="", help="One JSON document on stdout.", flags=("--json",), dest="json", action="store_true", flag_value=True, cli_only=True),
        _opt(key="if_changed", default=False, kind="bool", levels="", help="No-op when the installed overlay already matches the source.", flags=("--if-changed",), dest="if_changed", action="store_true", flag_value=True, cli_only=True),
        _opt(key="force", default=False, kind="bool", levels="", help="Replace edited CE-owned files without copying them. This is not --mode replace.", flags=("--force",), dest="force", action="store_true", flag_value=True, cli_only=True),
        _opt(key="include_local", default=False, kind="bool", levels="", help="With --mode replace, also remove personal *.local files.", flags=("--include-local",), dest="include_local", action="store_true", flag_value=True, cli_only=True),
        _opt(key="allow_dirty", default=False, kind="bool", levels="", help="With --mode replace, allow uncommitted changes to instruction files.", flags=("--allow-dirty",), dest="allow_dirty", action="store_true", flag_value=True, cli_only=True),
        _opt(key="force_replace_source_tree", default=False, kind="bool", levels="", help="Allow --mode replace in the ChaosEngine or SHAFT_ENGINE source tree.", flags=("--force-replace-source-tree",), dest="force_replace_source_tree", action="store_true", flag_value=True, cli_only=True),
        _opt(key="no_user_hooks", default=False, kind="bool", levels="", help="Install user-level instructions and the skill, but no guard hooks.", flags=("--no-user-hooks",), dest="no_user_hooks", action="store_true", flag_value=True, cli_only=True),
        _opt(key="user_layer.hosts", default=(), kind="list", levels="U", help="Hosts to wire at user level. Also CHAOS_ENGINE_USER_HOSTS.", env=("CHAOS_ENGINE_USER_HOSTS",), env_kind="csv", flags=("--user-hosts",), dest="user_hosts", action="append", choices=HOST_IDS),
    ]
    return tuple(rows)


CATALOG: tuple[InstallOption, ...] = build_catalog()
BY_KEY = {row.key: row for row in CATALOG}


class _SecretGuardOff(argparse.Action):
    """``--no-secret-guard`` matches ``CHAOS_ENGINE_SECRET_GUARD=0``."""

    def __call__(self, parser, namespace, values, option_string=None):
        setattr(namespace, self.dest, True)
        os.environ["CHAOS_ENGINE_SECRET_GUARD"] = "0"


def add_install_flags(parser: argparse.ArgumentParser, *, entry: str) -> None:
    """Add the shared install flags. ``entry`` is ``bootstrap`` or ``install``."""
    del entry  # both entries receive the same shared set
    mcp = parser.add_mutually_exclusive_group()
    for row in CATALOG:
        if row.key == "mcp.publish":
            _add_row(mcp, row)
            continue
        if row.flags or row.enable_flags:
            _add_row(parser, row)
    parser.add_argument(
        "--config",
        dest="config_path",
        default=None,
        help="Read this file instead of the user config.toml.",
    )
    parser.add_argument("--source", type=Path, default=None, help="Local ChaosEngine source tree.")
    parser.add_argument("--commit", default=None, help="40-hex source pin.")
    parser.add_argument("--no-color", action="store_true", help="Disable ANSI color. In-place redraw stays on a TTY.")
    parser.add_argument("--no-hyperlinks", action="store_true", help="Do not emit OSC 8 hyperlinks.")
    parser.add_argument(
        "--copy-prompt",
        action="store_true",
        help="Copy the failure prompt on a local TTY (CHAOS_ENGINE_COPY_PROMPT=1).",
    )


def _add_row(parser: argparse.ArgumentParser, row: InstallOption) -> None:
    if row.flags:
        kwargs: dict[str, object] = {"dest": row.dest, "help": row.help}
        if row.action == "store_true":
            kwargs["action"] = "store_true"
        elif row.action == "append":
            kwargs["action"] = "append"
            kwargs["default"] = None
        elif row.action == "secret_guard_off":
            kwargs["action"] = _SecretGuardOff
            kwargs["nargs"] = 0
            kwargs["default"] = False
        elif row.choices:
            kwargs["choices"] = row.choices
            kwargs["default"] = None
        else:
            kwargs["default"] = None
        if row.dest == "from_bundle":
            kwargs["type"] = Path
        if row.metavar:
            kwargs["metavar"] = row.metavar
        parser.add_argument(*row.flags, **kwargs)
    if row.enable_flags and row.key != "mcp.publish":
        parser.add_argument(
            *row.enable_flags,
            dest=row.enable_dest,
            action="store_true",
            help=row.help,
        )
    elif row.enable_flags and row.key == "mcp.publish":
        parser.add_argument(
            *row.enable_flags,
            dest=row.enable_dest,
            action="store_true",
            help="Withdraw a previous --with-mcp opt-in.",
        )


def flag_strings(parser: argparse.ArgumentParser) -> set[str]:
    """Option strings registered on ``parser``, including compressed flags."""
    found: set[str] = set()
    for action in parser._actions:
        found.update(action.option_strings)
        group_actions = getattr(action, "_group_actions", None)
        if group_actions:
            for child in group_actions:
                found.update(child.option_strings)
    return found
