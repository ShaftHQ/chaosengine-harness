# Gemini CLI

Host id: `gemini`.

Install as in [INSTALL.md](../../INSTALL.md). Inference never selects Gemini. Name it with `--hosts gemini` or `CHAOS_ENGINE_HOST=gemini`. The hook launcher is Node.js (`hooks/launch.js`).

Gemini reads `GEMINI.md` and the skill adapter `.gemini/skills/chaos-engine/SKILL.md`. Registered events are SessionStart, SessionEnd, BeforeAgent, AfterAgent, BeforeModel, AfterModel, BeforeToolSelection, BeforeTool, AfterTool, PreCompress, and Notification. BeforeAgent maps to UserPromptSubmit, BeforeTool and BeforeModel map to PreToolUse, AfterTool maps to PostToolUse, AfterAgent maps to Stop, and PreCompress maps to PreCompact. BeforeModel denies with exit 2 for the same cases as PreToolUse. BeforeToolSelection omits a denied tool and exits 0. AfterModel and Notification only observe. Exit code 2 is honored.

Published context and instruction caps are `unknown`. See [capability profiles](../../references/profiles/capabilities.md).

Example, checked by the offline conformance job: install into a repository of test plans, then follow [the tester start](../start-tester.md). No Java is required.

<!-- host-doc-example: gemini
entry: GEMINI.md
paths: GEMINI.md, .gemini/settings.json
config_keys: context, hooks, mcpServers
-->
