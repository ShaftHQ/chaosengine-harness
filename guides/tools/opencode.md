# OpenCode

Host id: `opencode`.

Install as in [INSTALL.md](../../INSTALL.md). Inference never selects OpenCode. Name it with `--hosts opencode` or `CHAOS_ENGINE_HOST=opencode`.

OpenCode reads `AGENTS.md`. That file stays the instruction file. Completing this host, and a full install, writes one directory plugin at `.opencode/plugins/chaos-engine/index.js`. The file is plain JavaScript. It uses `Plugin.define` and spawns `hooks/launch.py`. There is no npm build and no second rules file.

`ctx.tool.hook("execute.before")` throws when the guard denies. `ctx.session.hook("prompt")` can change the admitted text. Prompt hooks do not run for synthetic messages or compaction. The other current hooks only observe and do not deny: context, compaction, generate, title, experimental.model.resolve, model.request, http.request, http.response, experimental.ws.handshake, experimental.ws.send, experimental.ws.receive, retry, fork, evaluate, create.before, and execute.after. `session.created` does not inject text. These V1 names are not registered: tool.execute.before, tool.execute.after, session.created, and session.idle. `execute.before` and `execute.after` are not returned as V1 keys.

`process_exit2_honored` stays false. A missing opencode binary is blocking: unverifiable. This guide does not claim a live CLI run. Where a hook does not enforce, run `tool.py delete-check`, `tool.py pre-done --gate`, `tool.py dod`, and `tool.py ethics-check`.

Published context and instruction caps are `unknown`. See [capability profiles](../../references/profiles/capabilities.md).

Example, not yet validated by the offline conformance job: install into a docs-only repository, then follow [the tester start](../start-tester.md). No Java is required. ChaosEngine does not install the OpenCode product.
