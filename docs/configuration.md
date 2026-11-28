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

The key table is generated. See the [settings reference](reference/settings.md) for every key, default, flag, environment variable, opt-in, and effect.

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
