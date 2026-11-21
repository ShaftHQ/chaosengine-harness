# Configuration

ChaosEngine sends no usage data.

Installer options live in TOML files with `schema = 1`. A missing file changes nothing. Precedence is the flag, then the environment, then `.chaos-engine.local.toml`, then `.chaos-engine.toml`, then the user config file, then the built-in default. Lists replace the lower level except `addons.enabled` and `stores.graphify.extra_ignore`, which union. `instructions.mode = "replace"` is refused from every file (`CE_CONFIG_REPLACE_FROM_FILE`). A key whose name looks like a token, secret, password, or key is refused (`CE_CONFIG_SECRET`), except the catalog keys `network.use_gh_token` and `network.ca_bundle`.

Paths:

| Level | Linux | macOS | Windows |
| --- | --- | --- | --- |
| User | `$XDG_CONFIG_HOME/chaos-engine/config.toml` or `~/.config/chaos-engine/config.toml` | `~/.config/chaos-engine/config.toml` | `%APPDATA%\chaos-engine\config.toml` |
| Project | `.chaos-engine.toml` | `.chaos-engine.toml` | `.chaos-engine.toml` |
| Project-local | `.chaos-engine.local.toml` | `.chaos-engine.local.toml` | `.chaos-engine.local.toml` |

`--config FILE` replaces the user file for that run. `install.py config show --json` names the source of every key. `config validate` exits 1 with `CE_CONFIG_INVALID` on a bad file. `config set` keeps comments, CRLF, and a leading UTF-8 BOM.

CLI-only keys are ignored with a warning when they appear in a file: `dry_run`, `yes`, `json`, `if_changed`, `force`, `include_local`, `allow_dirty`, `force_replace_source_tree`, and `no_user_hooks`. A file level applies a key only when the catalog allows that level. `install.scope` is user-only, so a project file cannot opt a checkout into a home install. Flags and environment variables still apply.

| Key | Default | Flag | Environment |
| --- | --- | --- | --- |
| `source.repository` | `ShaftHQ/chaosengine-harness` | `` | `CHAOS_ENGINE_REPOSITORY` |
| `source.ref` | `main` | `--branch` | `CHAOS_ENGINE_BRANCH` |
| `source.version` | `latest` | `--version` | `CHAOS_ENGINE_VERSION` |
| `source.channel` | `main` | `--channel` | `CHAOS_ENGINE_CHANNEL` |
| `network.offline` | `false` | `--offline` | `CHAOS_ENGINE_OFFLINE` |
| `network.bundle` | `` | `--from-bundle` | `CHAOS_ENGINE_FROM_BUNDLE` |
| `network.ca_bundle` | `` | `--ca-bundle` | `CHAOS_ENGINE_CA_BUNDLE` |
| `network.use_gh_token` | `true` | `` | `CHAOS_ENGINE_GH_AUTH` |
| `install.scope` | `project` | `--scope` | `CHAOS_ENGINE_SCOPE` |
| `install.distribution` | `portable` | `--distribution` | `CHAOS_ENGINE_DISTRIBUTION` |
| `install.git_visibility` | `tracked` | `--consumer` | `CHAOS_ENGINE_CONSUMER` |
| `instructions.mode` | `merge` | `--mode` | `CHAOS_ENGINE_MODE` |
| `instructions.placement` | `top` | `--instructions-placement` | `CHAOS_ENGINE_INSTRUCTIONS_PLACEMENT` |
| `hosts.enabled` | `[]` | `--hosts` | `CHAOS_ENGINE_HOST` |
| `hosts.infer` | `true` | `--no-infer-hosts` | `CHAOS_ENGINE_INFER_HOSTS` |
| `hosts.portable_files` | `all` | `--portable-hosts` | `CHAOS_ENGINE_PORTABLE_HOSTS` |
| `hosts.grok.lean_skills` | `false` | `--lean-grok-skills` | `CHAOS_ENGINE_LEAN_GROK_SKILLS` |
| `hosts.register_plugins` | `true` | `--no-register-plugins` | `CHAOS_ENGINE_REGISTER_PLUGINS` |
| `components.memory` | `true` | `--without-memory` | `` |
| `components.mempalace` | `true` | `--without-mempalace` | `` |
| `components.graphify` | `true` | `--without-graphify` | `` |
| `components.ponytail` | `true` | `--without-ponytail` | `` |
| `components.caveman` | `true` | `--without-caveman` | `` |
| `components.icm-architect` | `true` | `--without-icm-architect` | `` |
| `addons.enabled` | `[]` | `` | `CHAOS_ENGINE_ADDONS` |
| `addons.auto_detect` | `true` | `--no-auto-addons` | `CHAOS_ENGINE_NO_AUTO_ADDONS` |
| `packs.shaft_skills_version` | `auto` | `--shaft-skills-version` | `CHAOS_ENGINE_SHAFT_SKILLS_VERSION` |
| `packs.post_install` | `true` | `--skip-pack-post-install` | `CHAOS_ENGINE_PACK_POST_INSTALL` |
| `mcp.publish` | `false` | `--with-mcp` | `CHAOS_ENGINE_WITH_MCP` |
| `mcp.servers` | `[]` | `--mcp-servers` | `CHAOS_ENGINE_MCP_SERVERS` |
| `mcp.maven_tools.enabled` | `false` | `--with-maven-tools` | `CHAOS_ENGINE_WITH_MAVEN_TOOLS` |
| `mcp.maven_tools.mode` | `native` | `--maven-tools-mode` | `CHAOS_ENGINE_MAVEN_TOOLS_MODE` |
| `provision.tools` | `true` | `--skip-tools` | `CHAOS_ENGINE_SKIP_TOOLS` |
| `provision.prerequisites` | `auto` | `--skip-prerequisites` | `CHAOS_ENGINE_PREREQUISITES` |
| `paths.modify_user_path` | `true` | `--no-modify-path` | `CHAOS_ENGINE_MODIFY_PATH` |
| `paths.bin_dir` | `` | `--bin-dir` | `CHAOS_ENGINE_SHIM_DIR` |
| `paths.cache_dir` | `` | `` | `CHAOS_ENGINE_CACHE_DIR` |
| `paths.data_dir` | `` | `` | `CHAOS_ENGINE_USER_DIR` |
| `cache.max_mb` | `0` | `` | `CHAOS_ENGINE_CACHE_MAX_MB` |
| `edits.policy` | `copy-aside` | `--keep-edits` | `CHAOS_ENGINE_KEEP_EDITS` |
| `backups.keep` | `20` | `--backup-keep` | `CHAOS_ENGINE_BACKUP_KEEP` |
| `git_hooks.secret_guard` | `true` | `--no-secret-guard` | `CHAOS_ENGINE_SECRET_GUARD` |
| `locks.project_wait_seconds` | `30` | `` | `CHAOS_ENGINE_LOCK_WAIT_SECONDS` |
| `hooks.guard_wait_ms` | `60000` | `` | `CHAOS_ENGINE_GUARD_WAIT_MS` |
| `stores.schedule` | `true` | `--no-store-schedule` | `CHAOS_ENGINE_STORE_SCHEDULE` |
| `stores.schedule_at` | `03:15` | `` | `CHAOS_ENGINE_STORE_SCHEDULE_AT` |
| `stores.refresh_on_session` | `true` | `` | `CHAOS_ENGINE_STORE_REFRESH` |
| `stores.stall_seconds` | `120` | `` | `CHAOS_ENGINE_STALL_SECONDS` |
| `stores.graphify.extra_ignore` | `[]` | `` | `` |
| `stores.mempalace.mine` | `` | `` | `CHAOS_ENGINE_MEMPALACE_MINE` |
| `stores.mempalace.full` | `` | `` | `CHAOS_ENGINE_MEMPALACE_FULL` |
| `stores.mempalace.collection` | `` | `` | `CHAOS_ENGINE_MEMPALACE_COLLECTION` |
| `session.resume_stale_days` | `7` | `` | `CHAOS_ENGINE_RESUME_STALE_DAYS` |
| `ui.interactive` | `false` | `--interactive` | `` |
| `ui.verbosity` | `normal` | `-q, --quiet` | `` |
| `ui.color` | `auto` | `--color` | `CHAOS_ENGINE_COLOR` |
| `ui.ascii` | `false` | `--ascii` | `CHAOS_ENGINE_ASCII` |
| `user_layer.hosts` | `[]` | `--user-hosts` | `CHAOS_ENGINE_USER_HOSTS` |

## Internal environment

These names are read by the installer and hooks. They are not config keys:

- `CHAOS_ENGINE_FIXTURE_ORIGIN`
- `CHAOS_ENGINE_TEST_REPO_GUARD`
- `CHAOS_ENGINE_USER_PATHS`
- `CHAOS_ENGINE_USER_HOME`
- `CHAOS_ENGINE_PROTECTED_GROK_HOME`
- `CHAOS_ENGINE_PROTECTED_GROK_HOME_LOG`
- `CHAOS_ENGINE_PYTHON_PROBE_ONLY`
- `CHAOS_ENGINE_RESOLVE_ONLY`
- `CHAOS_ENGINE_ARGV_ONLY`
- `CHAOS_ENGINE_BOOT_TIME`
- `CHAOS_ENGINE_BRAND_SHOWN`
- `CHAOS_ENGINE_HOOK_SOURCE`
- `CHAOS_ENGINE_HOOK_PAYLOAD`
- `CHAOS_ENGINE_RUN_RECEIPT`
- `CHAOS_ENGINE_JOB`
- `CHAOS_ENGINE_EVIDENCE_`
- `CHAOS_ENGINE_USER_PAYLOAD`
- `CHAOS_ENGINE_COPY_PROMPT`
- `CHAOS_ENGINE_CONFIG_HOME`
- `CHAOS_ENGINE_USER_DIR`
- `CHAOS_ENGINE_STATE_DIR`
- `CHAOS_ENGINE_CACHE_DIR`
