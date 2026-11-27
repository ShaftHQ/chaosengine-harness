---
name: local-runtimes
description: >-
  Use when the delegation ladder has already selected a local runtime.
license: MIT
permissions:
  - bash
  - read
  - env
  - network
---

# Local runtimes

Model choice is the [delegation ladder](../../skills/chaos-engine/SKILL.md#delegation-ladder). This skill only picks a READY local runtime after that ladder has selected a local writer. Pick one row, then open only that route. A local writer never reviews its own diff.

| Need | Route | Open |
| --- | --- | --- |
| Which model size fits this machine | hardware probe | [local-coding-delegate](references/local-coding-delegate.md) |
| Already READY loopback server (Ollama, LM Studio, llamacpp) | loopback | [local-openai-compat](references/local-openai-compat.md) |
| Standalone FreeToken process | FreeToken | [freetoken](references/freetoken.md) |
| Frontier MoE through disk/RAM/VRAM tiers | Colibri | [colibri](references/colibri.md) |
| OmniRoute runner with delegate continuity | OmniRoute | [omniroute](references/omniroute.md) |
| Local agents (OpenCode / OSS agency) | agency | [local-agency](../local-agency/SKILL.md) |

FreeToken and Colibri share the [loopback runtime contract](references/loopback-runtime-contract.md).

Rules:

- A runtime is used only when its READY probe passes; otherwise return to the
  delegation ladder and record `local: skipped(<reason>)` once.
- One-shot jobs only: one short spec in, one digest out. No parent relay.
- Avoided-spend metering and USD/EGP lines are required only when a local
  inference channel was actually used
  ([process owner](../../references/process-owner-scrum-master.md)).
- Descriptions, paths and host exposure live in the
  [catalog](../../references/catalog.md).

Writer selection: the [delegation ladder](../../skills/chaos-engine/SKILL.md#delegation-ladder).
