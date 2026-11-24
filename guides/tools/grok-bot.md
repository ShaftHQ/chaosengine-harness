# Grok Bot

Host id: `grok-bot`.

Install as in [INSTALL.md](../../INSTALL.md). Inference never selects Grok Bot. Name it with `--hosts grok-bot` or `CHAOS_ENGINE_HOST=grok-bot`.

Grok Bot is instruction-only. It does not auto-load the checkout. At task start, read [the bot entry](../../references/bot-entry.md). The installer writes no receipt shim. The research receipt replaces the hook gate (GAP-GROKBOT-HOOKS). Self-enforce `tool.py entry --full`, `tool.py retrieve`, `tool.py delete-check`, `tool.py ethics-check`, `tool.py pre-done`, `tool.py dod`, `tool.py checkpoint` / `tool.py resume`, and `tool.py maintain`. GAP-BOT-ENTRY residual risk: a hookless bot can still submit a person-only assessment if it skips `tool.py ethics-check`.

Published context and instruction caps are `unknown`. See [capability profiles](../../references/profiles/capabilities.md).

Example, not yet validated by the offline conformance job: from a story repository, follow [the product-owner start](../start-product-owner.md) after reading the bot entry. No Java is required.
