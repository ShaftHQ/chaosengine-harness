# LSP-lite host proof

Date: 2026-11-28.

No host proved that PostToolUse stdout reaches the model. The host parity matrix
lists PostToolUse tool-output replacement as not proven for Claude Code, Codex,
Grok, Gemini, Copilot, OpenCode, Cursor, Antigravity, Grok Bot, and OpenBot.
This change did not run those hosts.

Hosts where delivery is not proved are unsupported, not pass. The post-edit
syntax advisory stays off. No hook was changed to emit it. There is no
environment switch that turns it on, because the check is not installed.

A later change may enable it only for a host with a recorded run showing the
advisory text in the next model turn. Until then the feature stays off.
