# Settings reference

Generated from the installer catalog and `runtime/env_registry.json`. Version 1.20261126.0.
Do not edit this page by hand. Run `python3 scripts/docs/gen_reference.py`.

## Opt-in and opt-out switches

Bool catalog rows and env rows marked opt-in or opt-out. `opt-out` means the default is on.

| Name | Opt | Default | Flag | Env | Effect | Source |
| --- | --- | --- | --- | --- | --- | --- |
| `network.offline` | opt-in | `false` | --offline | `CHAOS_ENGINE_OFFLINE` | Use only the cache or --from-bundle. Also CHAOS_ENGINE_OFFLINE. | [owner](../../runtime/install_options.py#L158) |
| `network.use_gh_token` | opt-out | `true` |  | `CHAOS_ENGINE_GH_AUTH` | Read gh auth token for downloads. CHAOS_ENGINE_GH_AUTH=0 turns it off. | [owner](../../runtime/install_options.py#L195) |
| `hosts.infer` | opt-out | `true` | --no-infer-hosts | `CHAOS_ENGINE_INFER_HOSTS` | Infer the host from the environment. --no-infer-hosts turns it off. | [owner](../../runtime/install_options.py#L287) |
| `hosts.grok.lean_skills` | opt-in | `false` | --lean-grok-skills | `CHAOS_ENGINE_LEAN_GROK_SKILLS` | Disable Grok bundled game-* and imagine skills. Also CHAOS_ENGINE_LEAN_GROK_SKILLS=1. | [owner](../../runtime/install_options.py#L312) |
| `hosts.register_plugins` | opt-out | `true` | --no-register-plugins | `CHAOS_ENGINE_REGISTER_PLUGINS` | Register Codex and Claude plugins. --no-register-plugins turns it off. | [owner](../../runtime/install_options.py#L325) |
| `components.memory` | opt-out | `true` | --without-memory, --with-memory |  | Set false to disable default-on memory. --without-memory / --with-memory. | [owner](../../runtime/install_options.py#L1) |
| `components.mempalace` | opt-out | `true` | --without-mempalace, --with-mempalace |  | Set false to disable default-on mempalace. --without-mempalace / --with-mempalace. | [owner](../../runtime/install_options.py#L1) |
| `components.graphify` | opt-out | `true` | --without-graphify, --with-graphify |  | Set false to disable default-on graphify. --without-graphify / --with-graphify. | [owner](../../runtime/install_options.py#L1) |
| `components.ponytail` | opt-out | `true` | --without-ponytail, --with-ponytail |  | Set false to disable default-on ponytail. --without-ponytail / --with-ponytail. | [owner](../../runtime/install_options.py#L1) |
| `components.caveman` | opt-out | `true` | --without-caveman, --with-caveman |  | Set false to disable default-on caveman. --without-caveman / --with-caveman. | [owner](../../runtime/install_options.py#L1) |
| `components.icm-architect` | opt-out | `true` | --without-icm-architect, --with-icm-architect |  | Set false to disable default-on icm-architect. --without-icm-architect / --with-icm-architect. | [owner](../../runtime/install_options.py#L1) |
| `addons.auto_detect` | opt-out | `true` | --no-auto-addons | `CHAOS_ENGINE_NO_AUTO_ADDONS` | Detect a project pack. --no-auto-addons turns it off. | [owner](../../runtime/install_options.py#L350) |
| `packs.post_install` | opt-out | `true` | --skip-pack-post-install | `CHAOS_ENGINE_PACK_POST_INSTALL` | Run the project pack postInstall. --skip-pack-post-install turns it off. | [owner](../../runtime/install_options.py#L374) |
| `mcp.publish` | opt-in | `false` | --with-mcp, --without-mcp | `CHAOS_ENGINE_WITH_MCP` | Publish CLI-equivalent MCP servers. Also CHAOS_ENGINE_WITH_MCP. | [owner](../../runtime/install_options.py#L387) |
| `mcp.maven_tools.enabled` | opt-in | `false` | --with-maven-tools | `CHAOS_ENGINE_WITH_MAVEN_TOOLS` | Install Maven Tools MCP. Also CHAOS_ENGINE_WITH_MAVEN_TOOLS. | [owner](../../runtime/install_options.py#L415) |
| `provision.tools` | opt-out | `true` | --skip-tools | `CHAOS_ENGINE_SKIP_TOOLS` | Provision uv, Python, Node, and the stores. --skip-tools turns it off. | [owner](../../runtime/install_options.py#L440) |
| `paths.modify_user_path` | opt-out | `true` | --no-modify-path | `CHAOS_ENGINE_MODIFY_PATH` | Change the user PATH on Windows. --no-modify-path turns it off. | [owner](../../runtime/install_options.py#L467) |
| `git_hooks.secret_guard` | opt-out | `true` | --no-secret-guard | `CHAOS_ENGINE_SECRET_GUARD` | Wire the secret guard into git hooks. --no-secret-guard turns it off. | [owner](../../runtime/install_options.py#L545) |
| `stores.schedule` | opt-out | `true` | --no-store-schedule | `CHAOS_ENGINE_STORE_SCHEDULE` | Install the daily store-refresh timer. --no-store-schedule turns it off. | [owner](../../runtime/install_options.py#L576) |
| `stores.refresh_on_session` | opt-out | `true` |  | `CHAOS_ENGINE_STORE_REFRESH` | Refresh a stale store when a session starts. CHAOS_ENGINE_STORE_REFRESH=0 turns it off. | [owner](../../runtime/install_options.py#L598) |
| `ui.interactive` | opt-in | `false` | --interactive |  | Ask before each install operation. | [owner](../../runtime/install_options.py#L660) |
| `ui.ascii` | opt-in | `false` | --ascii | `CHAOS_ENGINE_ASCII` | Force ASCII glyphs. Also CHAOS_ENGINE_ASCII=1. | [owner](../../runtime/install_options.py#L697) |
| `dry_run` | opt-in | `false` | -n, --dry-run |  | Print the plan and write nothing. | [owner](../../runtime/install_options.py#L709) |
| `yes` | opt-in | `false` | --yes, --no-input |  | Do not prompt. CI=1 and a non-interactive stdin imply this. | [owner](../../runtime/install_options.py#L710) |
| `json` | opt-in | `false` | --json |  | One JSON document on stdout. | [owner](../../runtime/install_options.py#L711) |
| `if_changed` | opt-in | `false` | --if-changed |  | No-op when the installed overlay already matches the source. | [owner](../../runtime/install_options.py#L712) |
| `force` | opt-in | `false` | --force |  | Replace edited CE-owned files without copying them. This is not --mode replace. | [owner](../../runtime/install_options.py#L713) |
| `include_local` | opt-in | `false` | --include-local |  | With --mode replace, also remove personal *.local files. | [owner](../../runtime/install_options.py#L714) |
| `allow_dirty` | opt-in | `false` | --allow-dirty |  | With --mode replace, allow uncommitted changes to instruction files. | [owner](../../runtime/install_options.py#L715) |
| `force_replace_source_tree` | opt-in | `false` | --force-replace-source-tree |  | Allow --mode replace in the ChaosEngine or SHAFT_ENGINE source tree. | [owner](../../runtime/install_options.py#L716) |
| `no_user_hooks` | opt-in | `false` | --no-user-hooks |  | Install user-level instructions and the skill, but no guard hooks. | [owner](../../runtime/install_options.py#L717) |
| `CE_ALLOW_BOX_LOCAL_AGENCY` | opt-in | `unset` |  | `CE_ALLOW_BOX_LOCAL_AGENCY` | Set to 1 to allow the local-agency box path. | [owner](../../skills/local-agency/scripts/require_rog_freetoken.py#L24) |
| `CHAOS_ENGINE_ALLOW_MISSING_EVAL` | opt-out | `unset` |  | `CHAOS_ENGINE_ALLOW_MISSING_EVAL` | Set to 1 to skip the eval-parity check. | [owner](../../runtime/silent_verify.py#L126) |
| `CHAOS_ENGINE_DRAFT_SKILL_PRS` | opt-in | `unset` |  | `CHAOS_ENGINE_DRAFT_SKILL_PRS` | Set to 1, with the CLI opt-in, to allow a draft skill pull request. | [owner](../../runtime/draft_skill_pr.py#L28) |
| `CHAOS_ENGINE_ENFORCE_RESEARCH_RECEIPT` | opt-in | `unset` |  | `CHAOS_ENGINE_ENFORCE_RESEARCH_RECEIPT` | Set to a truthy value to require a research receipt before mutation. | [owner](../../hooks/guard.py#L3873) |
| `CHAOS_ENGINE_REVIEW_CAP_LIFT` | opt-in | `unset` |  | `CHAOS_ENGINE_REVIEW_CAP_LIFT` | Owner lift of the two-review cap. | [owner](../../hooks/delegation_gate.py#L23) |
| `CHAOS_ENGINE_SIGNIFICANCE_CAPTURE` | opt-in | `unset` |  | `CHAOS_ENGINE_SIGNIFICANCE_CAPTURE` | Set to 1 to capture significance. | [owner](../../runtime/significance.py#L241) |
| `CHAOS_ENGINE_WITHOUT` | opt-out | `unset` |  | `CHAOS_ENGINE_WITHOUT` | Comma-separated component names to turn off. | [owner](../../runtime/install_config.py#L348) |
| `CHAOS_RADIO_SILENCE` | opt-in | `unset` |  | `CHAOS_RADIO_SILENCE` | Blocks owner-visible status when set to 1, true, or full. | [owner](../../runtime/radio_silence.py#L7) |

## Installer options

| Key | Type | Default | Allowed values | Levels | Flag | Env | Effect | Source |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| `source.repository` | str | `ShaftHQ/chaosengine-harness` |  | UP |  | CHAOS_ENGINE_REPOSITORY | GitHub repository owner/name. Also CHAOS_ENGINE_REPOSITORY. | [owner](../../runtime/install_options.py#L115) |
| `source.ref` | str | `main` |  | UP | --branch | CHAOS_ENGINE_BRANCH | Git ref to install. Also CHAOS_ENGINE_BRANCH. | [owner](../../runtime/install_options.py#L124) |
| `source.version` | str | `latest` |  | UP | --version | CHAOS_ENGINE_VERSION | Release 0.4.YYYYMMDD.N or a 40-hex commit. Also CHAOS_ENGINE_VERSION. | [owner](../../runtime/install_options.py#L135) |
| `source.channel` | choice | `main` | main, release | UP | --channel | CHAOS_ENGINE_CHANNEL | Update channel: main or release. | [owner](../../runtime/install_options.py#L146) |
| `network.offline` | bool | `false` |  | UL | --offline | CHAOS_ENGINE_OFFLINE | Use only the cache or --from-bundle. Also CHAOS_ENGINE_OFFLINE. | [owner](../../runtime/install_options.py#L158) |
| `network.bundle` | path | `` |  | UL | --from-bundle | CHAOS_ENGINE_FROM_BUNDLE | Offline bundle zip. Also CHAOS_ENGINE_FROM_BUNDLE. | [owner](../../runtime/install_options.py#L171) |
| `network.ca_bundle` | path | `` |  | UL | --ca-bundle | CHAOS_ENGINE_CA_BUNDLE | PEM bundle for TLS interception. Also CHAOS_ENGINE_CA_BUNDLE. Exported as SSL_CERT_FILE. | [owner](../../runtime/install_options.py#L183) |
| `network.use_gh_token` | bool | `true` |  | U |  | CHAOS_ENGINE_GH_AUTH | Read gh auth token for downloads. CHAOS_ENGINE_GH_AUTH=0 turns it off. | [owner](../../runtime/install_options.py#L195) |
| `install.scope` | choice | `project` | project, user, both | U | --scope | CHAOS_ENGINE_SCOPE | Where to install. project: this folder (default, shared through git). user: every folder on this machine, no repo files. both: project and user. | [owner](../../runtime/install_options.py#L204) |
| `install.distribution` | str | `portable` |  | P | --distribution | CHAOS_ENGINE_DISTRIBUTION | Distribution id. Also CHAOS_ENGINE_DISTRIBUTION. | [owner](../../runtime/install_options.py#L219) |
| `install.git_visibility` | choice | `tracked` | tracked, excluded | UL | --consumer, --tracked | CHAOS_ENGINE_CONSUMER | tracked, or excluded (consumer mode, CHAOS_ENGINE_CONSUMER=1). | [owner](../../runtime/install_options.py#L230) |
| `instructions.mode` | choice | `merge` | merge, replace | UPL | --mode | CHAOS_ENGINE_MODE | How to treat existing agent instructions. merge (default): keep them and make ChaosEngine the primary driver. replace: back up, then delete them and install ChaosEngine's set (needs --yes when not interactive). | [owner](../../runtime/install_options.py#L246) |
| `instructions.placement` | choice | `top` | top, bottom | P | --instructions-placement | CHAOS_ENGINE_INSTRUCTIONS_PLACEMENT | Where the instruction block sits. Also CHAOS_ENGINE_INSTRUCTIONS_PLACEMENT. | [owner](../../runtime/install_options.py#L262) |
| `hosts.enabled` | list | `[]` | claude, codex, grok, gemini, copilot, opencode, cursor, antigravity, grok-bot | UPL | --hosts | CHAOS_ENGINE_HOST | Client ids to complete (comma-separated). Empty infers. Also CHAOS_ENGINE_HOST. | [owner](../../runtime/install_options.py#L274) |
| `hosts.infer` | bool | `true` |  | UP | --no-infer-hosts | CHAOS_ENGINE_INFER_HOSTS | Infer the host from the environment. --no-infer-hosts turns it off. | [owner](../../runtime/install_options.py#L287) |
| `hosts.portable_files` | choice | `all` | all, enabled | P | --portable-hosts | CHAOS_ENGINE_PORTABLE_HOSTS | Write portable files for all hosts, or only enabled ones. | [owner](../../runtime/install_options.py#L300) |
| `hosts.grok.lean_skills` | bool | `false` |  | U | --lean-grok-skills | CHAOS_ENGINE_LEAN_GROK_SKILLS | Disable Grok bundled game-* and imagine skills. Also CHAOS_ENGINE_LEAN_GROK_SKILLS=1. | [owner](../../runtime/install_options.py#L312) |
| `hosts.register_plugins` | bool | `true` |  | UL | --no-register-plugins | CHAOS_ENGINE_REGISTER_PLUGINS | Register Codex and Claude plugins. --no-register-plugins turns it off. | [owner](../../runtime/install_options.py#L325) |
| `components.memory` | bool | `true` |  | UPL | --without-memory, --with-memory |  | Set false to disable default-on memory. --without-memory / --with-memory. | [owner](../../runtime/install_options.py#L1) |
| `components.mempalace` | bool | `true` |  | UPL | --without-mempalace, --with-mempalace |  | Set false to disable default-on mempalace. --without-mempalace / --with-mempalace. | [owner](../../runtime/install_options.py#L1) |
| `components.graphify` | bool | `true` |  | UPL | --without-graphify, --with-graphify |  | Set false to disable default-on graphify. --without-graphify / --with-graphify. | [owner](../../runtime/install_options.py#L1) |
| `components.ponytail` | bool | `true` |  | UPL | --without-ponytail, --with-ponytail |  | Set false to disable default-on ponytail. --without-ponytail / --with-ponytail. | [owner](../../runtime/install_options.py#L1) |
| `components.caveman` | bool | `true` |  | UPL | --without-caveman, --with-caveman |  | Set false to disable default-on caveman. --without-caveman / --with-caveman. | [owner](../../runtime/install_options.py#L1) |
| `components.icm-architect` | bool | `true` |  | UPL | --without-icm-architect, --with-icm-architect |  | Set false to disable default-on icm-architect. --without-icm-architect / --with-icm-architect. | [owner](../../runtime/install_options.py#L1) |
| `addons.enabled` | list | `[]` | design-skills, shaft-engine-users, shaft-core-developers | UPL |  | CHAOS_ENGINE_ADDONS | Optional add-on ids. Lists merge across levels. Also CHAOS_ENGINE_ADDONS. | [owner](../../runtime/install_options.py#L339) |
| `addons.auto_detect` | bool | `true` |  | P | --no-auto-addons | CHAOS_ENGINE_NO_AUTO_ADDONS | Detect a project pack. --no-auto-addons turns it off. | [owner](../../runtime/install_options.py#L350) |
| `packs.shaft_skills_version` | str | `auto` |  | P | --shaft-skills-version | CHAOS_ENGINE_SHAFT_SKILLS_VERSION | SHAFT skills tag. Also CHAOS_ENGINE_SHAFT_SKILLS_VERSION. | [owner](../../runtime/install_options.py#L363) |
| `packs.post_install` | bool | `true` |  | PL | --skip-pack-post-install | CHAOS_ENGINE_PACK_POST_INSTALL | Run the project pack postInstall. --skip-pack-post-install turns it off. | [owner](../../runtime/install_options.py#L374) |
| `mcp.publish` | bool | `false` |  | UPL | --with-mcp, --without-mcp | CHAOS_ENGINE_WITH_MCP | Publish CLI-equivalent MCP servers. Also CHAOS_ENGINE_WITH_MCP. | [owner](../../runtime/install_options.py#L387) |
| `mcp.servers` | list | `[]` | chaosengine-memory, chaosengine-mempalace, context7, chrome-devtools-mcp | UPL | --mcp-servers | CHAOS_ENGINE_MCP_SERVERS | MCP server ids when publish is on. Also CHAOS_ENGINE_MCP_SERVERS. | [owner](../../runtime/install_options.py#L402) |
| `mcp.maven_tools.enabled` | bool | `false` |  | PL | --with-maven-tools | CHAOS_ENGINE_WITH_MAVEN_TOOLS | Install Maven Tools MCP. Also CHAOS_ENGINE_WITH_MAVEN_TOOLS. | [owner](../../runtime/install_options.py#L415) |
| `mcp.maven_tools.mode` | choice | `native` | native, docker | UL | --maven-tools-mode | CHAOS_ENGINE_MAVEN_TOOLS_MODE | Maven Tools runtime. Also CHAOS_ENGINE_MAVEN_TOOLS_MODE. | [owner](../../runtime/install_options.py#L428) |
| `provision.tools` | bool | `true` |  | UL | --skip-tools | CHAOS_ENGINE_SKIP_TOOLS | Provision uv, Python, Node, and the stores. --skip-tools turns it off. | [owner](../../runtime/install_options.py#L440) |
| `provision.prerequisites` | choice | `auto` | auto, report, skip, provision | UL | --skip-prerequisites | CHAOS_ENGINE_PREREQUISITES | Prerequisites: auto, report, skip, or provision. --skip-prerequisites selects skip. | [owner](../../runtime/install_options.py#L453) |
| `paths.modify_user_path` | bool | `true` |  | U | --no-modify-path | CHAOS_ENGINE_MODIFY_PATH | Change the user PATH on Windows. --no-modify-path turns it off. | [owner](../../runtime/install_options.py#L467) |
| `paths.bin_dir` | path | `` |  | U | --bin-dir | CHAOS_ENGINE_SHIM_DIR | Shim directory. Also CHAOS_ENGINE_SHIM_DIR. Empty uses the platform default. | [owner](../../runtime/install_options.py#L480) |
| `paths.cache_dir` | path | `` |  | U |  | CHAOS_ENGINE_CACHE_DIR | Download cache directory. Also CHAOS_ENGINE_CACHE_DIR. | [owner](../../runtime/install_options.py#L492) |
| `paths.data_dir` | path | `` |  | U |  | CHAOS_ENGINE_USER_DIR | User data directory. Also CHAOS_ENGINE_USER_DIR. | [owner](../../runtime/install_options.py#L501) |
| `cache.max_mb` | int | `0` |  | U |  | CHAOS_ENGINE_CACHE_MAX_MB | Download cache cap in MiB. 0 is unlimited. Eviction is not active. | [owner](../../runtime/install_options.py#L510) |
| `edits.policy` | choice | `copy-aside` | copy-aside, refuse | UPL | --keep-edits | CHAOS_ENGINE_KEEP_EDITS | copy-aside keeps edited owned files. refuse exits before replacing them (--keep-edits). | [owner](../../runtime/install_options.py#L519) |
| `backups.keep` | int | `20` |  | UP | --backup-keep | CHAOS_ENGINE_BACKUP_KEEP | How many backup stamps to keep. 0 is unlimited. | [owner](../../runtime/install_options.py#L533) |
| `git_hooks.secret_guard` | bool | `true` |  | UPL | --no-secret-guard | CHAOS_ENGINE_SECRET_GUARD | Wire the secret guard into git hooks. --no-secret-guard turns it off. | [owner](../../runtime/install_options.py#L545) |
| `locks.project_wait_seconds` | int | `30` |  | U |  | CHAOS_ENGINE_LOCK_WAIT_SECONDS | Seconds to wait for the project lock (1-600). Also CHAOS_ENGINE_LOCK_WAIT_SECONDS. | [owner](../../runtime/install_options.py#L558) |
| `hooks.guard_wait_ms` | int | `60000` |  | UP |  | CHAOS_ENGINE_GUARD_WAIT_MS | Guard wait in milliseconds (0-600000). Also CHAOS_ENGINE_GUARD_WAIT_MS. | [owner](../../runtime/install_options.py#L567) |
| `stores.schedule` | bool | `true` |  | U | --no-store-schedule | CHAOS_ENGINE_STORE_SCHEDULE | Install the daily store-refresh timer. --no-store-schedule turns it off. | [owner](../../runtime/install_options.py#L576) |
| `stores.schedule_at` | str | `03:15` |  | U |  | CHAOS_ENGINE_STORE_SCHEDULE_AT | Daily refresh clock time HH:MM. Also CHAOS_ENGINE_STORE_SCHEDULE_AT. | [owner](../../runtime/install_options.py#L589) |
| `stores.refresh_on_session` | bool | `true` |  | UL |  | CHAOS_ENGINE_STORE_REFRESH | Refresh a stale store when a session starts. CHAOS_ENGINE_STORE_REFRESH=0 turns it off. | [owner](../../runtime/install_options.py#L598) |
| `stores.stall_seconds` | int | `120` |  | U |  | CHAOS_ENGINE_STALL_SECONDS | Store-stall timeout in seconds. Also CHAOS_ENGINE_STALL_SECONDS. | [owner](../../runtime/install_options.py#L607) |
| `stores.graphify.extra_ignore` | list | `[]` |  | P |  |  | Extra Graphify ignore patterns. Merged with the harness ignores; it cannot remove them. | [owner](../../runtime/install_options.py#L616) |
| `stores.mempalace.mine` | str | `` |  | UP |  | CHAOS_ENGINE_MEMPALACE_MINE | MemPalace mine mode. Also CHAOS_ENGINE_MEMPALACE_MINE. | [owner](../../runtime/install_options.py#L624) |
| `stores.mempalace.full` | str | `` |  | UP |  | CHAOS_ENGINE_MEMPALACE_FULL | MemPalace full mine. Also CHAOS_ENGINE_MEMPALACE_FULL. | [owner](../../runtime/install_options.py#L633) |
| `stores.mempalace.collection` | str | `` |  | UP |  | CHAOS_ENGINE_MEMPALACE_COLLECTION | MemPalace collection. Also CHAOS_ENGINE_MEMPALACE_COLLECTION. | [owner](../../runtime/install_options.py#L642) |
| `session.resume_stale_days` | int | `7` |  | U |  | CHAOS_ENGINE_RESUME_STALE_DAYS | Days before a session resume is stale. Also CHAOS_ENGINE_RESUME_STALE_DAYS. | [owner](../../runtime/install_options.py#L651) |
| `ui.interactive` | bool | `false` |  | U | --interactive |  | Ask before each install operation. | [owner](../../runtime/install_options.py#L660) |
| `ui.verbosity` | choice | `normal` | quiet, normal, verbose | U | -q, --quiet, --verbose |  | quiet, normal, or verbose. | [owner](../../runtime/install_options.py#L671) |
| `ui.color` | choice | `auto` | auto, always, never | U | --color | CHAOS_ENGINE_COLOR | Colour mode. NO_COLOR and --no-color win over always. Also CHAOS_ENGINE_COLOR. | [owner](../../runtime/install_options.py#L685) |
| `ui.ascii` | bool | `false` |  | U | --ascii | CHAOS_ENGINE_ASCII | Force ASCII glyphs. Also CHAOS_ENGINE_ASCII=1. | [owner](../../runtime/install_options.py#L697) |
| `dry_run` | bool | `false` |  |  | -n, --dry-run |  | Print the plan and write nothing. | [owner](../../runtime/install_options.py#L709) |
| `yes` | bool | `false` |  |  | --yes, --no-input |  | Do not prompt. CI=1 and a non-interactive stdin imply this. | [owner](../../runtime/install_options.py#L710) |
| `json` | bool | `false` |  |  | --json |  | One JSON document on stdout. | [owner](../../runtime/install_options.py#L711) |
| `if_changed` | bool | `false` |  |  | --if-changed |  | No-op when the installed overlay already matches the source. | [owner](../../runtime/install_options.py#L712) |
| `force` | bool | `false` |  |  | --force |  | Replace edited CE-owned files without copying them. This is not --mode replace. | [owner](../../runtime/install_options.py#L713) |
| `include_local` | bool | `false` |  |  | --include-local |  | With --mode replace, also remove personal *.local files. | [owner](../../runtime/install_options.py#L714) |
| `allow_dirty` | bool | `false` |  |  | --allow-dirty |  | With --mode replace, allow uncommitted changes to instruction files. | [owner](../../runtime/install_options.py#L715) |
| `force_replace_source_tree` | bool | `false` |  |  | --force-replace-source-tree |  | Allow --mode replace in the ChaosEngine or SHAFT_ENGINE source tree. | [owner](../../runtime/install_options.py#L716) |
| `no_user_hooks` | bool | `false` |  |  | --no-user-hooks |  | Install user-level instructions and the skill, but no guard hooks. | [owner](../../runtime/install_options.py#L717) |
| `user_layer.hosts` | list | `[]` | claude, codex, grok, gemini, copilot, opencode, cursor, antigravity, grok-bot | U | --user-hosts | CHAOS_ENGINE_USER_HOSTS | Hosts to wire at user level. Also CHAOS_ENGINE_USER_HOSTS. | [owner](../../runtime/install_options.py#L718) |

## Dynamic add-on flags

These `--with-<addon>` and `--without-<addon>` flags are parsed from unknown arguments. They are not all on `install.py install --help`.

- `--with-design-skills` / `--without-design-skills`
- `--with-shaft-engine-users` / `--without-shaft-engine-users`
- `--with-shaft-core-developers` / `--without-shaft-core-developers`

## Environment-only variables

Names read by code and not declared as a catalog env. Class `user`, then `maint`.

| Name | Class | Type | Default | Values | Opt | Effect | Source |
| --- | --- | --- | --- | --- | --- | --- | --- |
| `CE_ALLOW_BOX_LOCAL_AGENCY` | user | str | `unset` |  | opt-in | Set to 1 to allow the local-agency box path. | [owner](../../skills/local-agency/scripts/require_rog_freetoken.py#L24) |
| `CE_HOOK_TRACE` | user | str | `unset` |  | value | unknown — see read site | [owner](../../hooks/launch.py#L396) |
| `CE_OPENCODE_GUARD_TIMEOUT_MS` | user | str | `unset` |  | value | unknown — see read site | [owner](../../runtime/hook_surfaces.py#L210) |
| `CE_OPENCODE_PYTHON` | user | str | `unset` |  | value | unknown — see read site | [owner](../../runtime/hook_surfaces.py#L216) |
| `CE_OWNER_EMAIL` | user | str | `unset` |  | value | unknown — see read site | [owner](../../runtime/commit_identity.py#L188) |
| `CE_OWNER_IDENTITY` | user | str | `unset` |  | value | unknown — see read site | [owner](../../runtime/commit_identity.py#L184) |
| `CE_OWNER_NAME` | user | str | `unset` |  | value | unknown — see read site | [owner](../../runtime/commit_identity.py#L187) |
| `CHAOS_ENGINE_ADDON_PATHS` | user | str | `unset` |  | value | unknown — see read site | [owner](../../runtime/addon_catalog.py#L34) |
| `CHAOS_ENGINE_ALLOW_LINKED_WORKTREE` | user | str | `unset` |  | value | unknown — see read site | [owner](../../install.py#L8905) |
| `CHAOS_ENGINE_ALLOW_MISSING_EVAL` | user | str | `unset` |  | opt-out | Set to 1 to skip the eval-parity check. | [owner](../../runtime/silent_verify.py#L126) |
| `CHAOS_ENGINE_APPLY_UPDATE` | user | str | `unset` |  | value | unknown — see read site | [owner](../../hooks/lifecycle.py#L471) |
| `CHAOS_ENGINE_CLIENT_NAME_DENYLIST` | user | str | `unset` |  | value | unknown — see read site | [owner](../../bootstrap.py#L1058) |
| `CHAOS_ENGINE_DEBUG` | user | str | `unset` |  | value | unknown — see read site | [owner](../../bootstrap.py#L7669) |
| `CHAOS_ENGINE_DRAFT_SKILL_PRS` | user | str | `unset` |  | opt-in | Set to 1, with the CLI opt-in, to allow a draft skill pull request. | [owner](../../runtime/draft_skill_pr.py#L28) |
| `CHAOS_ENGINE_ENFORCE_RESEARCH_RECEIPT` | user | str | `unset` |  | opt-in | Set to a truthy value to require a research receipt before mutation. | [owner](../../hooks/guard.py#L3873) |
| `CHAOS_ENGINE_FILE_ISSUE` | user | str | `unset` |  | value | unknown — see read site | [owner](../../bootstrap.py#L1174) |
| `CHAOS_ENGINE_HYPERLINKS` | user | str | `unset` |  | value | unknown — see read site | [owner](../../bootstrap.py#L845) |
| `CHAOS_ENGINE_JSON` | user | str | `unset` |  | value | unknown — see read site | [owner](../../bootstrap.py#L790) |
| `CHAOS_ENGINE_NO_INPUT` | user | str | `unset` |  | value | unknown — see read site | [owner](../../bootstrap.py#L3535) |
| `CHAOS_ENGINE_OWNER_FINISH_GOAL` | user | str | `unset` |  | value | unknown — see read site | [owner](../../runtime/task_ledger.py#L101) |
| `CHAOS_ENGINE_QUIET` | user | str | `unset` |  | value | unknown — see read site | [owner](../../bootstrap.py#L172) |
| `CHAOS_ENGINE_RELEASE_FEED` | user | str | `unset` |  | value | unknown — see read site | [owner](../../hooks/lifecycle.py#L434) |
| `CHAOS_ENGINE_RELEASE_VERSION` | user | str | `unset` |  | value | unknown — see read site | [owner](../../hooks/lifecycle.py#L435) |
| `CHAOS_ENGINE_REVIEW_CAP_LIFT` | user | str | `unset` |  | opt-in | Owner lift of the two-review cap. | [owner](../../hooks/delegation_gate.py#L23) |
| `CHAOS_ENGINE_SIGNIFICANCE_CAPTURE` | user | str | `unset` |  | opt-in | Set to 1 to capture significance. | [owner](../../runtime/significance.py#L241) |
| `CHAOS_ENGINE_TOKEN_BUDGET` | user | choice | `balanced` | ultra-lean, lean, balanced, deep | value | Selects ultra-lean (alias lean), balanced (default), or deep. | [owner](../../hooks/lifecycle.py#L69) |
| `CHAOS_ENGINE_UPSTREAM_REPO` | user | str | `unset` |  | value | unknown — see read site | [owner](../../hooks/session_scratch.py#L254) |
| `CHAOS_ENGINE_VERBOSE` | user | str | `unset` |  | value | unknown — see read site | [owner](../../bootstrap.py#L218) |
| `CHAOS_ENGINE_WITHOUT` | user | str | `unset` | comma-separated component ids | opt-out | Comma-separated component names to turn off. | [owner](../../runtime/install_config.py#L348) |
| `CHAOS_RADIO_SILENCE` | user | str | `unset` | 1, true, full | opt-in | Blocks owner-visible status when set to 1, true, or full. | [owner](../../runtime/radio_silence.py#L7) |
| `CE_NEUTRAL_TERMS_FILE` | maint | str | `unset` |  | value | unknown — see read site | [owner](../../skills/job-apply/scripts/check_abstraction.py#L35) |
| `CE_ROG_CHECKOUT` | maint | str | `unset` |  | value | unknown — see read site | [owner](../../skills/local-agency/scripts/require_rog_freetoken.py#L23) |
| `CHAOS_BACKUPS_WATCH_PATH` | maint | str | `unset` |  | value | unknown — see read site | [owner](../../runtime/backups_watch.py#L242) |
| `CHAOS_BACKUP_WORKSPACES` | maint | str | `unset` |  | value | unknown — see read site | [owner](../../runtime/delete_guard.py#L5556) |
| `CHAOS_CHECKPOINTS_DIR` | maint | str | `unset` |  | value | unknown — see read site | [owner](../../runtime/progress_log.py#L25) |
| `CHAOS_DELETE_ACK` | maint | str | `unset` |  | value | unknown — see read site | [owner](../../runtime/delete_guard.py#L94) |
| `CHAOS_ENGINE_CONSENT_PATH` | maint | str | `unset` |  | value | unknown — see read site | [owner](../../runtime/learning_session.py#L237) |
| `CHAOS_ENGINE_DRY_RUN` | maint | str | `unset` |  | value | unknown — see read site | [owner](../../bootstrap.py#L5405) |
| `CHAOS_ENGINE_EVIDENCE_BRANCH` | maint | str | `unset` |  | value | unknown — see read site | [owner](../../runtime/mobile_retro.py#L65) |
| `CHAOS_ENGINE_EVIDENCE_BUILD_ID` | maint | str | `unset` |  | value | unknown — see read site | [owner](../../runtime/mobile_retro.py#L59) |
| `CHAOS_ENGINE_FORCE` | maint | str | `unset` |  | value | unknown — see read site | [owner](../../bootstrap.py#L5404) |
| `CHAOS_ENGINE_GRAPHIFY_OUT` | maint | str | `unset` |  | value | unknown — see read site | [owner](../../hooks/retrieve_justification.py#L229) |
| `CHAOS_ENGINE_INSTALL_URL` | maint | str | `unset` |  | value | unknown — see read site | [owner](../../install.sh#L105) |
| `CHAOS_ENGINE_JOBS_DIR` | maint | str | `unset` |  | value | unknown — see read site | [owner](../../runtime/jobs.py#L45) |
| `CHAOS_ENGINE_LOCAL_CLONE` | maint | str | `unset` |  | value | unknown — see read site | [owner](../../bootstrap.py#L169) |
| `CHAOS_ENGINE_MEMPALACE` | maint | str | `unset` |  | value | unknown — see read site | [owner](../../runtime/hosts.py#L1043) |
| `CHAOS_ENGINE_PREREQ_DISK_PATH` | maint | str | `unset` |  | value | unknown — see read site | [owner](../../runtime/task_ledger.py#L692) |
| `CHAOS_ENGINE_PRIMARY` | maint | str | `unset` |  | value | unknown — see read site | [owner](../../runtime/delete_guard.py#L4617) |
| `CHAOS_ENGINE_SHAFT_FIXTURE_ORIGIN` | maint | str | `unset` |  | value | unknown — see read site | [owner](../../packs/shaft/sync.py#L55) |
| `CHAOS_ENGINE_SHIM_INTERPRETER` | maint | str | `unset` |  | value | unknown — see read site | [owner](../../install.ps1#L508) |
| `CHAOS_ENGINE_SPEC_DIR` | maint | str | `unset` |  | value | unknown — see read site | [owner](../../runtime/task_ledger.py#L847) |
| `CHAOS_ENGINE_STORE_REGISTRY` | maint | str | `unset` |  | value | unknown — see read site | [owner](../../runtime/stores.py#L238) |
| `CHAOS_ENGINE_TASKS_DIR` | maint | str | `unset` |  | value | unknown — see read site | [owner](../../runtime/task_ledger.py#L116) |
| `CHAOS_PROGRESS_LOG` | maint | str | `unset` |  | value | unknown — see read site | [owner](../../runtime/progress_log.py#L8) |
| `CHAOS_YT_EXPECTED_AUTHORS` | maint | str | `unset` |  | value | unknown — see read site | [owner](../../runtime/delete_guard.py#L121) |
| `CHAOS_YT_VERIFIED_DELETE` | maint | str | `unset` |  | value | unknown — see read site | [owner](../../runtime/delete_guard.py#L114) |

## Internal variables

The harness sets these itself. They are not owner switches.

| Name | Effect | Why internal | Source |
| --- | --- | --- | --- |
| `CHAOS_AGENT_ID` | unknown — see read site | Set by the harness, not an owner switch. | [owner](../../runtime/backups_watch.py#L33) |
| `CHAOS_ENGINE_ARGV_ONLY` | unknown — see read site | Set by the harness, not an owner switch. | [owner](../../bootstrap.py#L8060) |
| `CHAOS_ENGINE_BOOT_TIME` | unknown — see read site | Set by the harness, not an owner switch. | [owner](../../runtime/task_ledger.py#L109) |
| `CHAOS_ENGINE_BRAND_SHOWN` | unknown — see read site | Set by the harness, not an owner switch. | [owner](../../bootstrap.py#L2692) |
| `CHAOS_ENGINE_CONFIG_HOME` | unknown — see read site | Set by the harness, not an owner switch. | [owner](../../runtime/install_config.py#L95) |
| `CHAOS_ENGINE_COPY_PROMPT` | unknown — see read site | Set by the harness, not an owner switch. | [owner](../../bootstrap.py#L7520) |
| `CHAOS_ENGINE_DERIVED_VERSION` | unknown — see read site | Set by the harness, not an owner switch. | [owner](../../bootstrap.py#L1672) |
| `CHAOS_ENGINE_FIXTURE_ORIGIN` | unknown — see read site | Set by the harness, not an owner switch. | [owner](../../bootstrap.py#L5134) |
| `CHAOS_ENGINE_HOOK_EVENT` | unknown — see read site | Set by the harness, not an owner switch. | [owner](../../hooks/launch.py#L66) |
| `CHAOS_ENGINE_HOOK_PAYLOAD` | unknown — see read site | Set by the harness, not an owner switch. | [owner](../../hooks/launch.py#L23) |
| `CHAOS_ENGINE_HOOK_SOURCE` | unknown — see read site | Set by the harness, not an owner switch. | [owner](../../runtime/hosts.py#L5526) |
| `CHAOS_ENGINE_JOB` | unknown — see read site | Set by the harness, not an owner switch. | [owner](../../runtime/jobs.py#L44) |
| `CHAOS_ENGINE_JOB_RUN` | unknown — see read site | Set by the harness, not an owner switch. | [owner](../../runtime/jobs.py#L43) |
| `CHAOS_ENGINE_PROTECTED_GROK_HOME` | unknown — see read site | Set by the harness, not an owner switch. | [owner](../../runtime/grok_lean_config.py#L459) |
| `CHAOS_ENGINE_PROTECTED_GROK_HOME_LOG` | unknown — see read site | Set by the harness, not an owner switch. | [owner](../../runtime/grok_lean_config.py#L472) |
| `CHAOS_ENGINE_PYTHON_PROBE_ONLY` | unknown — see read site | Set by the harness, not an owner switch. | [owner](../../install.sh#L387) |
| `CHAOS_ENGINE_RESOLVE_ONLY` | unknown — see read site | Set by the harness, not an owner switch. | [owner](../../install.ps1#L540) |
| `CHAOS_ENGINE_RETRIEVE` | unknown — see read site | Set by the harness, not an owner switch. | [owner](../../tool.py#L868) |
| `CHAOS_ENGINE_RUN_RECEIPT` | unknown — see read site | Set by the harness, not an owner switch. | [owner](../../runtime/session_token_usage.py#L260) |
| `CHAOS_ENGINE_SESSION_ID` | unknown — see read site | Set by the harness, not an owner switch. | [owner](../../hooks/retrieve_justification.py#L483) |
| `CHAOS_ENGINE_SESSION_WORKTREE` | unknown — see read site | Set by the harness, not an owner switch. | [owner](../../runtime/session_logs.py#L19) |
| `CHAOS_ENGINE_STATE_DIR` | unknown — see read site | Set by the harness, not an owner switch. | [owner](../../runtime/user_paths.py#L69) |
| `CHAOS_ENGINE_TEST_REPO_GUARD` | unknown — see read site | Set by the harness, not an owner switch. | [owner](../../runtime/stores.py#L2118) |
| `CHAOS_ENGINE_USER_HOME` | unknown — see read site | Set by the harness, not an owner switch. | [owner](../../runtime/user_paths.py#L29) |
| `CHAOS_ENGINE_USER_PATHS` | unknown — see read site | Set by the harness, not an owner switch. | [owner](../../packs/java/installer.py#L453) |
| `CHAOS_ENGINE_USER_PAYLOAD` | unknown — see read site | Set by the harness, not an owner switch. | [owner](../../hooks/launch.py#L527) |
| `CHAOS_SESSION_CONTAINMENT_ROOTS` | unknown — see read site | Set by the harness, not an owner switch. | [owner](../../runtime/delete_guard.py#L66) |
| `CHAOS_SESSION_CREATED_MANIFEST` | unknown — see read site | Set by the harness, not an owner switch. | [owner](../../runtime/delete_guard.py#L63) |
| `CHAOS_SESSION_MANIFEST_HMAC` | unknown — see read site | Set by the harness, not an owner switch. | [owner](../../runtime/delete_guard.py#L65) |
| `CHAOS_SESSION_WORKTREE` | unknown — see read site | Set by the harness, not an owner switch. | [owner](../../hooks/retrieve_justification.py#L1701) |
