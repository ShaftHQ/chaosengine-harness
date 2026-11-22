# ChaosEngine Harness Hook Parity, Entry Points, and Implementation Tracker

> Source: Gemini research share https://share.gemini.google/g0Aaq50Oib3x (gemini.google.com/share/29ec1c7ae691). Markdown rendering of the official 18-page PDF export ([research.pdf](research.pdf), "ChaosEngine Hook Parity Implementation Tracker"); the prose, headings, lists and inline citations follow the PDF verbatim. Tables come from the same report's HTML capture because the PDF clips long cells. The interactive tracker is [research.html](research.html); the PDF has no HTML-tracker section. Converted 2026-11-20.

## Executive Overview & Evidentiary Boundaries

ChaosEngine (ShaftHQ/chaosengine-harness, extracted from ShaftHQ/SHAFT_ENGINE under the MIT license as of November 2026) enforces a provider-neutral SDLC contract through instruction entry points (AGENTS.md, CLAUDE.md, GEMINI.md, and skills/chaos-engine/SKILL.md), a stdin-driven JSON hook dispatcher (hooks/guard.py paired with hooks/reflection.py, secret_guard.py, and overlay_pre_push.py), and mechanical CLI/CI gates (tool.py, dod.py, and scripts/ci/harness_pr_gate.py) (SHAFT_ENGINE #8062, SHAFT_ENGINE #8051). Issue logs and probe records confirm that hooks/guard.py actively implements UserPromptSubmit, PreToolUse, PostToolUse, and Stop (_stop_block_reason)—with active host wiring verified for Claude Code (CLI and Desktop Code tab), OpenAI Codex CLI (.codex/hooks.json for PreToolUse and PostToolUse), and Grok Build (an 8-event .grok/hooks/lifecycle.json configuration)—while PostToolUseFailure parity (SHAFT_ENGINE #5000) and SubagentStart locator injection (#7390 in SHAFT_ENGINE Releases) remain partial (SHAFT_ENGINE #5354, SHAFT_ENGINE #7860). Conversely, Gemini CLI (GEMINI.md instruction block only), Cursor (GAP-CURSOR-HOOKS), OpenCode (GAP-OPENCODE-HOOKS), and hookless bots such as Grok Bot rely on instruction loading plus tool.py pre-done and CI PR validation, and Google Antigravity and GitHub Copilot have no verified repository hook-file generators in the retrieved ChaosEngine issues (SHAFT_ENGINE #6178, SHAFT_ENGINE #8051).

Across all target coding agents documented through November 2026, lifecycle hook surfaces span 39 canonical hook capabilities and diverge sharply outside core tool-call interception:

- Claude Code exposes the largest lifecycle surface with 33 events across command, http, prompt, and agent handlers plus in-process JavaScript function mods—19 of which do not exist in any other client's declarative hook contract (Claude Code Hooks Reference, Codex CLI Hooks Breakdown).
- Grok Build defines 14 events, with PreToolUse as its only blocking event (SpaceXAI Grok Build Hooks).
- Gemini CLI exposes 11 Before*/After* events (described as "roughly 12" in one community article) (gemini-cli-hooks).
- GitHub Copilot splits across 8 events in VS Code/Copilot Desktop, 7 camelCase events plus agent-frontmatter hooks in Copilot CLI, a Cloud Agent subset, and 5 SDK hook types (GitHub Copilot Hooks Reference, VS Code Customizations Hooks, GitHub Copilot SDK Hooks Overview).
- Google Antigravity provides 6 JSON events (uniquely exposing PreInvocation and PostInvocation while lacking a pre-model UserPromptSubmit gate) plus 5 Python SDK hook classes (Google Antigravity Hooks, Antigravity Python SDK Hooks, NeuralTrust Antigravity Integration).
- OpenAI Codex CLI exposes 5 lifecycle events (explicitly omitting PostToolUseFailure) alongside lifecycle hooks restricted to manually installed Codex desktop plugins (SHAFT_ENGINE #5000, OpenAI Plugins Documentation).

Four evidentiary boundaries bound this mapping:

1. While ShaftHQ/chaosengine-harness contains hooks/ and plugin-adapters/ directories, individual files beyond hooks/guard.py, hooks/reflection.py, secret_guard.py, and overlay_pre_push.py—as well as the exact 8 event names inside Grok's .grok/hooks/lifecycle.json beyond the three probed events—are unexposed in the retrieved repository landing pages and issues.
2. Although JetBrains / IntelliJ IDEA plugins exist for Claude Code, GitHub Copilot, Continue, Kilo Code, Amazon Q Developer, JetBrains Junie, and SHAFT (shaft-intellij), no JetBrains-specific hook runtime specification was retrieved, and no dedicated IntelliJ plugin is documented for Codex, Grok Build, or Antigravity (Open Source AI Coding Tools 2026, Agentic Coding Tools, Best AI Coding Agents).
3. Codex desktop plugin hooks are confirmed solely at a high level for manually installed plugins without an enumerated desktop event table (OpenAI Plugins Documentation).
4. Among other top-10 agents, Cursor exposes camelCase hooks (workspaceOpen, preToolUse, beforeShellExecution, afterFileEdit) and OpenCode exposes TypeScript plugin hooks (execute.before / tool.execute.before), whereas Cline (and archived Roo Code), Devin Desktop (formerly Windsurf), and Kilo Code are documented as rules-file/checkpoint tools without transparent pre-tool hook rewriting, and Goose, Aider, OpenHands, and Kiro have no client lifecycle hook API documented in retrieved sources (RTK Supported Agents Matrix, 10 Best AI Coding Agents).

## ChaosEngine Harness Architecture, Entry Points, and Implemented Hooks

ChaosEngine operates as a standalone, provider-neutral working contract covering coding and non-coding SDLC roles (developers, testers, product owners, and scrum masters) via a fixed workflow: research first, plan, implement, verify with evidence, obtain at least one fresh-context adversarial review, and record learned findings (ShaftHQ/chaosengine-harness, SHAFT_ENGINE #8051, SHAFT_ENGINE #8059). To avoid vendor lock-in and context bloat, the repository enforces an always-loaded-budget.json cap on baseline rules while placing specialized procedures into on-demand skills indexed by harness-index.json.

### ChaosEngine Entry Points and Runtime Surfaces

ChaosEngine distributes execution across four distinct entry-point layers that connect local shells, agent runtimes, and CI pipelines:

- Bootstrap & Lifecycle Management Layer: install.sh, install.ps1, install.py, and bootstrap.py manage commit-pinned deployments (--version <40-hex> with SHA-256 verification), configuration drift detection (verify, status --project . --json, and doctor), managed runtime provisioning (dependencies.json, which upgraded managed CPython from 3.10.20 to 3.11.15 so hooks/reflection.py can import datetime.UTC), and safe uninstallation that preserves user-modified files (ShaftHQ/chaosengine-harness, SHAFT_ENGINE #5354).
- CLI & Evaluation Layer: chaosengine_harness.py, tool.py, dod.py, and executables under bin/ provide mechanical commands outside the model's hook loop, including tool.py pre-done (and proposed tool.py done / dod.py gate wrappers), tool.py usage for privacy-scrubbed session receipts, and evals/parity-fixtures.json (references/eval-parity-fixtures.md) for simulating identical hook policy outcomes across host schemas without spawning live agent binaries (SHAFT_ENGINE #8051, SHAFT_ENGINE #8048).
- Agent-Context Layer: AGENTS.md defines the canonical harness contract, CLAUDE.md acts as a thin import pointer to AGENTS.md, GEMINI.md embeds the ChaosEngine host block, and skills/chaos-engine/SKILL.md provides the primary operational entry point loaded by agents (SHAFT_ENGINE #8062, SHAFT_ENGINE #6178).
- Enforcement & Guard Layer: hooks/guard.py reads hook_event_name JSON payloads from stdin on hooked hosts, hooks/reflection.py acts as the canonical portable reflection reducer (with scripts/agents/reflection.py serving as a thin CLI adapter), secret_guard.py scans for exposed secrets, and overlay_pre_push.py plus scripts/ci/harness_pr_gate.py enforce push-time and PR-time compliance when hookless bots or instruction-only agents bypass PreToolUse (SHAFT_ENGINE #5000, SHAFT_ENGINE #8051).

### ChaosEngine Repository Hook Implementation Audit

Cross-referencing ShaftHQ/chaosengine-harness against SHAFT_ENGINE tracking issues (#5000, #5354, #6178, #7860, #8032, #8051, #8060, #8062) and release logs establishes which hooks and host generators exist today versus which remain specifications or documented gaps. Note that hosts.py is documented under chaos-engine/hosts.py in SHAFT_ENGINE and referenced in standalone issue SHAFT_ENGINE #8058.

_Table cells below are taken from the HTML/innerText capture of the same report, because the PDF export clips long table cells with "…". Row and column content otherwise matches the PDF table._

| ChaosEngine Component or Host Target | Hook Events / Triggers Covered | Verified Behavior and Guard Logic | Implementation Status and Source Evidence |
|---|---|---|---|
| hooks/guard.py | UserPromptSubmit, PreToolUse, PostToolUse, Stop | Returns additionalContext on UserPromptSubmit/PostToolUse; blocks secrets, commit-identity mismatches (commit-identity.md), PR scope violations (pr-scope-check.md), ghost cwd (#7528), and gh pr create; enforces retrieve justification and reflection in _stop_block_reason | Implemented and probe-tested (#5354, #7860, #8051); open-PR WIP cap on gh pr create/ready/reopen specified in #8032 R1 |
| hooks/reflection.py | Triggered via PostToolUse / Stop reflection pipeline | Canonical portable reducer using CPython 3.11+ (datetime.UTC), HMAC/session-token receipt boundary, exact failure disposition, and elapsed-time validation | Implemented (#5000, #5354); tracks Claude PostToolUseFailure vs. Codex PostToolUse normalization |
| secret_guard.py, overlay_pre_push.py, harness_pr_gate.py | PreToolUse / Git pre-push / GitHub Actions PR gate | Secret detection (secret_guard.py), pre-push contract validation (overlay_pre_push.py), and CI enforcement for agentic PRs (scripts/ci/harness_pr_gate.py) | Implemented / active in mechanical-gate spec (#8051, #8062) |
| Claude Code (CLAUDE.md, agent-plugins/chaos-engine) | UserPromptSubmit, PreToolUse, PostToolUse, PostToolUseFailure, Stop | Executes guard.py across Claude CLI and Claude Desktop Code tab; #7860 fixed infinite Stop looping by checking stop_hook_active before session_retrieve_gap; #7390 added SubagentStart locator injection in SHAFT_ENGINE | Implemented (#5000, #7860); standalone SubagentStart wiring in chaosengine-harness unverified |
| OpenAI Codex (.codex/hooks.json, hosts.py) | PreToolUse, PostToolUse | Project .codex/hooks.json invokes .chaos-engine/hooks/guard.py; #5000 confirmed Codex runtime lacks PostToolUseFailure | Implemented for tool hooks (#5000); Codex SessionStart, UserPromptSubmit, and Stop not confirmed wired |
| Grok Build (.grok/hooks/lifecycle.json, hosts.py) | 8 lifecycle events (lifecycle.json) | Installer/generator provisions .grok/hooks/lifecycle.json using CPython 3.11.15 with original matchers and timeouts; requires /hooks reload in Grok | Implemented (#5354); lags Grok Build's 14-event spec (docs.x.ai); only 3 events explicitly probed in #5354 |
| Gemini CLI (GEMINI.md) | None wired (GEMINI.md block only) | #6178 confirms GEMINI.md carries only the CE instruction block; no .gemini/settings.json hook configuration verified | Instruction-only (#6178); 11 native hooks unmapped |
| Google Antigravity (agy / App / IDE) | Not listed in README supported clients | Inherits AGENTS.md and GEMINI.md natively if placed in workspace; no .agents/hooks.json or ~/.gemini/config/hooks.json generator documented | Gap / Not supported in README or hosts.py |
| GitHub Copilot (CLI / VS Code / Cloud) | Listed in README; hook config unverified | Listed as supported client in README and targeted by shaft-mcp docs, but no .github/hooks/*.json generator confirmed in retrieved ChaosEngine issues | Unverified / Partial (README client without confirmed hook emitter) |
| Cursor and OpenCode | None (AGENTS.md native load only) | Tracked explicitly in #6178 and #8051 as instruction-only hosts absent from hosts.py (GAP-CURSOR-HOOKS, GAP-OPENCODE-HOOKS) | Documented Gap (#6178, #8051) |
| Grok Bot and Hookless Bots | None (CLI tool.py pre-done and CI gate) | Explicitly documented as skipping PreToolUse; relies on tool.py pre-done, dod.py, overlay_pre_push.py, and CI PR gates | Hookless by host design; mitigated via CI/CLI (#8051) |

## Hook and Entry-Point Specifications Across Target Agents

### Claude Code across CLI, Desktop, IDE, and Web

Claude Code defines the largest lifecycle surface in the ecosystem and runs from the claude terminal CLI (including -p headless mode, --init-only, --init, --maintenance, --worktree, /hooks, /add-dir, and /loop), the Claude Desktop app's Code tab, VS Code and JetBrains extensions, and the web interface (Claude Code Hooks Reference, SHAFT_ENGINE #7860). Project and user context enters through CLAUDE.md (which may import AGENTS.md), .claude/rules/*.md, auto memory in ~/.claude/projects/.../memory/, and .mcp.json (Claude Code Hooks Guide). Hook definitions live in JSON across ~/.claude/settings.json, .claude/settings.json, .claude/settings.local.json, enterprise managed settings (allowedHttpHookUrls, httpHookAllowedEnvVars), and plugin bundles.

Official documentation enumerates 33 lifecycle events: SessionStart, Setup, UserPromptSubmit, UserPromptExpansion, PreToolUse, PermissionRequest, PermissionDenied, PostToolUse, PostToolUseFailure, PostToolBatch, Notification, MessageDisplay, SubagentStart, SubagentStop, TaskCreated, TaskCompleted, Stop, StopFailure, TeammateIdle, InstructionsLoaded, ConfigChange, CwdChanged, DirectoryAdded, FileChanged, WorktreeCreate, WorktreeRemove, PreCompact, PostCompact, PreModelSwitch, PostModelSwitch, Elicitation, ElicitationResult, and SessionEnd (Claude Code Hooks Reference). Official docs detail command and HTTP handlers plus in-process JavaScript function "mods" (capable of drawing custom UI), while a third-party developer guide additionally notes prompt and agent handler types (Codex CLI Hooks Breakdown). Claude Desktop's Code tab executes the same local .claude/settings.json hook pipeline as the CLI, as demonstrated by SHAFT_ENGINE #7860.

### OpenAI Codex across CLI, Desktop App, IDE, and Cloud

OpenAI Codex operates through the Apache-2.0 Rust codex CLI, codex app (desktop app), IDE extensions, ChatGPT web/mobile, and Codex Cloud. Its primary instruction entry point is AGENTS.md, paired with config.toml and enterprise requirements.toml (where allow_managed_hooks_only = true restricts execution exclusively to administrator-managed hooks) (OpenAI Config Reference, Codex CLI Hooks Reference). CLI hooks register in ~/.codex/hooks.json and repo-level .codex/hooks.json, though OpenAI documentation notes that Codex can also discover standalone hooks.json files without sibling config.toml or requirements.toml (OpenAI Hooks Discovery). Non-managed hooks are blocked until explicitly approved by the user against a cryptographic hash of the definition via /hooks (or bypassed for one invocation with --dangerously-bypass-hook-trust), and builds prior to 0.145 required [features].codex_hooks = true (Codex CLI Hooks Reference).

Community engineering guides document 5 lifecycle events in Codex CLI:

- SessionStart (matches startup or resume and injects stdout as developer context; exit 2 does not gate)
- UserPromptSubmit (added in PR #14626 on March 18, 2026; exit 2 rejects prompts)
- PreToolUse (added alongside PostToolUse around v0.117.0; intercepts local shell, unified exec, apply_patch, and MCP calls via exit 2 or permissionDecision values allow/deny/ask, though updatedInput argument rewriting failed on tested builds)
- PostToolUse (exit 2 replaces tool output with stderr)
- Stop (requires valid JSON on exit 0; decision: "block" triggers continuation) (Codex CLI Hooks Breakdown, Codex Agentic Loop)

Codex hooks do not execute for hosted cloud tools, and SHAFT_ENGINE #5000 confirmed from Codex binary strings that PostToolUseFailure is absent. For the desktop surface, OpenAI Plugins Documentation states that lifecycle hooks apply specifically to manually installed Codex desktop plugins only, without exposing a full desktop-specific event catalog in the retrieved excerpt.

### Grok Build CLI and Grok Bot

SpaceXAI's open-source terminal agent, Grok Build (xai-org/grok-build, Apache-2.0 since July 14, 2026), provides three core runtimes—an interactive TUI (grok), headless CLI (grok -p with --output-format streaming-json), and Agent Client Protocol (grok agent stdio)—alongside worktrees (grok -w), grok inspect, grok import / /import-claude, /personas, /hooks, and /hooks-trust (SpaceXAI Grok Build Hooks, Grok Build Overview). (An earlier community project, superagent-ai/grok-cli, used ~/.grok/user-settings, distinct from official Grok Build paths.) Grok Build loads AGENTS.md, CLAUDE.md, .grok/skills, .grok/agents/, ~/.grok/hooks/*.json, .grok/hooks/*.json, and—for migration compatibility—.claude/settings.json and .cursor/hooks.json (including Cursor's camelCase names). Project hooks require folder trust saved in ~/.grok/trusted_folders.toml (granted interactively or via --trust). SpaceXAI Grok Build Hooks (updated July 2, 2026) specifies 14 lifecycle events: SessionStart, SessionEnd, UserPromptSubmit, PreToolUse, PostToolUse, PostToolUseFailure, PermissionDenied, Stop, StopFailure, Notification, SubagentStart, SubagentStop, PreCompact, and PostCompact. Handlers support "command" and "http" (default timeout 5 seconds) and receive GROK_HOOK_EVENT, GROK_HOOK_NAME, GROK_SESSION_ID, and GROK_WORKSPACE_ROOT. Crucially, PreToolUse is documented as the only blocking event ({"decision": "deny", "reason": "..."} or exit code 2); crashes, timeouts, and malformed outputs fail open, and passive events ignore stdout and cannot inject model context. By contrast, Grok Bot (listed in ChaosEngine's supported clients and supercompress-proxy's hosted MCP ecosystem) is a hookless bot without local PreToolUse execution, forcing reliance on tool.py pre-done, pre-push checks, and CI PR gates (SHAFT_ENGINE #8051).

### Google Antigravity and Gemini CLI

Following Google's June 18, 2026 transition moving free individual and Google AI Pro/Ultra plans to closed-source Antigravity (agy CLI, Antigravity 2.0 desktop App with Manager/Editor/Playground views, Antigravity IDE, and the Python SDK) while retaining Apache-2.0 Gemini CLI for API-key and Google Cloud users, the two Google platforms use incompatible hook schemas despite sharing ~/.gemini/ paths.

Antigravity discovers AGENTS.md, GEMINI.md, .agents/rules/*.md (24,000-byte limit per file; flat scan unless registered in .agents/rules.json), and ~/.gemini/config/rules/*.md, while .agent/workflows/ is deprecated in favor of Agent Skills (Google Antigravity Rules, Google Antigravity Workflows). Hooks live in workspace .agents/hooks.json, global ~/.gemini/config/hooks.json (~/.gemini/antigravity-cli/settings.json is explicitly ignored), or plugin hooks.json files (Google Antigravity Hooks). NeuralTrust Antigravity Integration notes that Antigravity lacks a system-level hooks path and that some builds ignore workspace hook files in favor of ~/.gemini/config/hooks.json. Official Antigravity documentation supports only "command" handlers (default timeout 30 seconds) across 6 JSON events: SessionStart, PreToolUse, PostToolUse, PreInvocation (before model API calls), PostInvocation (after model API calls), and Stop. Unlike PreToolUse and PostToolUse, PreInvocation, PostInvocation, and Stop accept no matcher and must map directly to handler arrays—nesting them inside a "hooks": [...] object causes the IDE Language Server parser to crash and discard the file (Google AI Forum Antigravity Hooks). Antigravity also lacks any JSON hook able to block a user prompt prior to model ingestion. Built-in tool names matchable in Antigravity include view_file, write_to_file, replace_file_content, run_command, manage_task, schedule, list_permissions, ask_permission, invoke_subagent, define_subagent, send_message, and manage_subagents.

Programmatic agents built on Antigravity Python SDK Hooks replace JSON shell hooks with three typed Python hook categories across 5 hook classes:
- Inspect hooks (read-only, non-blocking): PostToolCallHook
- Decide hooks (blocking with optional modified_args): PreToolCallDecideHook and PreTurnHook
- Transform hooks (modifying, fail-closed): OnToolErrorHook (which surfaces RuntimeError across LocalConnection and can replace stacktraces with custom error strings) and OnInteractionHook

Separately, open-source Gemini CLI configures hooks under hooks.* in .gemini/settings.json / ~/.gemini/settings.json alongside GEMINI.md (Gemini CLI Configuration); gemini-cli-hooks targeting Gemini CLI v0.38.2 (April 2026) documents 11 events: SessionStart, SessionEnd, BeforeAgent, AfterAgent, BeforeModel, AfterModel, BeforeToolSelection, BeforeTool, AfterTool, PreCompress, and Notification (a separate community blog refers to "roughly 12" events enabled by default since v0.26.0).

### GitHub Copilot across CLI, VS Code Desktop App, Cloud Agent, and SDK

GitHub Copilot spans copilot CLI, VS Code and the GitHub Copilot Desktop app, IDE extensions, Copilot Cloud Agent (running in GitHub Actions via .github/workflows/copilot-setup-steps.yml), and github/copilot-sdk. VS Code, the Copilot app, and Copilot CLI share a unified Copilot harness that discovers .github/hooks/*.json, ~/.copilot/hooks/*.json ($COPILOT_HOME/hooks/), .github/copilot/settings.json, .github/copilot/settings.local.json, ~/.copilot/settings.json, and compatibility configs in .claude/settings.json, .claude/settings.local.json, and ~/.claude/settings.json (while ignoring ~/.copilot/config.json for hooks and deprecating VS Code's legacy Local harness) (VS Code Copilot Hooks, GitHub Copilot CLI Use Hooks). Copilot CLI additionally supports hooks event maps in custom agent YAML frontmatter (supporting command or http handlers active only while that agent is selected) and CLI-only prompt hooks restricted to sessionStart (GitHub Copilot Hooks Reference).

Event naming splits across Copilot surfaces:

- VS Code / Copilot Desktop: VS Code Customizations Hooks defines 8 PascalCase events: SessionStart, UserPromptSubmit, PreToolUse (precedence deny -> ask -> allow, supporting updatedInput and additionalContext), PostToolUse, PreCompact, SubagentStart, SubagentStop, and Stop. Blocking in Copilot Stop triggers an additional turn that consumes an extra Copilot premium request (Zenn GitHub Copilot Hooks).
- Copilot CLI: Uses camelCase (sessionStart, sessionEnd, userPromptSubmitted, preToolUse, postToolUse, agentStop, and subagentStop, with agentStop/subagentStop added in v0.0.401) (Copilot CLI Issue #1730, GitHub Copilot Hooks Concepts). Declaring both PreToolUse and preToolUse simultaneously in CLI setups fires hooks twice (RTK Supported Agents Matrix), and open GitHub issues document sessionStart failing to fire in .github/hooks/ or nested monorepo directories (Copilot CLI Issue #1730) and plugin hooks.json silently skipping execution (Copilot CLI Issue #2540).
- Copilot Cloud Agent & SDK: Cloud Agent runs a subset of .github/hooks/*.json starting with sessionStart, while GitHub Copilot SDK Hooks Overview (Node.js/TypeScript, Go, .NET, Java) exposes programmatic onPreToolUse, onPostToolUse (success only), onSessionStart, and documented User Prompt Submitted and User Prompt Transformed hooks alongside skipPermission: true for trusted custom tools (Copilot SDK Pre-Tool Use). Enterprise-managed Copilot policies disable Claude and Codex harnesses unless explicitly permitted by IT.

### IntelliJ IDEA and JetBrains Plugins

Retrieved 2026 documentation confirms JetBrains / IntelliJ IDEA extensions for Claude Code, GitHub Copilot, Continue (36k stars), Kilo Code, Amazon Q Developer, JetBrains Junie, and SHAFT (shaft-intellij), while showing no documented IntelliJ IDEA plugins for OpenAI Codex, Grok Build, or Google Antigravity (Open Source AI Coding Tools 2026, Agentic Coding Tools, Best AI Coding Agents, ShaftHQ/SHAFT_ENGINE). Claude Code's JetBrains plugin integrates with Anthropic's coding-agent runtime alongside terminal, VS Code, and desktop app deployments (CLAUDE.md / AGENTS.md). GitHub Copilot, Amazon Q Developer, Continue, Kilo Code, and Junie operate across JetBrains IDEs (with shaft-intellij providing SHAFT Engine support alongside SHAFT MCP Docs). However, no primary JetBrains-specific lifecycle hook API documentation was retrieved for any of these plugins—VS Code Copilot Hooks explicitly scopes its reference to VS Code, the Copilot app, Copilot CLI, and Cloud Agent. Consequently, whether JetBrains IDE plugins execute local .claude/settings.json or .github/hooks/*.json hooks identically to CLI and VS Code hosts remains unverified in the available evidence.

### Other Top-10 and Prominent Coding Agents

Evaluating the remaining top-10 coding agents from 2026 rankings and developer surveys—Cursor, Devin Desktop (formerly Windsurf), OpenCode, Cline (whose fork Roo Code was archived in May 2026), Kiro, OpenHands, Goose, and Aider—alongside other hook-capable harnesses tracked by RTK Supported Agents Matrix highlights two contrasting integration tiers:

- Runtime-Hooked Tools:
  - Cursor (editor, Cloud Agents, and Cursor CLI) configures camelCase command hooks in .cursor/hooks.json alongside .cursor/permissions.json and AGENTS.md. Retrieved bug reports and adapter documentation confirm four Cursor events: workspaceOpen (returns pluginPaths to auto-load plugins, though affected by a startup reload race in Cursor Forum #172939), preToolUse, beforeShellExecution, and afterFileEdit.
  - OpenCode (anomalyco/opencode, 222k GitHub stars reported in October 2026) bypasses declarative shell JSON in favor of TypeScript plugins (~/.config/opencode/plugins/*.ts) exporting execute.before (2.0) and tool.execute.before (1.x >= 1.18.29) alongside AGENTS.md (/init).
  - Pi / Oh My Pi (tool_call TypeScript extension event), OpenClaw (before_tool_call TypeScript plugin), Hermes (Python terminal command mutation plugins), Trae (PreToolUse with RunCommand matcher), Factory Droid (PreToolUse with Execute matcher), and Mistral Vibe (pre_tool) expose programmatic or declarative pre-tool interception.
- Rules-File / Container / Checkpoint Tools:
  - Cline (71k stars, VS Code/CLI/SDK), Devin Desktop / Windsurf, and Kilo Code operate at the prompt/rules-file layer (N/A for transparent pre-tool hook rewriting in RTK's adapter matrix) and rely on interactive UI approval checkpoints rather than user-configured lifecycle hook scripts.
  - Goose (56k stars, Block / Linux Foundation Agentic AI Foundation), Aider (50k stars), OpenHands (92k stars), and Kiro rely on MCP integrations, repeatable recipes, git-commit loops, or Docker sandboxes, with no client lifecycle hook API documented in retrieved sources.

**Client Entry-Point and Contract Comparison Table**

_Table cells below are taken from the HTML/innerText capture of the same report, because the PDF export clips long table cells with "…". Row and column content otherwise matches the PDF table._

| Agent / Tool | Surfaces Covered | Entry / Instruction Files | Hook Config Locations | Handler Types | Blocking & Failure Contract |
|---|---|---|---|---|---|
| Claude Code | CLI (claude), Desktop, VS Code, JetBrains, Web | CLAUDE.md, AGENTS.md, .claude/rules/*.md, SKILL.md | ~/.claude/settings.json, .claude/settings.json, .claude/settings.local.json, managed settings, plugins | command, http, prompt, agent, JS mods | 33 events; exit 2 or JSON permissionDecision blocks across tool, permission, prompt expansion, model switch, and worktree hooks |
| OpenAI Codex | CLI (codex), Desktop (codex app), IDE, Cloud | AGENTS.md, config.toml, requirements.toml | ~/.codex/hooks.json, .codex/hooks.json; manual desktop plugins only | command (CLI); desktop plugin hooks | 5 CLI events (no PostToolUseFailure); hash-based trust approval; PreToolUse updatedInput rejected in tested builds; no cloud tool hooks |
| Grok Build | CLI (grok), TUI, Headless -p, ACP (grok agent stdio) | AGENTS.md, CLAUDE.md, .grok/skills, .grok/agents/ | ~/.grok/hooks/*.json, .grok/hooks/*.json, plus .claude/settings.json & .cursor/hooks.json | command, http (default 5s) | 14 events; PreToolUse is the only blocker (deny / exit 2); timeouts/crashes fail open; passive hooks ignore stdout; trust in trusted_folders.toml |
| Grok Bot | Hosted bot / MCP proxy | Repo AGENTS.md, PR templates | None (hookless bot) | N/A | Skips PreToolUse; enforced solely via CLI tool.py pre-done, pre-push, and CI PR gates (harness_pr_gate.py) |
| Google Antigravity | CLI (agy), App 2.0, IDE, Python SDK | AGENTS.md, GEMINI.md, .agents/rules/*.md (24 KB limit) | ~/.gemini/config/hooks.json, .agents/hooks.json, plugin hooks.json (no system hooks); SDK hook classes | command (default 30s); Python SDK Inspect/Decide/Transform | 6 JSON events (PreInvocation/PostInvocation/Stop omit matcher); no pre-model prompt block; SDK OnToolErrorHook fail-closed |
| Gemini CLI | CLI (gemini) | GEMINI.md | .gemini/settings.json, ~/.gemini/settings.json | command | 11 Before*/After* events (v0.38.2), including BeforeModel, AfterModel, and BeforeToolSelection |
| GitHub Copilot | CLI (copilot), VS Code / Desktop App, Cloud Agent, SDK | .github/copilot-instructions.md, ~/.copilot/copilot-instructions.md, custom agent frontmatter | .github/hooks/*.json, ~/.copilot/hooks/*.json, .github/copilot/settings*.json, .claude/settings*.json | command (bash/powershell), http (frontmatter), prompt (CLI sessionStart), SDK callbacks | VS Code 8 PascalCase vs. CLI 7 camelCase events; PreToolUse (deny/ask/allow + updatedInput); blocking Stop consumes an extra premium request |
| Cursor | Editor, Cursor CLI, Cloud Agents | AGENTS.md, .cursor/permissions.json, .cursor/mcp.json | .cursor/hooks.json | command | camelCase events (workspaceOpen, preToolUse, beforeShellExecution, afterFileEdit); #172939 workspaceOpen startup race |
| OpenCode | TUI, Desktop (beta), IDE extension | AGENTS.md (/init) | ~/.config/opencode/plugins/*.ts | TypeScript plugin functions | In-place argument mutation via execute.before (2.0) and tool.execute.before (>= 1.18.29) |
| Cline / Devin / Kilo / Goose / Aider / OpenHands / Kiro | IDE extensions, CLIs, Docker/Cloud | Rules files, AGENTS.md, Recipes, mcpServers | None verified (rules-file or MCP extension only) | N/A | UI checkpoints or container sandboxes; no client hook script runtime verified |

## Cross-Client Hook Parity Matrix and Unique Events

Normalizing every documented client hook into 39 canonical lifecycle capabilities reveals a sharp concentration of cross-vendor parity around tool interception, session bookends, and turn completion:

- 11 canonical events achieve broad parity across three or more client families: PreToolUse, PostToolUse, PostToolUseFailure (two CLI JSON specs plus Antigravity's SDK OnToolErrorHook), SessionStart, SessionEnd, UserPromptSubmit, Stop, SubagentStart, SubagentStop, PreCompact, and Notification.
- 5 additional capabilities sit in strict two-client parity islands: PermissionDenied, StopFailure, and PostCompact exist solely in Claude Code and Grok Build, while model-call boundary hooks (PreInvocation/BeforeModel and PostInvocation/AfterModel) exist exclusively in Google's Antigravity and Gemini CLI.
- 23 canonical lifecycle capabilities are unique to a single client or SDK in the retrieved specifications. Claude Code accounts for 19 unique events, while Cursor (workspaceOpen), Gemini CLI (BeforeToolSelection), Copilot SDK (User Prompt Transformed), and Antigravity Python SDK (OnInteractionHook) each contribute one unique hook capability.
- ChaosEngine Coverage: ChaosEngine implements 4 core hooks directly in hooks/guard.py (UserPromptSubmit, PreToolUse, PostToolUse, Stop) and maintains partial coverage on 2 (PostToolUseFailure parity tracking in SHAFT_ENGINE #5000 and SHAFT_ENGINE SubagentStart #7390), yielding 13% raw breadth across the full 39-event ecosystem despite complete 4-of-4 coverage on the core behavioral guard loop for its actively wired CLI hosts.

_Table cells below are taken from the HTML/innerText capture of the same report, because the PDF export clips long table cells with "…". Row and column content otherwise matches the PDF table._

| Canonical Lifecycle Capability | Parity Class | Claude Code (33) | Codex CLI (5) | Grok Build (14) | Antigravity CLI / SDK (6 / 5) | Gemini CLI (11) | Copilot VS Code / CLI / SDK | Cursor / OpenCode / Other Hooked | ChaosEngine Status |
|---|---|---|---|---|---|---|---|---|---|
| One-Time Repo Setup | UNIQUE (Claude) | Setup | — | — | — | — | — | — | Gap (uses install.py doctor) |
| Workspace Open | UNIQUE (Cursor) | — | — | — | — | — | — | Cursor: workspaceOpen | Gap (GAP-CURSOR-HOOKS) |
| Session Start | Broad (6 families) | SessionStart | SessionStart | SessionStart | SessionStart | SessionStart | SessionStart / sessionStart / onSessionStart | — | Gap / Unverified (.grok/hooks/lifecycle.json has 8 events in #5354; non-probed names unexposed) |
| Session End | Broad (4 families) | SessionEnd | — | SessionEnd | — | SessionEnd | CLI: sessionEnd | — | Gap / Unverified (tool.py usage tracks receipts manually #8032) |
| User Prompt Submit / Pre-Turn | Broad (5 families + SDK) | UserPromptSubmit | UserPromptSubmit | UserPromptSubmit | SDK: PreTurnHook (none in JSON) | BeforeAgent | UserPromptSubmit / userPromptSubmitted / SDK | — | Implemented (guard.py #5354; Codex/Copilot/Gemini unwired) |
| Slash-Command Expansion | UNIQUE (Claude) | UserPromptExpansion | — | — | — | — | — | — | Gap |
| Prompt Replacement (SDK) | UNIQUE (Copilot SDK) | — | — | — | — | — | SDK: User Prompt Transformed | — | Gap |
| Before Model Call | 2-Client (Google) | — | — | — | PreInvocation | BeforeModel | — | — | Gap |
| After Model Call | 2-Client (Google) | — | — | — | PostInvocation | AfterModel | — | — | Gap |
| Before Tool Selection | UNIQUE (Gemini CLI) | — | — | — | — | BeforeToolSelection | — | — | Gap |
| Pre-Model Switch | UNIQUE (Claude) | PreModelSwitch | — | — | — | — | — | — | Gap |
| Post-Model Switch | UNIQUE (Claude) | PostModelSwitch | — | — | — | — | — | — | Gap |
| Pre-Tool Execution / Gate | Broad (Universal Hooked) | PreToolUse | PreToolUse | PreToolUse (sole blocker) | PreToolUse / SDK PreToolCallDecideHook | BeforeTool | PreToolUse / preToolUse / onPreToolUse | Cursor preToolUse + beforeShellExecution; OpenCode execute.before; Pi tool_call; OpenClaw before_tool_call; Trae/Droid PreToolUse; Vibe pre_tool | Implemented (guard.py, secret_guard.py; wired on Claude, Codex #5000, Grok #5354; gaps on Cursor/OpenCode/Gemini/Antigravity/Copilot) |
| Permission Request | UNIQUE (Claude) | PermissionRequest | — | — | — | — | — | — | Gap |
| Permission Denied | 2-Client (Claude+Grok) | PermissionDenied | — | PermissionDenied | — | — | — | — | Gap |
| Post-Tool Completion | Broad (6 families + Cursor) | PostToolUse | PostToolUse | PostToolUse | PostToolUse / SDK PostToolCallHook | AfterTool | PostToolUse / postToolUse / onPostToolUse | Cursor: afterFileEdit (edits only) | Implemented (guard.py, reflection.py on Claude, Codex #5000, Grok #5354) |
| Post-Tool Failure / Error | Broad (3-surface: 2 JSON + SDK) | PostToolUseFailure | Missing (#5000) | PostToolUseFailure | SDK: OnToolErrorHook | — | — | — | Partial (#5000 tracks Claude vs. Codex normalization in reflection.py) |
| Post-Tool Parallel Batch | UNIQUE (Claude) | PostToolBatch | — | — | — | — | — | — | Gap |
| Agent Turn Stop | Broad (6 families) | Stop | Stop | Stop | Stop | AfterAgent | Stop (extra request on block) / agentStop | — | Implemented (_stop_block_reason in guard.py; #7860 fixed loop in Claude Desktop) |
| Turn API Error Stop | 2-Client (Claude+Grok) | StopFailure | — | StopFailure | — | — | — | — | Gap |
| Subagent Start | Broad (3 families) | SubagentStart | — | SubagentStart | — | — | VS Code: SubagentStart | — | Partial (SHAFT #7390 locator injection; standalone parity unverified) |
| Subagent Stop | Broad (3 families) | SubagentStop | — | SubagentStop | — | — | VS Code SubagentStop / CLI subagentStop | — | Gap |
| Task Created | UNIQUE (Claude) | TaskCreated | — | — | — | — | — | — | Gap |
| Task Completed | UNIQUE (Claude) | TaskCompleted | — | — | — | — | — | — | Gap (uses tool.py pre-done / dod.py) |
| Teammate Idle | UNIQUE (Claude) | TeammateIdle | — | — | — | — | — | — | Gap |
| Pre-Compaction | Broad (4 families) | PreCompact | — | PreCompact | — | PreCompress | VS Code: PreCompact | — | Gap |
| Post-Compaction | 2-Client (Claude+Grok) | PostCompact | — | PostCompact | — | — | — | — | Gap |
| Notification | Broad (3 families) | Notification | — | Notification | — | Notification | — | — | Gap |
| Message Display | UNIQUE (Claude) | MessageDisplay (+ JS mods) | — | — | — | — | — | — | Gap |
| Interaction Transform (SDK) | UNIQUE (Antigravity SDK) | — | — | — | SDK: OnInteractionHook | — | — | — | Gap |
| Instructions Loaded | UNIQUE (Claude) | InstructionsLoaded | — | — | — | — | — | — | Gap |
| Config Change | UNIQUE (Claude) | ConfigChange | — | — | — | — | — | — | Gap |
| Working Dir Changed | UNIQUE (Claude) | CwdChanged | — | — | — | — | — | — | Gap (ghost cwd blocked in PreToolUse #7528) |
| Directory Added | UNIQUE (Claude) | DirectoryAdded | — | — | — | — | — | — | Gap |
| Watched File Changed | UNIQUE (Claude) | FileChanged | — | — | — | — | — | — | Gap |
| Git Worktree Create | UNIQUE (Claude) | WorktreeCreate | — | — | — | — | — | — | Gap |
| Git Worktree Remove | UNIQUE (Claude) | WorktreeRemove | — | — | — | — | — | — | Gap |
| MCP Elicitation Request | UNIQUE (Claude) | Elicitation | — | — | — | — | — | — | Gap |
| MCP Elicitation Result | UNIQUE (Claude) | ElicitationResult | — | — | — | — | — | — | Gap |

## Gap Mapping and Remediation Roadmap for ChaosEngine

Mapping ChaosEngine's current implementation in ShaftHQ/chaosengine-harness against this cross-client contract surfaces concrete engineering hazards and integration gaps:

1. GAP-CURSOR-HOOKS and GAP-OPENCODE-HOOKS (SHAFT_ENGINE #8051, SHAFT_ENGINE #6178), alongside absent hook generators for Gemini CLI, Antigravity, and GitHub Copilot, allow those hosts to bypass hooks/guard.py at tool-call time even though every one of those five runtimes supports pre-tool interception natively.
2. .grok/hooks/lifecycle.json (SHAFT_ENGINE #5354) covers 8 events versus 14 in SpaceXAI Grok Build Hooks, and because Grok fails open on crashes/timeouts while discarding stdout on passive events, ChaosEngine cannot depend on Grok UserPromptSubmit or Stop hooks for context injection or blocking.
3. Codex CLI's lack of PostToolUseFailure (SHAFT_ENGINE #5000) forces hooks/reflection.py to derive tool failures from PostToolUse output payloads, while .codex/hooks.json still omits Codex's SessionStart, UserPromptSubmit, and Stop hooks and Codex desktop plugin hooks remain isolated to manual plugins.
4. Any future GitHub Copilot hook adapter must emit a single consistent casing to avoid double execution in CLI (Copilot CLI Issue #1730 and Copilot CLI Issue #2540 notwithstanding) and avoid unbounded Stop blocking due to premium-request billing per continuation turn.
5. For hookless bots (Grok Bot), rules-only agents (Cline, Devin Desktop, Kilo Code), and unverified IntelliJ plugins, ChaosEngine's architecture appropriately shifts enforcement from PreToolUse to tool.py pre-done, dod.py, overlay_pre_push.py, and scripts/ci/harness_pr_gate.py.

Recommended Implementation

_Table cells below are taken from the HTML/innerText capture of the same report, because the PDF export clips long table cells with "…". Row and column content otherwise matches the PDF table._

| ChaosEngine Gap ID | Affected Clients | Root Cause / Technical Constraint | Current ChaosEngine Mitigation | Recommended Implementation Target |
|---|---|---|---|---|
| GAP-HOOK-INVENTORY | All | Public repo inspection confirms guard.py, reflection.py, secret_guard.py, overlay_pre_push.py; remainder of hooks/ and plugin-adapters/ unexposed | Simulated parity tests in evals/parity-fixtures.json | Inventory local hooks/ and plugin-adapters/ files directly |
| GAP-CURSOR-HOOKS | Cursor (IDE + CLI) | hosts.py omits .cursor/hooks.json; Cursor workspaceOpen has startup reload race (#172939) | Native AGENTS.md + tool.py pre-done / CI | Emit .cursor/hooks.json mapping preToolUse to guard.py |
| GAP-OPENCODE-HOOKS | OpenCode | Requires TypeScript plugins (execute.before / tool.execute.before), not JSON hooks | Native AGENTS.md + tool.py pre-done / CI | Add TS adapter in plugin-adapters/ shelling out to guard.py |
| GAP-GEMINI-HOOKS | Gemini CLI | GEMINI.md carries CE block only (#6178); needs .gemini/settings.json BeforeTool/AfterTool | GEMINI.md rules only | Generate .gemini/settings.json normalizing BeforeTool -> PreToolUse |
| GAP-ANTIGRAVITY-HOOKS | Google Antigravity | Not in README clients; uses ~/.gemini/config/hooks.json/.agents/hooks.json; flat arrays for Stop/PreInvocation/PostInvocation; no prompt blocker | Passive AGENTS.md / GEMINI.md discovery | Add hosts.py target emitting flat-array Stop + PreToolUse/PostToolUse |
| GAP-COPILOT-HOOKS | GitHub Copilot | Listed in README, but no .github/hooks/*.json emitter verified; CLI camelCase vs. VS Code PascalCase collision; Stop billing; #1730/#2540 | VS Code Copilot reads .claude/settings.json automatically | Emit single-cased .github/hooks/chaosengine.json normalizing sessionId/toolName |
| GAP-CODEX-EXPANSION | OpenAI Codex | .codex/hooks.json covers PreToolUse/PostToolUse; lacks PostToolUseFailure (#5000); SessionStart/UserPromptSubmit/Stop and desktop plugins unwired | Failure disposition in hooks/reflection.py | Wire SessionStart/UserPromptSubmit/Stop; avoid relying on updatedInput |
| GAP-GROK-DRIFT | Grok Build & Grok Bot | .grok/hooks/lifecycle.json defines 8 events (#5354) vs. 14 in docs.x.ai; Grok passive hooks fail open and discard stdout; Grok Bot is hookless | PreToolUse blocking + tool.py pre-done | Sync .grok/hooks/lifecycle.json to 14 events; keep Grok Bot on CI gate |
| GAP-INTELLIJ-PLUGINS | JetBrains Plugins | No official JetBrains hook runtime docs retrieved for Claude, Copilot, Continue, Kilo, Q, or Junie; no IntelliJ plugin for Codex/Grok/Antigravity | AGENTS.md/CLAUDE.md + shaft-mcp + CI PR gate | Verify live IDE hook firing on Claude and Copilot JetBrains plugins |

## Primary References & Documentation Index

- ChaosEngine & SHAFT Repositories / Issues:
  - ShaftHQ/chaosengine-harness
  - ShaftHQ/SHAFT_ENGINE
  - SHAFT_ENGINE Releases
  - SHAFT_ENGINE #5000 — Reflection & Codex vs. Claude Parity
  - SHAFT_ENGINE #5354 — Runtime, Grok 8-Event Lifecycle & Probes
  - SHAFT_ENGINE #6178 — Host Parity & GEMINI.md
  - SHAFT_ENGINE #7860 — Claude Desktop Stop Loop Fix
  - SHAFT_ENGINE #8032 — Open-PR PreToolUse Gate Spec
  - SHAFT_ENGINE #8048 — Session Receipts & Usage
  - SHAFT_ENGINE #8051 — Mechanical tool.py & CI Gates
  - SHAFT_ENGINE #8058 — Standalone hosts.py Tracking
  - SHAFT_ENGINE #8059 — SDLC Role Coverage
  - SHAFT_ENGINE #8060 — Harness Parity Tracking
  - SHAFT_ENGINE #8062 — Core Harness Contract & Secret Guard
  - SHAFT MCP Docs and SHAFT Pilot Docs
- Official Client & SDK Specifications:
  - Claude Code Hooks Reference and Claude Code Hooks Guide
  - OpenAI Plugins Documentation, OpenAI Hooks Discovery, and OpenAI Config Reference
  - SpaceXAI Grok Build Hooks
  - Google Antigravity Hooks, Google Antigravity Rules, Google Antigravity Workflows, and Antigravity Python SDK Hooks
  - Gemini CLI Configuration and gemini-cli-hooks
  - GitHub Copilot Hooks Reference, GitHub Copilot Hooks Concepts, GitHub Copilot CLI Use Hooks, VS Code Copilot Hooks, VS Code Customizations Hooks, GitHub Copilot SDK Hooks Overview, and Copilot SDK Pre-Tool Use
  - RTK Supported Agents Matrix and NeuralTrust Antigravity Integration

### Hyperlink targets in the PDF

Every distinct link target embedded in [research.pdf](research.pdf), in order of first appearance, with the anchor text it sits on.

| # | Anchor text | URL |
|---|---|---|
| 1 | — | <https://github.com/ShaftHQ/chaosengine-harness> |
| 2 | ShaftHQ/SHAFT_ENGINE | <https://github.com/shafthq/SHAFT_ENGINE> |
| 3 | — | <https://github.com/ShaftHQ/SHAFT_ENGINE/issues/8062> |
| 4 | SHAFT_ENGINE | <https://github.com/ShaftHQ/SHAFT_ENGINE/issues/8051> |
| 5 | — | <https://github.com/ShaftHQ/SHAFT_ENGINE/issues/5000> |
| 6 | SHAFT_ENGINE | <https://github.com/MohabMohie/SHAFT_ENGINE/releases> |
| 7 | — | <https://github.com/ShaftHQ/SHAFT_ENGINE/issues/5354> |
| 8 | SHAFT_ENGINE | <https://github.com/ShaftHQ/SHAFT_ENGINE/issues/7860> |
| 9 | — | <https://github.com/ShaftHQ/SHAFT_ENGINE/issues/6178> |
| 10 | Code Hooks | <https://code.claude.com/docs/en/hooks> |
| 11 | Codex CLI Hooks | <https://ai.sulat.com/codex-hooks-just-gave-you-back-complete-control-over-your-code-57d044bcae1b> |
| 12 | Grok | <https://docs.x.ai/build/features/hooks> |
| 13 | — | <https://github.com/shanraisshan/gemini-cli-hooks> |
| 14 | Copilot Hooks | <https://docs.github.com/en/copilot/reference/hooks-reference> |
| 15 | VS Code Customizations | <https://code.visualstudio.com/learn/customizations/5-hooks> |
| 16 | GitHub Copilot SDK | <https://github.com/github/copilot-sdk/blob/main/docs/hooks/hooks-overview.md> |
| 17 | Antigravity | <https://antigravity.google/docs/hooks/> |
| 18 | Antigravity Python SDK | <https://github.com/google-antigravity/antigravity-sdk-python/blob/main/google/antigravity/hooks/README.md> |
| 19 | NeuralTrust | <https://docs.neuraltrust.ai/integrations/antigravity> |
| 20 | OpenAI Plugins | <https://developers.openai.com/plugins/build/plugins> |
| 21 | Source AI Coding Tools | <https://amux.io/lists/open-source-ai-coding-tools-2026/> |
| 22 | Agentic Coding | <https://iceberglakehouse.com/posts/agentic-coding-tools/> |
| 23 | Best AI Coding | <https://openagents.org/blog/posts/2026-05-21-best-ai-coding-agents> |
| 24 | Supported Agents | <https://www.rtk-ai.app/docs/getting-started/supported-agents/> |
| 25 | 10 Best AI Coding | <https://www.labellerr.com/blog/10-best-ai-coding-agents/> |
| 26 | SHAFT_ENGINE | <https://github.com/ShaftHQ/SHAFT_ENGINE/issues/8059> |
| 27 | SHAFT_ENGINE | <https://github.com/ShaftHQ/SHAFT_ENGINE/issues/8048> |
| 28 | SHAFT_ENGINE | <https://github.com/ShaftHQ/SHAFT_ENGINE/issues/8058> |
| 29 | SHAFT_ENGINE #8032 | <https://github.com/ShaftHQ/SHAFT_ENGINE/issues/8032> |
| 30 | Antigravity | <https://antigravity.google/docs/rules/> |
| 31 | SHAFT | <https://shafthq.github.io/docs/agentic/mcp> |
| 32 | SHAFT Pilot | <https://shafthq.github.io/docs/agentic/pilot> |
| 33 | Code Hooks | <https://code.claude.com/docs/en/hooks-guide> |
| 34 | Config | <https://learn.chatgpt.com/docs/config-file/config-reference> |
| 35 | Codex CLI Hooks | <https://agenticcontrolplane.com/blog/codex-cli-hooks-reference> |
| 36 | Hooks | <https://learn.chatgpt.com/docs/hooks> |
| 37 | Codex Agentic | <https://daily.dev/posts/put-your-own-logic-inside-the-codex-agentic-loop-jowjgysff> |
| 38 | Grok Build | <https://gist.github.com/YourAKShaw/9787c5f06809ffb9067bb39de6ea9c1f> |
| 39 | Google | <https://antigravity.google/docs/ide/workflows/> |
| 40 | AI Forum Antigravity | <https://discuss.ai.google.dev/t/hooks-in-antigravity/120458> |
| 41 | CLI | <https://geminicli.com/docs/reference/configuration/> |
| 42 | Code | <https://code.visualstudio.com/docs/agent-customization/hooks> |
| 43 | GitHub Copilot CLI Use | <https://docs.github.com/en/copilot/how-tos/copilot-cli/customize-copilot/use-hooks> |
| 44 | GitHub Copilot | <https://zenn.dev/rampo_dev/articles/github-copilot-hooks> |
| 45 | CLI Issue | <https://github.com/github/copilot-cli/issues/1730> |
| 46 | GitHub Copilot Hooks | <https://docs.github.com/en/copilot/concepts/customizations/hooks> |
| 47 | CLI Issue | <https://github.com/github/copilot-cli/issues/2540> |
| 48 | SDK Pre-Tool | <https://docs.github.com/en/copilot/how-tos/copilot-sdk/hooks/pre-tool-use> |
| 49 | Cursor Forum | <https://forum.cursor.com/t/project-workspaceopen-hook-never-runs-the-event-fires-during-a-hooks-config-reload-before-project-hooks-are-registered/172939> |
| 50 | SHAFT_ENGINE #8060 — Harness Parity Tracking | <https://github.com/ShaftHQ/SHAFT_ENGINE/issues/8060> |

### References in the HTML tracker (`REFS_DATA`)
Pulled verbatim from `REFS_DATA` in [research.html](research.html).

| # | Category | Title | URL | Note |
|---|---|---|---|---|
| 1 | ChaosEngine Repo | ShaftHQ/chaosengine-harness | <https://github.com/ShaftHQ/chaosengine-harness> | Root structure, entry points, supported clients, dod.py, VERSION |
| 2 | ChaosEngine Issue | SHAFT_ENGINE#5000 — Reflection & Codex vs Claude parity | <https://github.com/ShaftHQ/SHAFT_ENGINE/issues/5000> | Confirms .codex/hooks.json, guard.py, reflection.py, Codex missing PostToolUseFailure |
| 3 | ChaosEngine Issue | SHAFT_ENGINE#5354 — Runtime, Grok 8-event lifecycle & probes | <https://github.com/ShaftHQ/SHAFT_ENGINE/issues/5354> | Confirms Python 3.11.15, .grok/hooks/lifecycle.json (8 events), guard.py probes |
| 4 | ChaosEngine Issue | SHAFT_ENGINE#7860 — Claude Desktop Stop loop fix | <https://github.com/ShaftHQ/SHAFT_ENGINE/issues/7860> | Confirms _stop_block_reason + stop_hook_active ordering in Claude Desktop Code tab |
| 5 | ChaosEngine Issue | SHAFT_ENGINE#8051 — Mechanical tool.py & CI gates | <https://github.com/ShaftHQ/SHAFT_ENGINE/issues/8051> | Confirms GAP-CURSOR-HOOKS, GAP-OPENCODE-HOOKS, hookless bots, pre-done, harness_pr_gate.py |
| 6 | ChaosEngine Issue | SHAFT_ENGINE#8032 — Open-PR PreToolUse gate spec | <https://github.com/ShaftHQ/SHAFT_ENGINE/issues/8032> | Proposes extending hooks/guard.py PreToolUse on gh pr create/ready/reopen |
| 7 | ChaosEngine Issue | SHAFT_ENGINE#6178 — Host parity & GEMINI.md | <https://github.com/ShaftHQ/SHAFT_ENGINE/issues/6178> | Confirms GEMINI.md CE block only and Cursor/OpenCode absence from hosts.py |
| 8 | Official Docs | Claude Code Hooks Reference (33 events) | <https://code.claude.com/docs/en/hooks> | Primary specification for all 33 Claude Code lifecycle hooks |
| 9 | Official Docs | OpenAI Codex Plugins & Standalone Hooks | <https://developers.openai.com/plugins/build/plugins> | Confirms lifecycle hooks for manually installed Codex desktop plugins only |
| 10 | Official Docs | OpenAI Codex Hooks Discovery | <https://learn.chatgpt.com/docs/hooks> | Standalone hooks.json discovery semantics |
| 11 | Community Ref | Codex CLI Hooks Reference & 5 Events | <https://agenticcontrolplane.com/blog/codex-cli-hooks-reference> | Trust hashing, allow_managed_hooks_only, updatedInput rejection |
| 12 | Community Ref | Codex CLI 5-Event Lifecycle Breakdown | <https://ai.sulat.com/codex-hooks-just-gave-you-back-complete-control-over-your-code-57d044bcae1b> | PR #14626 UserPromptSubmit, v0.117.0 Pre/PostToolUse, SessionStart, Stop |
| 13 | Official Docs | SpaceXAI Grok Build Hooks (14 events) | <https://docs.x.ai/build/features/hooks> | Primary Grok Build spec: 14 events, PreToolUse sole blocker, fail-open, Cursor compat |
| 14 | Official Docs | Google Antigravity Hooks & Rules | <https://antigravity.google/docs/hooks/> | Primary spec for 6 Antigravity JSON hooks, tool schemas, config paths |
| 15 | Vendor Integration | NeuralTrust Antigravity Hooks Deployment | <https://docs.neuraltrust.ai/integrations/antigravity> | Notes lack of pre-model prompt blocker and workspace hooks.json caveats |
| 16 | Official SDK | Google Antigravity Python SDK Hook Architecture | <https://github.com/google-antigravity/antigravity-sdk-python/blob/main/google/antigravity/hooks/README.md> | Inspect / Decide / Transform SDK hook classes |
| 17 | Official Docs | Gemini CLI Configuration & 11 Hooks | <https://geminicli.com/docs/reference/configuration/> | hooks.BeforeTool / AfterTool reference (paired with gemini-cli-hooks v0.38.2) |
| 18 | Official Docs | GitHub Copilot Hooks & VS Code Docs | <https://docs.github.com/en/copilot/reference/hooks-reference> | CLI, Cloud Agent, frontmatter hooks, VS Code shared harness, Copilot SDK |
| 19 | Official SDK | GitHub Copilot SDK Hooks Overview | <https://github.com/github/copilot-sdk/blob/main/docs/hooks/hooks-overview.md> | onPreToolUse, onPostToolUse, onSessionStart, prompt transformation hooks |
| 20 | Issue / Bug | Copilot CLI #1730 & #2540; Cursor #172939 | <https://github.com/github/copilot-cli/issues/1730> | Documented sessionStart, plugin hook (#2540), and workspaceOpen (#172939) execution bugs |
| 21 | Integration Map | RTK Supported Agents Hook Matrix | <https://www.rtk-ai.app/docs/getting-started/supported-agents/> | Adapter mapping across 18 harnesses including OpenCode, Pi, OpenClaw, Trae, Droid, Vibe |
