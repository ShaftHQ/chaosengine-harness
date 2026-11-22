# Hook trigger map

Each ChaosEngine lifecycle event fires only at its logical point. Must-hold
rules are PreToolUse deny. PostToolUse stays silent unless the text changes the
next decision. SessionStart is guide-only context (Grok ignores SessionStart stdout); standing instructions live in the project router, not SessionStart.

| Event | Hosts | Mode | Next-decision effect |
| --- | --- | --- | --- |
| `SessionStart` | Claude, Codex, Gemini, Grok, Copilot | guide | Inject compact locators and the identity body (Truth and Principles bullets). Not enforcement. Grok reads `systemMessage`, not bare stdout, and that adapted payload stays inside `SESSION_START_MAX_BYTES`. Claude reads `hookSpecificOutput.additionalContext`. After compaction, Claude and Codex re-inject on SessionStart with source `compact`. |
| `SubagentStart` | Claude, Codex, Grok | guide | Same injection as SessionStart: locators plus the identity body. Claude and Codex keep `hookEventName` as `SubagentStart`. Grok does not fire SessionStart for a subagent, and a Grok spawn does not emit SubagentStart. Grok's model-visible load is `.grok/rules/entrypoint.md`, `.grok/rules/identity.md`, and `.grok/rules/companions.md`, because SessionStart `systemMessage` is a hook annotation outside the prompt and `AGENTS.md` must not repeat the companion intensity. Skill bodies stay one source under `.chaos-engine/skills/`. |
| `UserPromptSubmit` | Claude, Codex, Gemini, Grok, Copilot | guide | Companion mode tracking. Gemini and Copilot, which have no subagent-start event, inject the same locators once per agent scope when SessionStart has not. Claude and Codex do that only for a scope SubagentStart missed. Grok discards this event's context. |
| `PreToolUse` | Claude, Codex, Gemini, Grok, Copilot, Cursor, OpenCode, Antigravity | enforce | Deny catastrophic or out-of-contract tool use; hold work that owes a reflection receipt; deny primary-checkout mutations when a session worktree exists. Cursor renders `permission: deny`. OpenCode throws. Antigravity writes `decision: deny` and exits 0. |
| `PostToolUse` | Claude, Codex, Gemini, Grok, Copilot | guide | Record mutation/delivery for reflection. Stay silent unless stdout changes the next decision. |
| `PostToolUseFailure` | Claude, Grok, Copilot, Cursor, OpenCode | guide | Record failure and inject a pending reflection checkpoint only when one is owed. Codex has no official `PostToolUseFailure`; failure on Codex stays on `PostToolUse`. |
| `Stop` | Claude, Codex, Gemini, Grok, Copilot | enforce | Collect incomplete delivery duties; require the root Learning Session after every confirmed delivery (Learning Session after every final delivery). |
| `SubagentStop` | Claude, Codex, Grok, Copilot | enforce | Delegate-owned completion duties only. Never start the root Learning Session. |
| `PreCompact` | Claude, Codex, Gemini, Grok, Copilot | guide | Gemini and Copilot re-inject compact locators that compaction would drop. Claude PreCompact stdout is the compaction-summary channel, not JSON additionalContext. Claude and Codex re-inject on SessionStart with source `compact`. Codex and Grok list this event (read 2026-11-22); the guard already emits the compact locator and no new deny policy is added. |
| `PostCompact` | Claude, Codex, Grok | guide | No Claude context channel (side effects only). The handler still emits the PreCompact payload; Claude ignores it. Claude re-injects on SessionStart with source `compact`. Codex runs PostCompact after compaction, and plain text on stdout is ignored; the identity re-injection is SessionStart with `source: "compact"` ([Codex hooks](https://developers.openai.com/codex/hooks)). Grok lists PostCompact and ignores passive stdout. Gemini and Copilot do not have this event. |
| `PermissionRequest` | Claude | gap | Guide-only. No ChaosEngine hook returns allow or deny. The owner decides. |
| `Elicitation` | Claude | gap | Guide-only MCP elicitation. Do not auto-approve. |
| `ElicitationResult` | Claude | gap | Guide-only result of an elicitation. Do not auto-approve. |
| `SessionEnd` | Claude, Codex, Gemini, Grok, Copilot | enforce | Remove this session's worktree after merge is recorded and the tree is clean. |

Hosts without a hook primitive cannot enforce this table; say so in the install
receipt. Narrow matchers live in `hooks/matchers.json`.
