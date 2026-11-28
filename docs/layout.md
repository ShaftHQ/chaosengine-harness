# Repository layout

One map of this checkout. The installer copies the tree into `.chaos-engine/` and leaves out `docs/`, `guides/`, `tests/`, and the other origin-only paths.

| Path | What it is |
| --- | --- |
| `skills/` | Agent skills. Start at `skills/chaos-engine/SKILL.md`. |
| `references/` | On-demand contract pages linked from skills. |
| `guides/` | Human guides: overview, roles, architecture, per-tool pages. Not installed into adopter projects. |
| `runtime/` | Python modules the entry points load by path. Not an import package. |
| `hooks/` | Lifecycle hook runtime. |
| `rules/` | Rule modules. |
| `packs/` | Optional packs. |
| `profiles/` | Install profiles. Portable is the public default. |
| `addons/` | Add-on trees such as design-skills. |
| `plugins/` | Host plugin payloads. |
| `plugin-adapters/` | Adapters that project a plugin into a host. |
| `agent-plugins/` | Plugin package sources. |
| `companions/` | Companion cards linked from the core skill. |
| `vendor/` | Vendored upstream skill bodies. |
| `assets/` | Brand and other static assets. `assets/brand/` is not installed. |
| `bin/` | The optional npm wrapper `bin/chaosengine-harness.js`. |
| `schemas/` | JSON schemas for host-neutral contracts such as `ce-plan/v1`. |
| `scripts/` | Repository CI helpers. |
| `tests/` | Pytest suite. Not installed. |
| `evals/` | Evaluation fixtures. |
| `experiments/` | Experiment evidence. Not installed. |
| `docs/` | Maintainer notes, evidence, this map, and the generated inventory. Not installed. |
| `graphify-out/` | Derived Graphify index. Gitignored. Not installed. |
| `install.sh`, `install.ps1`, `bootstrap.py`, `install.py`, `tool.py`, `chaosengine_harness.py` | Install and tool entry points. They stay at the repository root. |
