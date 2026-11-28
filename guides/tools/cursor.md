# Cursor

Host id: `cursor`.

Install as in [INSTALL.md](../../INSTALL.md). A `cursor` program on `PATH` does not select this host. Name it with `--hosts cursor` or `CHAOS_ENGINE_HOST=cursor`.

Cursor reads `AGENTS.md`. Completing this host, and a full install, writes version-1 `.cursor/hooks.json`. Every command calls `hooks/launch.py`. There is one hooks file, no prompt hook, and no HTTP hook. Kernel-registered events are sessionStart, beforeSubmitPrompt, preToolUse, postToolUse, postToolUseFailure, subagentStart, subagentStop, stop, preCompact, sessionEnd, beforeShellExecution, afterShellExecution, beforeMCPExecution, afterMCPExecution, beforeReadFile, afterFileEdit, beforeTabFileRead, afterTabFileEdit, afterAgentResponse, afterAgentThought, and workspaceOpen. `preToolUse` can deny with `permission`. `sessionStart` can add `additional_context`. `stop` can add `followup_message`. `beforeShellExecution` denies the same cases as `preToolUse`. The vendor field is `command`. A deny is `permission` `deny`, not `ask`, plus `user_message`. A command that is not blocked does not deny. `beforeReadFile` and `beforeTabFileRead` deny a secret path the existing guard already denies. The vendor field is `file_path`. `permission` is `deny`. They do not use `ask`. `beforeTabFileRead` output is `permission` only. `beforeMCPExecution` can deny and does not emit `updated_input`. `afterShellExecution`, `afterMCPExecution`, `afterFileEdit`, `afterTabFileEdit`, `afterAgentResponse`, `afterAgentThought`, and `workspaceOpen` only observe: they exit 0 and do not emit a deny. `postToolUse` does not block. `failClosed` is true on `preToolUse`, `beforeShellExecution`, and `beforeReadFile`, and on no other Cursor event. Exit 2 is not yet a proven process block. A missing `cursor-agent` login is blocking: unverifiable. Where a hook does not enforce, run `tool.py delete-check`, `tool.py pre-done --gate`, `tool.py dod`, and `tool.py ethics-check`.

Published context and instruction caps are `unknown`. See [capability profiles](../../references/profiles/capabilities.md).

Example, checked by the offline conformance job: install into a repository of stories, then follow [the developer start](../start-developer.md). No Java is required.

<!-- host-doc-example: cursor
entry: AGENTS.md
paths: AGENTS.md
-->
