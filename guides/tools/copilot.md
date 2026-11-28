# GitHub Copilot

Host id: `copilot`.

Install as in [INSTALL.md](../../INSTALL.md). The wizard may list Copilot when `gh`, `code`, or `cursor` is on `PATH`. That list is not a selection. Name `copilot` with `--hosts copilot` or `CHAOS_ENGINE_HOST=copilot`.

Copilot reads `AGENTS.md`, `.github/copilot-instructions.md`, and `.github/skills/chaos-engine/SKILL.md`. Registered events are sessionStart, sessionEnd, userPromptSubmitted, userPromptTransformed, preToolUse, postToolUse, postToolUseFailure, permissionRequest, agentStop, subagentStart, subagentStop, preCompact, errorOccurred, and notification. permissionRequest denies the same cases as preToolUse. A deny includes permissionDecision `deny`, permissionDecisionReason, behavior `deny`, and message. behavior is what short-circuits the Copilot CLI permission service. permissionDecision stays because exit 2 is not a proven process block. subagentStart prepends the same harness context SessionStart already emits, as additionalContext, and exits 0. It does not deny or block creation. The vendor does not emit subagentStart for the general-purpose agent; that absence is not a failure. userPromptTransformed, errorOccurred, and notification only observe: they exit 0 and do not emit a deny decision. notification does not return additionalContext. Lifecycle hooks cover the CLI. Cloud agent does not fire permissionRequest. This checkout does not claim a live cloud or CLI run. Cloud and IDE surfaces are checked statically. Exit code 2 is not honored (GAP-EXIT2).

Published context and instruction caps are `unknown`. See [capability profiles](../../references/profiles/capabilities.md).

Example, not yet validated by the offline conformance job: install into a repository of stories, then follow [the product-owner start](../start-product-owner.md). No Java is required.
