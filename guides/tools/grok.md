# Grok

Host id: `grok`.

Install as in [INSTALL.md](../../INSTALL.md), then name this host with `--hosts grok` or `CHAOS_ENGINE_HOST=grok`. Naming `grok` does not by itself merge the lean config span.

Grok reads `AGENTS.md` and `.grok/plugins/chaos-engine`. Lifecycle hooks match the Claude set, including SessionStart, SubagentStart, UserPromptSubmit, PreToolUse, PostToolUse, PostToolUseFailure, Stop, SubagentStop, PreCompact, PostCompact, and SessionEnd. PermissionDenied, StopFailure, and Notification stay observe: if the guard would deny them, host `grok` returns exit 0 and no output. Stop cannot block. A live PreToolUse probe denied with `Hook denied: CE-DENY-PROBE` and the tool did not run, so `process_exit2_honored` is true. ChaosEngine still emits a deny and exit code 2 on blocking events.

A non-git directory has no project hook root. The user hook is `~/.grok/hooks/chaos-engine.json`, or `$GROK_HOME/hooks/chaos-engine.json` when `GROK_HOME` is set. Install merges that file and registers PreToolUse only, using the shared guard.

A trusted project (`grok inspect --json` reports `projectTrusted: true`) whose loaded hooks call `launch.py` for every required event is activated. `/hooks-trust` is the next step only for a bound project whose inspect says `projectTrusted` is false. Inspect failure is `CE_GROK_INSPECT_FAILED`. Unbound `projectRoot` is `CE_GROK_PROJECT_UNBOUND`. Those two do not mention `/hooks-trust`. A trusted project with a missing event names that event. Doctor stays healthy for this host-gated trust check (GAP-HOOK-TRUST).

Published context and instruction caps are `unknown`. See [capability profiles](../../references/profiles/capabilities.md).

Example, checked by the offline conformance job: install into a repository of stories, then follow [the scrum-master start](../start-scrum-master.md). No Java is required.

<!-- host-doc-example: grok
entry: AGENTS.md
paths: AGENTS.md, .grok/hooks/lifecycle.json
config_keys: hooks
-->
