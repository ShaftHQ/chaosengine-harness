---
description: Use when Grok or Copilot may not honor an exit-2 hard block and the compensating checklist applies.
---

# Host Parity Matrix v0

Living adapter-outcome matrix for ChaosEngine across Claude Code, Codex, Grok, Gemini, GitHub Copilot, OpenCode, Cursor, Antigravity, and Grok Bot; independent bots (GPTs and others) follow the Grok Bot column via the bot entry.

Parity means the same workflow *outcomes* on all nine hosts (not UI chrome parity).
Machine-checkable capability pins also live in `scripts/ci/agent_harness_parity.json`.

## Harness parity (permanent)

Any lasting behavior or policy — including the trigger-based Learning Session, the ban on traffic proxies ([no-proxy](no-proxy.md)), and token optimization as Kanban eliminate-waste ([eliminate-waste](eliminate-waste.md)) — MUST live in the portable ChaosEngine overlay: hooks, skills,
installer/doctor, and host guidance adapters (`AGENTS.md` / `CLAUDE.md` /
`GEMINI.md` equivalents). Never leave lasting harness rules only in one
agent's memory or routines. Unchanged `chaos-engine/` sources are not a
valid Learning Session skip on any host.

## One implementation for every host

Claude, Codex (the GPT host), Copilot, Gemini, Grok, OpenCode, Cursor, and
Grok Bot run one portable implementation. Do not add a separate GPT adapter, and do not copy a rule
into a host skill, a host guard, or a second policy file. A new harness
rule is one shared row in `scripts/ci/agent_harness_parity.json`: every
host column names the same evidence path, and one test runs that decision
for every host in `hosts`. File reads and file searches follow this rule
through `hooks/retrieve_justification.py` and `hooks/guard.py`. A cheap read does not wait for a store. A broad search is allowed and owes one retrieve for that session. Downloading a GitHub Actions job log (`gh api` `.../actions/jobs/<id>/logs`, `gh run view --log` / `--log-failed`, or curl of that logs URL), including a filter pipeline or a write into a scratch directory, is not a project read and does not require MemPalace or Graphify. Opening a checkout file in that same command still does. `tool.py
--help` is the same CLI on every host.

A new host is receipt-compatible only when previous routes are a subset
(`host_routes_cover` in `hosts.py`). Rollback writes `priorHostReceipt` bytes
through the still-current candidate before the old core runs. Those checks
already live in `tests/scripts/test_chaos_engine_hosts.py`
(`test_added_host_route_upgrades_without_rewriting_shared_routes`) and
`tests/scripts/test_chaos_engine_generation_runtime.py`
(`test_offline_rollback_validates_previous_before_core_swap`).
Copilot CLI repo-settings hook decisions are covered by
`tests/scripts/test_copilot_cli_hook.py`.
Do not reimplement them.

Legend: P = parity (outcome available), A = adapter-shaped equivalent, G = gap (see below), N = not applicable.


## Matrix

| Surface | Claude Code | Codex | Grok | Gemini | Copilot | OpenCode | Cursor | Antigravity | Grok Bot |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| Install / doctor human UX | P | P | P | P | P | P | P | P | P |
| Host onboarding / activation path | A marketplace/plugin | A marketplace/plugin | A file/hook | A file/hook | A file/hook | A AGENTS.md | A AGENTS.md | A file/hook | A bot entry |
| Router skill (`chaos-engine`) | P | P | P | P | P | P | P | P | P |
| Lifecycle hooks | A | A | A | A | A | A | A | A | G |
| Exit-2 / blocking denial fidelity | A | A | G | A | G | G | G | G | G |
| SessionStart identity and locators / progressive disclosure | A | A | A | A | A | G | A | A | G |
| Skills discovery | A | A | A | A | A | A | A | A | A |
| Companions (Caveman + Ponytail) | P | P | P | P | P | P | P | P | P |
| Self-improve skill (Learning Session) | P | P | P | P | P | P | P | P | P |
| Retrieval soft-degrade (Memory/MemPalace/Graphify) | P | P | P | P | P | P | P | P | P |
| Work-item to merge playbook | P | P | P | P | P | P | P | P | P |
| Learning Session | P | P | P | P | P | P | P | P | P |

## Measured gaps (severity)

| ID | Host(s) | Severity | Gap | Evidence / next |
| --- | --- | --- | --- | --- |
| GAP-EXIT2 | Grok, Copilot | high | `HostCapability.process_exit2_honored=False`; ChaosEngine still returns deny exit 2 + native deny payload (`decision`/`permissionDecision`). Owner doctor surfaces `blockingGap`. | Proven by `tests/scripts/test_chaos_engine_exit2_fidelity.py`; fields on HOST_CAPABILITIES. |
| GAP-SESSIONSTART | — (cleared) | info | ChaosEngine emits the same SessionStart context on all five hosts, including the identity Truth and Principles bullets, under `SESSION_START_MAX_BYTES`=4096. Grok copies that context into `systemMessage` and, when drift or unfinished-task lines would exceed the budget, falls back to the identity path line. A host that ignores SessionStart output still loads companions via the entrypoint. Codex post-compaction: after a root session compacts, Codex runs SessionStart with `source: "compact"` before the next model request and adds `hookSpecificOutput.additionalContext` to that continuation ([Codex hooks](https://developers.openai.com/codex/hooks)). | Proven by `tests/scripts/test_chaos_engine_sessionstart_locator_parity.py`. |
| GAP-HOOK-TRUST | Grok | medium | Project hook trust (`/hooks-trust`, projectTrusted) is host-gated. `/hooks-trust` is the advisory only when `grok inspect --json` says the project is not trusted, or inspect did not return trust. A trusted project with `launch.py` hooks loaded is healthy. A trusted project missing an event names that event and does not ask for `/hooks-trust`. Doctor stays healthy and reports sync-advisory. Never flip overall doctor to recovery-required for Grok trust alone when hosts verify is healthy. | Host onboarding card + grok_runtime_status (advisory). |
| GAP-GROK-LEAN | Grok | medium | Dual Claude-compat + native `.grok` hooks double CE context; installer merges lean `[compat.*]` into user `~/.grok/config.toml`; optional `--lean-grok-skills`; skill adapters stay pointers. | [`grok_lean_config.py`](../runtime/grok_lean_config.py) + doctor sync-advisory. |
| GAP-IMPL-COMPANIONS | all | medium | Implementation must load Caveman+Ponytail at ultra via portable overlay; not optional and not SessionStart-only. Doctor **self-heals** missing companions from CE vendor (official publish); agentic handoff with official repair/install only if heal fails. | `rematerialize_companions` + doctor. |
| GAP-IDENTITY-MD | all | medium | Durable `.chaos-engine/identity.md` with protected Truth markers. SessionStart injects the Truth and Principles body (path locator if the file is missing or over `SESSION_START_MAX_BYTES`). Claude reads that body from `hookSpecificOutput.additionalContext`, including SessionStart `source=compact`. Instruction files still point at the file. Doctor create-on-heal. | [`identity_md.py`](../runtime/identity_md.py) + seed [`identity.md`](../identity.md);. |
| GAP-MARKETPLACE-CLI | Claude, Codex | low | Marketplace/plugin auto-activation needs host CLI on PATH; absent CLI still installs adapters but activation is manual. | Onboarding cards. |
| GAP-COPILOT-DETECT | Copilot | low | The wizard list is soft (`gh` / `code` / `cursor`). Host completion does not select Copilot from those programs. Name `copilot` with `--hosts` or `CHAOS_ENGINE_HOST`. | Onboarding card and [INSTALL.md](../INSTALL.md#clients-this-command-can-complete). |
| GAP-GEMINI-NODE | Gemini | low | Hook launcher needs Node.js; unsupported native events remain explicit capability gaps. | Onboarding card + launch.js. |
| GAP-OPENCODE-HOOKS | OpenCode | info | The plain JS plugin `.opencode/plugins/chaos-engine-receipt.js` calls `hooks/launch.py`. `tool.execute.before` / `execute.before` throw on deny. `session.idle` is observe-only. `session.created` has no documented context channel, so SessionStart stays G. Exit 2 stays G until a live probe. | `runtime/hook_surfaces.py`; `tests/scripts/test_hook_parity.py`. |
| GAP-CURSOR-HOOKS | Cursor | info | `.cursor/hooks.json` version 1 calls `hooks/launch.py` for the ten agent events. Deny renders `permission`, `additional_context`, and `followup_message`. `failClosed` is set only on `preToolUse`. Exit 2 stays G until a live probe. One guard run per event stays unclaimed until a posted trace count. | `runtime/hook_surfaces.py`; `tests/scripts/test_hook_parity.py`. |
| GAP-ANTIGRAVITY-HOOKS | Antigravity (`agy`) | info | `.agents/hooks.json` registers a named `"chaos-engine"` hook calling `hooks/launch.py`. PreToolUse and PostToolUse use the scoped `hooks/matchers.json` groups (including `run_command`, `run_workflow`, and `swarm`), not `.*`. Flat arrays are `SessionStart`, `PreInvocation`, and `Stop`. `PostInvocation` stays a kernel alias and is not a per-turn spawn. Antigravity treats non-zero hook exits as fail-open, so denies emit exit-0 JSON (`decision: "deny"`, `decision: "continue"` + `reason`, or `errorMessage` + `terminationBehavior: "terminate"`). A Stop with `fullyIdle: false` or terminal `terminationReason` does not emit `decision: "continue"`. SessionStart/PreInvocation inject context via `injectSteps`. MCP stays CLI-first: Antigravity reads `~/.gemini/config/mcp_config.json` or `plugins/<name>/mcp_config.json`, not `.mcp.json`, and a plugin bundle is `plugins/<name>/plugin.json`. | `runtime/hook_surfaces.py`; `tests/scripts/test_antigravity_support.py`. |
| GAP-GROKBOT-HOOKS | Grok Bot | medium | Instruction-only agent: auto-loads nothing from the checkout and has no hook runtime. At task start it reads the core card and both companion cards itself, then runs one retrieve. Same receipt substitution; `worktree_overlay.py verify` reports it as instruction-only. | `hosts.INSTRUCTION_ONLY_HOSTS`; research receipt;. |
| GAP-BOT-ENTRY | Independent bots (GPTs, Claude Projects, others) | medium | No checkout auto-load and no hooks: start from [bot entry](bot-entry.md) (`tool.py entry`, or an exported entry file for bots without repository access). Residual risk: a hookless bot can still submit a person-only assessment if it skips `tool.py ethics-check`. | `hosts.INSTRUCTION_ONLY_HOSTS`; research receipt;. |
| GAP-GROK-BUNDLED | Grok | info | Grok product bundled skills (pdf/pptx/imagine/game-*) and session GitHub MCP cannot be deleted from the install tree. CE does not vendor them; doctor strips user GitHub MCP when gh is healthy and documents this limit. | prefer-cli-over-mcp. |
| GAP-GROK-CAVEMAN | — (cleared) | info | Always-on CE card (`caveman=ultra` in `hooks/lifecycle.py`) is the Grok communication constitution. Do not copy Caveman skill bodies into `AGENTS.md`. | Closed: locator-only host guidance plus lifecycle ultra selector. No proxy. |
| GAP-CLAUDE-IMPORT | Claude surfaces that do not expand `@AGENTS.md` | medium | A Claude surface that does not expand `CLAUDE.md`'s `@AGENTS.md` import, and has no installed overlay, sees only that one import line. That explains a report that Claude ignored the rules. Installed Claude Code stays the strongest hook mapping. | Tracked `CLAUDE.md` stays exactly `@AGENTS.md` (`test_fresh_import_pointers_are_exactly_one_import`). |



## Official hook docs read 2026-11-22

Pins in `evals/host-doc-conformance.json` follow the pages below. A missing official event is registered only when `LIFECYCLE_EVENTS` already handles it and the adapter already renders that payload. Provider-only events that need new policy stay in the pin and are not stripped for consistency.

| Host | Doc read 2026-11-22 | Registered this pass | Recorded, not registered |
| --- | --- | --- | --- |
| Claude Code | https://code.claude.com/docs/en/hooks | none; guard events were already registered once | Setup, InstructionsLoaded, UserPromptExpansion, MessageDisplay, PostToolBatch, PermissionDenied, Notification, TaskCreated, TaskCompleted, TeammateIdle, ConfigChange, CwdChanged, DirectoryAdded, FileChanged, WorktreeCreate, WorktreeRemove, PreModelSwitch, PostModelSwitch, PermissionRequest, StopFailure, Elicitation, ElicitationResult |
| Codex | https://developers.openai.com/codex/hooks | PreCompact, PostCompact | PermissionRequest, PreModelRequest, PostModelRequest, Interrupt. PostToolUseFailure is not on the page. |
| Grok | https://docs.x.ai/build/features/hooks | PreCompact, PostCompact | PermissionDenied, StopFailure, Notification |
| Gemini CLI | https://geminicli.com/docs/hooks | none | BeforeModel, AfterModel, BeforeToolSelection, Notification |

The previous Grok URL `https://docs.x.ai/docs/guides/grok-build/hooks` returned HTTP 404. The live page lists PascalCase only. Snake_case `GROK_HOOK_EVENT` values stay convenience spellings, not a second command. That page says exit code 2 denies and every other failure is fail-open. `HostCapability.process_exit2_honored` stays false until a live probe.

Codex says the same command in two files for one event can run twice. This tree writes Codex hooks only in `.codex/hooks.json`. `plugins/chaos-engine/hooks/hooks.json` stays an empty `hooks` object, and `.codex/config.toml` has no `[hooks]` table. No second ChaosEngine command was registered for one host event, so none was removed. Grok also reads `.claude/settings.json` and `.cursor/hooks.json`. That fan-out is the host, not a second copy of the Grok command.

## Guard runs measured (#108, #123)

No dedupe ships from these counts. `CE_HOOK_TRACE` stays off unless set, and one call writes one line. Do not register Stop a second time, and do not drop the second Stop in `launch.py`. A repository rooted under `/tmp` is not project-trusted, so Grok loads no project hooks there.

| Host | Version | OS | Event | Runs | Reason |
| --- | --- | --- | --- | --- | --- |
| Grok | 1.0.92 | not recorded | Stop | 2 | Session `01a1fbcc-68a1-7ff3-8f60-d3b1bb2c8846`, `hook_count=1`, two `CE_HOOK_TRACE` lines. One project Stop command. Host double dispatch, not an install defect. |
| Cursor | not measured | not measured | not measured | not-measured | `cursor-agent` still requires login. This session posted no trace count. |
| Copilot | not measured | not measured | not measured | not-measured | No scripted Copilot count in this session. |
| JetBrains | not measured | not measured | not measured | not-measured | No JetBrains plugin run in this session. |

Live cursor-agent, Copilot, and JetBrains logins are blocking: unverifiable. This archive does not add trace lines for those hosts. Research copy: [2026-11-20 hook parity](../docs/research/2026-11-20-hook-parity/research-full.md).

## Official self-heal

Doctor runs each required third party's **official install command** (or CE vendor rematerialize for Caveman/Ponytail) before agentic handoff. Inventory and heal wiring live in [`official_self_heal.py`](../runtime/official_self_heal.py) + `chaos-engine/INSTALL.md` (repo-only). Opt-out `--without-*` stays off. Parent epic:.

## How to refresh

1. Update rows when adapter contracts or Host Parity Wave B issues land.
2. Keep `scripts/ci/agent_harness_parity.json` as the machine-checked pin set.
3. Prefer outcome language (P/A/G) over host UI chrome comparisons.
4. Re-run the eval / parity fixture suite (`python3 scripts/ci/chaos_engine_eval_parity.py`, repo-only;
   see [eval-parity-fixtures](eval-parity-fixtures.md)) after hook or adapter changes.
   Fixture failures ratchet into hooks, skills, or a documented matrix gap — never
   weaken the fixture to look green.

Checked-in memory for one-router / CLI-owned MCP / project-mode Caveman:
`.memory/memory/constraints/host-parity-one-router-cli-owned-mcp-project-mode-caveman.md` (repo-only).
See also the [hook trigger map](hook-trigger-map.md).


## Tool-output replacement

No supported host has a proven PostToolUse replacement for the tool-result
body in this tree. Grok can adapt `additionalContext` for SessionStart and can
show deny text. That does not replace the tool result. This delivery is a
manual store ([tool_output_store.py](../runtime/tool_output_store.py), `tool.py output-search`).
It does not claim the original bytes left the model window.

| Host | PostToolUse tool-output replacement |
| --- | --- |
| Claude Code | not proven |
| Codex | not proven |
| Grok | not proven |
| Gemini | not proven |
| Copilot | not proven |
| OpenCode | not proven |
| Cursor | not proven |
| Grok Bot | not proven |

## GAP-EXIT2 compensating UX checklist (Grok / Copilot)

GAP-EXIT2-SENTENCE: GAP-EXIT2: ChaosEngine still emits decision=block or permissionDecision=deny and exit 2; verify host trust.

Do **not** pretend a hard process exit-2 block on these hosts. ChaosEngine still
emits `decision=block` / `permissionDecision=deny` and exit 2; owners must
verify trust and static surfaces.

- [x] Doctor human output shows `blockingGap` / GAP-EXIT2 warning for Grok and Copilot (`format_blocking_fidelity_warnings`)
- [x] Host parity row `GAP-EXIT2` stays documented with severity and proof test
- [x] After a deny, tell the owner to check project trust / hooks trust (Grok: `grok inspect --json`, `/hooks-trust`) and IDE Copilot trust — not “the tool was hard-blocked by exit code”
- [x] SessionStart / Heal locators remain available when marketplace plugins are absent
- [x] Exit-2 fidelity unit test remains green: `tests.scripts.test_chaos_engine_exit2_fidelity`

