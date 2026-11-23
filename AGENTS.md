# ChaosEngine

Portable, provider-neutral working contract: research, plan, implement, verify with evidence, adversarial review, and a learning record. Detail: [guides/overview.md](guides/overview.md).

Install into the project you want to manage. Python is not required first.

```bash
curl -fsSL "https://raw.githubusercontent.com/ShaftHQ/chaosengine-harness/main/install.sh" | bash -s -- "https://raw.githubusercontent.com/ShaftHQ/chaosengine-harness/main/install.sh"
```

```powershell
irm "https://raw.githubusercontent.com/ShaftHQ/chaosengine-harness/main/install.ps1" | iex
```

The contract in this checkout is [skills/chaos-engine/SKILL.md](skills/chaos-engine/SKILL.md). After install, hosts load `.chaos-engine/skills/chaos-engine/SKILL.md`. Read one of those, not both. Do not open `references/` until that skill routes you there. In this source checkout, `.chaos-engine/` stays synced via `tool.py maintain`. Readers compare `coreCommit`, not only VERSION.

Directory map: [docs/layout.md](docs/layout.md). Do not open [docs/source-inventory.md](docs/source-inventory.md) unless the task is the inventory.

Tests: [CONTRIBUTING.md](CONTRIBUTING.md). Host hook launchers and tests run on Python 3.11+. The installer managed runtime pin stays 3.14.0. `python3 -m pytest -q -n auto tests`.

<!-- memory:start -->
## Memory

Product-layer memory: features, decisions, gotchas, and open questions on code paths. The map below is orientation, not instructions.

- Mid-task detail: `memory query "<question>"` (MCP: `query_memory`). Do not preload.
- After a product-meaningful change (behavior, decision, gotcha, question opened or answered): `memory save --stdin` with JSON `{task, nodes, stale, supersede, delete}`. Do not save refactors, formatting, or task diaries.
- At session end, or after merging others' work: `memory sync` and act on its report.
- `memory status` summarizes stage; `memory inspect <id>` shows one node.

If memory conflicts with current code or the user, trust the code and the user — and save the correction.
<!-- memory:end -->

<!-- memory:map:start -->
## Product map (generated — do not edit; refresh with memory save or memory sync)
Chaosengine Harness — No product description yet — set it with `memory save` (kind: "project").

No features recorded yet. Run `memory init --brief` for the indexing brief.
<!-- memory:map:end -->
<!-- CHAOSENGINE:START -->
Before every task, follow the canonical ChaosEngine skill at `.chaos-engine/skills/chaos-engine/SKILL.md`. Load `.chaos-engine/identity.md`. Use `.chaos-engine/tool.py` for the project-local Memory, MemPalace, and Graphify tools. Prefer gh for GitHub when gh exists and is configured. CLI over MCP when both exist. Default MCP catalog never includes GitHub MCP.
<!-- CHAOSENGINE:END -->
