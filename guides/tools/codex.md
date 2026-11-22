# Codex

Host id: `codex`.

Install as in [INSTALL.md](../../INSTALL.md), then name this host with `--hosts codex` or `CHAOS_ENGINE_HOST=codex`. Codex registers a marketplace when `codex` is on `PATH`. A missing CLI still leaves the adapter files.

Codex reads `AGENTS.md` and the skill adapter `.agents/skills/chaos-engine/SKILL.md`. Lifecycle hooks include SessionStart, SubagentStart, UserPromptSubmit, PreToolUse, PostToolUse, Stop, SubagentStop, PreCompact, PostCompact, and SessionEnd. `PostToolUseFailure` is not an official Codex event; failure is read from `PostToolUse`. Exit code 2 is honored on the CLI. The bundled plugin file `plugins/chaos-engine/hooks/hooks.json` stays an empty `hooks` object, so Codex desktop does not register a second copy beside project `.codex/hooks.json`. Codex states that duplicate registrations run twice.

A generated `.codex/hooks.json` is configured, not running. Codex skips a non-managed hook until the operator reviews and trusts that exact definition in `/hooks`. A changed hook is skipped until trusted again. `[features] hooks = false` in `config.toml` turns hooks off (`codex_hooks` is the deprecated alias). Marketplace plugin activation does not prove a hook ran. See the [Codex hooks guide](https://developers.openai.com/codex/hooks).

Published context and instruction caps are `unknown`. See [capability profiles](../../references/profiles/capabilities.md).

Example, checked by the offline conformance job: install into a repository of stories, then follow [the developer start](../start-developer.md). No Java is required.

<!-- host-doc-example: codex
entry: AGENTS.md
paths: AGENTS.md, .codex/config.toml, .codex/hooks.json
config_keys: mcp_servers, project_doc_max_bytes, hooks
-->
