# GitHub Copilot

Host id: `copilot`.

Install as in [INSTALL.md](../../INSTALL.md). The wizard may list Copilot when `gh`, `code`, or `cursor` is on `PATH`. That list is not a selection. Name `copilot` with `--hosts copilot` or `CHAOS_ENGINE_HOST=copilot`.

Copilot reads `AGENTS.md`, `.github/copilot-instructions.md`, and `.github/skills/chaos-engine/SKILL.md`. Kernel-registered events are sessionStart, userPromptSubmitted, preToolUse, postToolUse, postToolUseFailure, agentStop, subagentStop, preCompact, and sessionEnd. Lifecycle hooks cover the CLI. Cloud and IDE surfaces are checked statically. Exit code 2 is not honored (GAP-EXIT2).

Published context and instruction caps are `unknown`. See [capability profiles](../../references/profiles/capabilities.md).

Example, not yet validated by the offline conformance job: install into a repository of stories, then follow [the product-owner start](../start-product-owner.md). No Java is required.
