# Cursor

Host id: `cursor`.

Install as in [INSTALL.md](../../INSTALL.md). A `cursor` program on `PATH` does not select this host. Name it with `--hosts cursor` or `CHAOS_ENGINE_HOST=cursor`.

Cursor reads `AGENTS.md`. Completing this host, and a full install, writes version-1 `.cursor/hooks.json`. Every command calls `hooks/launch.py`. Kernel-registered events are sessionStart, beforeSubmitPrompt, preToolUse, postToolUse, postToolUseFailure, subagentStart, subagentStop, stop, preCompact, and sessionEnd. `preToolUse` can deny with `permission`. `sessionStart` can add `additional_context`. `stop` can add `followup_message`. `failClosed` is set only on `preToolUse`. Exit 2 is not yet a proven process block.

Published context and instruction caps are `unknown`. See [capability profiles](../../references/profiles/capabilities.md).

Example, checked by the offline conformance job: install into a repository of stories, then follow [the developer start](../start-developer.md). No Java is required.

<!-- host-doc-example: cursor
entry: AGENTS.md
paths: AGENTS.md
-->
