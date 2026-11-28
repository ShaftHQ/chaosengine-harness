# OpenBot

Host id: `openbot`.

Install as in [INSTALL.md](../../INSTALL.md). Inference never selects OpenBot from `grok` on `PATH`. Name it with `--hosts openbot` or `CHAOS_ENGINE_HOST=openbot`.

OpenBot is instruction-only (`GAP-OPENBOT-HOOKS`). It has no hook runtime of its own. ChaosEngine installs no OpenBot proxy, no fake hook event, and no receipt shim. OpenBot injects `AGENTS.md`, or `CLAUDE.md` when that is the only file, at most 32000 characters, and only when that provider's `workspaceInstructionFiles` does not already name the file. A longer file is cut. Doctor warns. Do not raise the cap. Claude and Codex already name `CLAUDE.md` and `AGENTS.md`, so they keep their own hooks and do not get a second injected copy. Claude in workspace-only mode still receives the text, because it reads user settings only. Codex caches `AGENTS.md` for the loaded session; a change starts a new Codex session, and OpenBot does not also inject it.

Grok's provider descriptor lists no workspace instruction file, so OpenBot injects the text. Hook execution is the Grok child's user-level PreToolUse hook (`~/.grok/hooks/chaos-engine.json` or `$GROK_HOME/hooks/chaos-engine.json`), not an OpenBot event. A failed `grok inspect` or an inspect that returns `hooks: []` is not a healthy hook result. A healthy doctor does not mean those hooks ran. A `grok inspect` that cannot be run, or an OpenBot prompt capture that cannot be made, is blocking: unverifiable, not a pass.

Grok does not discover the project pointers at `.agents/skills/chaos-engine/SKILL.md` or `.claude/skills/chaos-engine/SKILL.md`. Install adds a pointer at `.grok/skills/chaos-engine/SKILL.md` that points at the canonical [chaos-engine router skill](../../skills/chaos-engine/SKILL.md) (`.chaos-engine/skills/chaos-engine/SKILL.md`). It does not copy rule text. OpenBot still loads that router directly from `AGENTS.md`, along with [the bot entry](../../references/bot-entry.md) and the [level-1 catalog](../../references/level-1-catalog.md). An explicit `tool.py retrieve` receipt substitutes for the hook read gate. Self-enforce `tool.py entry --full`, `tool.py retrieve`, `tool.py delete-check`, `tool.py ethics-check`, `tool.py pre-done --gate`, `tool.py dod`, `tool.py checkpoint` / `tool.py resume`, and `tool.py maintain`.

Published context cap is `unknown`. The instruction injection cap is 32000 characters. See [capability profiles](../../references/profiles/capabilities.md).

Example, not yet validated by the offline conformance job: install into a project, then follow [the developer start](../start-developer.md) or [the product-owner start](../start-product-owner.md).
