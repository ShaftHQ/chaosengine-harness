---
name: chaos-engine
description: >-
  Canonical provider-neutral skill router and working contract. Use at the start
  of every task, on every host, in every main thread and delegate, before
  discovery, planning, edits, or answering.
license: MIT
---

# ChaosEngine

Delegates: [delegate card](../../references/delegate-card.md). Identity: [identity](../../identity.md). `<python>`: `py -3` Windows, `python3` Linux/macOS.

## Iron laws

1. Measure thrice, cut once: step back before retrieve, discovery, or edits; name the goal, larger context, and what a local hotfix would miss; then research and plan before the first edit.
2. Evidence over inference. Inspect or run before claiming.
3. Never weaken, delete, or rewrite a test to reach green.
4. Smallest correct change. Complete it before consolidated Check.
5. Never claim a check you did not run.
6. Finish before starting. WIP limits and Definition of Done ([kanban](../kanban/SKILL.md)).
7. Preserve user work and secrets. Irreversible or externally visible actions need explicit owner authority ([ethics card](../../companions/ethics-card.md)).

## Bigger picture first

Before Triage ([bigger picture first](../../references/bigger-picture-first.md)). Treat prompts as vague requirements; rephrase it as a domain expert; route by complexity to implementation or a spec first. One file and reversible: one line. If unsure, it is not trivial.

## Triage

| Worse answer | Depth |
| --- | --- |
| One file, reversible | Read, fix, prove. No plan document. |
| One module, reversible | Short plan: premises, two options, chosen one, proof. |
| Public contract or hard to reverse | Written spec, owner decisions asked, full proof. |

Before a broad search, run `<python> .chaos-engine/tool.py retrieve` and record `retrieve: used|skipped(<reason>)` ([retrieve-first](../../references/retrieve-first.md)).

## Plan, then go

After plan approval, routine in-scope work is unattended. Stop for an owner decision. Ledger: [delivery ledger](../../references/bot-entry.md#delivery-ledger).

## Implement

Companions at task start via `tool.py entry` ([bot entry](../../references/bot-entry.md)): [Caveman](../../companions/caveman-ultra.md), [Ponytail](../../companions/ponytail-ultra.md). Off only: `stop caveman`, `stop ponytail`, `normal mode`.

### Delegation ladder

One writer-selection rule. Stop at the first rung that applies. Record a receipt before the tool call (`python3 .chaos-engine/hooks/delegation_gate.py record`). Do not restate this ladder elsewhere. Hook hosts (Claude, Codex, Gemini, Grok, Copilot, Cursor, OpenCode, Antigravity) run this gate from `hooks/guard.py` on PreToolUse and refuse a writer with no matching receipt. Hookless clients (Grok Bot, OpenBot, custom GPTs) receive this section from `tool.py entry`. `dispatch.py argv` and `dispatch.py chat` refuse a free writer with no receipt.

1. Free writer. Proactively decompose the work into small file-disjoint items. If a free model is reachable (a hardware-fit local runtime or a free (`$0`) or local model on a gateway), send the item to the smartest one at its highest available reasoning effort (`high` / `max`). A smaller local model is only for an item the brief marks mechanical. Do not lower effort to save tokens.
2. Brief. The orchestrator writes it. Name the goal, the file scope, the behavior to preserve, the acceptance checks, the test command, and the stop conditions. The writer does not choose scope, model, or effort. A brief that only names an issue is not a dispatch. A host session subagent is not the default writer.
3. Nothing free is reachable. Ask the owner in that turn for explicit approval to install OpenCode and/or llama, plus the free models OpenCode provides and the free local models that fit this machine (RAM, GPU VRAM, CPU, disk). Do not install, download, or open a paid writer in that turn. Owner yes: install only what was approved, then return to rung 1. Owner no: go to rung 4 and record `free=unreachable-declined`. No answer: do not dispatch.
4. Free models are reachable and cannot do the item. The orchestrator judges it too complex for them, or a free writer already failed the acceptance checks. Record `free=too-complex`. Send the item to the cheapest of the paid / metered models that can do it, at the lowest task-appropriate effort (the lowest reasoning effort sufficient). When two models cost the same, pick the newer generation, never an older generation in that price tier.
5. Paid escalation. Stay on rung 4 until that choice fails the acceptance checks or the blast radius makes low effort insufficient. Raise effort up to high before raising the model tier. Raise toward a premium model only after the cheaper tier cannot do the item. When a lower effort is sufficient, keep it.

Review is not a writer rung. Independent adversarial review stays on a fresh-context host reviewer at the most intelligent setting. The writer never reviews its own diff.

A direct host edit is not a writer dispatch. Use it only for one tightly coupled change whose brief would cost more than the edit. Record `rung=direct`.

Receipt fields: `rung` (`free`, `ask`, `paid`, `direct`), `effort`, `why`, and a brief that passes rung 2. `paid` also requires `free` of `unreachable-declined` or `too-complex`. `free` requires effort `high` or `max` unless the item is mechanical.

## Check and deliver

- PDCA cap is 3, not a quota. Review 1 starts with the self-accept push (review 1 with the self-accept push) ([delivery cycle](../../references/delivery-cycle.md)). Do not start both reviewers in one step.
- Ordinary reversible: one fresh-context adversarial review. Public-contract or hard-to-reverse: two in sequence.
- Two failed attempts on one approach: step back and re-plan.
- A pending check is not success. Babysit until merged or `blocking: unverifiable`.
- Learning Session after every final delivery. Never local queues.
- Work is not done until the pull request is merged.

## Route

<!-- HARNESS-ROUTES:START -->
| Route | Use when | Load |
| --- | --- | --- |
| Local LLM | local runtime or agents | [local-runtimes](../local-runtimes/SKILL.md), [local-agency](../local-agency/SKILL.md), [omniroute](../omniroute/SKILL.md), [freetoken](../freetoken/SKILL.md), [colibri](../colibri/SKILL.md), [local-openai-compat](../local-openai-compat/SKILL.md), [local-coding-delegate](../local-coding-delegate/SKILL.md) |
| work-item | open or rewrite an issue or work item | [SKILL.md](../work-item/SKILL.md) |
| self-improve | after final delivery | [SKILL.md](../self-improve/SKILL.md) |
| kanban | several deliverables, tickets, or delegates | [SKILL.md](../kanban/SKILL.md) |
| architect | design, API, risk, review | [SKILL.md](../architect/SKILL.md) |
| Git cleanup | dirty worktree or stray branches | [SKILL.md](../git-cleanup/SKILL.md) |
| CI | slow merges, CI | [SKILL.md](../ci-cd/SKILL.md) |
| Security audit | audit a repository we own | [SKILL.md](../security-audit/SKILL.md) |
| Zero-LLM first | install, doctor, repair by script | [zero-llm-catalog.md](../../references/zero-llm-catalog.md) |
| Heal | drifted or unhealthy install | [heal-route.md](../../references/heal-route.md) |
| Level-1 catalog | secondary skill or tool needed | [level-1-catalog.md](../../references/level-1-catalog.md) |
| Context firewall | isolate broad research | [context-firewall.md](../../references/context-firewall.md) |
| Harness learn | traces show the overlay should change | [harness-learn.md](../../references/harness-learn.md) |
| Design loop | design doc needs review rounds | [design-loop.md](../../references/design-loop.md) |
| Deep research | cited multi-source research | [deep-research.md](../../references/deep-research.md) |
| UI delivery | user-visible UI | [ui-delivery.md](../../references/ui-delivery.md) |
| Public landing | calling card or product page | [public-landing.md](../../references/public-landing.md) |
| Learn traces | turn traces into lessons | [learn-traces.md](../../references/learn-traces.md) |
| Meta-optimize | periodic offline log review | [meta-optimize.md](../../references/meta-optimize.md) |
| Draft skill PR | opt-in eval-gated skill PR | [draft-skill-pr.md](../../references/draft-skill-pr.md) |
| Token budget | lean, balanced, or deep | [token-budget-modes.md](../../references/token-budget-modes.md) |
| Eliminate waste | a hop or retry adds no decision | [eliminate-waste.md](../../references/eliminate-waste.md) |
| Prefer CLI over MCP | CLI and MCP both fit | [prefer-cli-over-mcp.md](../../references/prefer-cli-over-mcp.md) |
| No proxy | a task would add a traffic proxy | [no-proxy.md](../../references/no-proxy.md) |
| GAP-EXIT2 UX | host ignores exit-2 hard blocks | [host-parity-matrix.md](../../references/host-parity-matrix.md) |
| Add-ons | design, video, or project pack | [addons.md](../../references/addons.md) |
| Complexity gate | complexity gate | [complexity-gate.md](../../references/complexity-gate.md) |
| Durable jobs | outlives the session | [durable-jobs.md](../../references/durable-jobs.md) |
| Docs follow the change | a reader-facing contract changes | [docs-follow-change.md](../../references/docs-follow-change.md) |
<!-- HARNESS-ROUTES:END -->

## Catalog

[catalog](../../references/catalog.md), [harness map](../../references/harness-map.md), [router contract](../../references/router-contract.md).
