# OpenCode

Host id: `opencode`.

Install as in [INSTALL.md](../../INSTALL.md). Inference never selects OpenCode. Name it with `--hosts opencode` or `CHAOS_ENGINE_HOST=opencode`.

OpenCode reads `AGENTS.md`. Completing this host, and a full install, writes `.opencode/plugins/chaos-engine-receipt.js`. That file is plain JavaScript. It spawns `hooks/launch.py` and throws when the guard denies. Kernel-registered events are tool.execute.before, execute.before, tool.execute.after, execute.after, session.created, and session.idle. V1 registers `tool.execute.before`. V2 registers `execute.before`. `session.idle` is observe-only. `session.created` has no documented context channel.

Published context and instruction caps are `unknown`. See [capability profiles](../../references/profiles/capabilities.md).

Example, not yet validated by the offline conformance job: install into a docs-only repository, then follow [the tester start](../start-tester.md). No Java is required. ChaosEngine does not install the OpenCode product.
