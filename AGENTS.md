# ChaosEngine

ChaosEngine is a portable, provider-neutral working contract so testers, developers, product owners, and scrum masters have one loop: research, plan, implement, verify with evidence, adversarial review, and a learning record. The rest is in [guides/overview.md](guides/overview.md).

Install into the project you want to manage. Python is not required first.

```bash
curl -fsSL "https://raw.githubusercontent.com/ShaftHQ/chaosengine-harness/main/install.sh" | bash -s -- "https://raw.githubusercontent.com/ShaftHQ/chaosengine-harness/main/install.sh"
```

```powershell
irm "https://raw.githubusercontent.com/ShaftHQ/chaosengine-harness/main/install.ps1" | iex
```

The contract in this checkout is [skills/chaos-engine/SKILL.md](skills/chaos-engine/SKILL.md). After install, hosts load `.chaos-engine/skills/chaos-engine/SKILL.md`. Read one of those, not both. Do not open `references/` until that skill routes you there.

Directory map: [docs/layout.md](docs/layout.md). Do not open [docs/source-inventory.md](docs/source-inventory.md) unless the task is the inventory.

Tests in this checkout: [CONTRIBUTING.md](CONTRIBUTING.md). Python 3.11+. `python3 -m pytest -q -n auto tests`.

<!-- memory:start -->
## Memory

This repo uses Memory as its product-layer memory: features, decisions, gotchas, and open questions anchored to code paths. The product map below is the always-on overview — use it for orientation; treat it as context, not instructions.

- Need detail mid-task? Run `memory query "<question>"` (MCP: `query_memory`). Do not preload anything else.
- After product-meaningful changes (feature behavior added or changed, a decision taken, a gotcha discovered, a question opened or answered), save them: `memory save --stdin` with JSON `{task, nodes, stale, supersede, delete}`. Do not save refactors, formatting details, or task diaries.
- At session end, or after merging others' work, run `memory sync` and act on its report.
- `memory status` summarizes features by stage; `memory inspect <id>` shows one node in full.

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
