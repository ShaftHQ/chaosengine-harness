# Claude Code

Host id: `claude`.

Install as in [INSTALL.md](../../INSTALL.md), then name this host with `--hosts claude` or `CHAOS_ENGINE_HOST=claude`. Portable files are written for every host. Completing Claude also registers a marketplace when `claude` is on `PATH`. A missing CLI still leaves the adapter files and the install succeeds.

Claude Code reads `CLAUDE.md`, which points at `AGENTS.md`, and the skill adapter `.claude/skills/chaos-engine/SKILL.md`. Lifecycle hooks include SessionStart, SubagentStart, UserPromptSubmit, PreToolUse, PostToolUse, PostToolUseFailure, Stop, SubagentStop, PreCompact, PostCompact, SessionEnd, PreSkillShellCommand, UserPromptExpansion, PermissionRequest, Setup, InstructionsLoaded, MessageDisplay, PostToolBatch, PermissionDenied, Notification, TaskCreated, TaskCompleted, StopFailure, TeammateIdle, ConfigChange, CwdChanged, DirectoryAdded, FileChanged, WorktreeCreate, WorktreeRemove, PreModelSwitch, PostModelSwitch, Elicitation, and ElicitationResult. PostCompact re-injects the same compact locators as PreCompact. PreSkillShellCommand and UserPromptExpansion deny like PreToolUse. PermissionRequest can deny and is not auto-approved. Elicitation and ElicitationResult are not decided. InstructionsLoaded does not append companion bodies. Exit code 2 is honored.

Published context and instruction caps are `unknown`. See [capability profiles](../../references/profiles/capabilities.md).

Example, checked by the offline conformance job: install into a repository of stories, then follow [the product-owner start](../start-product-owner.md). No Java is required.

<!-- host-doc-example: claude
entry: CLAUDE.md
paths: CLAUDE.md, AGENTS.md
-->
