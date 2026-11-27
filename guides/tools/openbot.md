# OpenBot

Host id: `openbot`.

Install as in [INSTALL.md](../../INSTALL.md). Inference never selects OpenBot from `grok` on `PATH`. Name it with `--hosts openbot` or `CHAOS_ENGINE_HOST=openbot`.

OpenBot is instruction-only (`GAP-OPENBOT-HOOKS`). It reads `AGENTS.md` and loads the canonical [chaos-engine router skill](../../skills/chaos-engine/SKILL.md) (`.chaos-engine/skills/chaos-engine/SKILL.md`) directly, along with [the bot entry](../../references/bot-entry.md) and the [level-1 catalog](../../references/level-1-catalog.md). ChaosEngine installs no hook runtime or receipt shim for OpenBot, and OpenBot makes no hook-enforcement claim. An explicit `tool.py retrieve` receipt substitutes for the hook read gate. Self-enforce `tool.py entry --full`, `tool.py retrieve`, `tool.py delete-check`, `tool.py ethics-check`, `tool.py pre-done --gate`, `tool.py dod`, `tool.py checkpoint` / `tool.py resume`, and `tool.py maintain`.

Published context and instruction caps are `unknown`. See [capability profiles](../../references/profiles/capabilities.md).

Example, not yet validated by the offline conformance job: install into a project, then follow [the developer start](../start-developer.md) or [the product-owner start](../start-product-owner.md).
