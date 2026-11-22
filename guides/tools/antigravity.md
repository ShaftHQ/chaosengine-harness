# Antigravity

Host id: `antigravity` (`agy`).

Install as in [INSTALL.md](../../INSTALL.md). Name this host with `--hosts antigravity` or `CHAOS_ENGINE_HOST=antigravity`.

Antigravity reads `AGENTS.md` and `GEMINI.md`. The host route stays `AGENTS.md`. Completing this host writes `.agents/hooks.json` under a named `chaos-engine` hook. Every command calls `hooks/launch.py`. Kernel-registered events are SessionStart, PreToolUse, PostToolUse, PreInvocation, PostInvocation, and Stop. PreToolUse and PostToolUse use the scoped matchers from `hooks/matchers.json`, including `run_command`, `run_workflow`, and `swarm`. SessionStart, PreInvocation, and Stop are flat handler lists. PostInvocation is a kernel alias of PostToolUse and is not spawned on every turn.

A non-zero hook exit is fail-open. Denies are JSON on exit 0: `decision: "deny"` on PreToolUse, `decision: "continue"` plus `reason` on a Stop that still owes work, or `errorMessage` plus `terminationBehavior: "terminate"`. A Stop with `fullyIdle: false`, or `terminationReason` `USER_CANCELED`, `ERROR`, or `MAX_TOKEN_BUDGET_EXCEEDED`, does not emit `decision: "continue"`. SessionStart and PreInvocation inject context with `injectSteps`.

MCP stays CLI-first. Antigravity reads `~/.gemini/config/mcp_config.json` or `plugins/<name>/mcp_config.json`. It does not read `.mcp.json`. A plugin bundle is `plugins/<name>/plugin.json`.

The host receipt covers `.agents/hooks.json` with a digest and a backup blob. Doctor reports tampering. `python3 .chaos-engine/tool.py retrieve` is the trusted retrieve path. An untrusted script that launches a dynamic subprocess stays denied, and that denial does not set `retrieved: true`.

Published context and instruction caps are `unknown`. See [capability profiles](../../references/profiles/capabilities.md).

Example, not yet validated by the offline conformance job: install into a repository, then follow [the developer start](../start-developer.md).
