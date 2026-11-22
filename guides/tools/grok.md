# Grok

Host id: `grok`.

Install as in [INSTALL.md](../../INSTALL.md), then name this host with `--hosts grok` or `CHAOS_ENGINE_HOST=grok`. Naming `grok` does not by itself merge the lean config span.

Grok reads `AGENTS.md` and `.grok/plugins/chaos-engine`. Lifecycle hooks match the Codex set, including SessionStart, SubagentStart, UserPromptSubmit, PreToolUse, PostToolUse, PostToolUseFailure, Stop, SubagentStop, PreCompact, PostCompact, and SessionEnd. ChaosEngine still emits a deny and exit code 2. This host can ignore that exit (GAP-EXIT2 in `references/host-parity-matrix.md`).

A trusted project (`grok inspect --json` reports `projectTrusted: true`) whose loaded hooks call `launch.py` for every required event is activated. `/hooks-trust` is the next step only when that inspect says the project is not trusted, or when inspect itself did not return trust. A trusted project with a missing event names that event. Doctor stays healthy for this host-gated trust check (GAP-HOOK-TRUST).

Published context and instruction caps are `unknown`. See [capability profiles](../../references/profiles/capabilities.md).

Example, checked by the offline conformance job: install into a repository of stories, then follow [the scrum-master start](../start-scrum-master.md). No Java is required.

<!-- host-doc-example: grok
entry: AGENTS.md
paths: AGENTS.md, .grok/hooks/lifecycle.json
config_keys: hooks
-->
