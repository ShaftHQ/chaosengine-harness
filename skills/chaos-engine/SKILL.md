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

One writer-selection rule. Stop at the first rung that applies. Record a receipt before the tool call (`python3 .chaos-engine/hooks/delegation_gate.py record`). Hook hosts (including Antigravity) refuse an unreceipted writer via `hooks/guard.py` on PreToolUse; hookless clients (Grok Bot, OpenBot) load this via `tool.py entry`. `dispatch.py` `argv`/`chat` refuse unreceipted free writers.

1. Free writer. Decompose into small items. Send each to smartest reachable free (`$0`) or local model at its highest available reasoning effort. A hosted free quota or usage failure is not "nothing free is reachable" while a local runtime answers. Continue on that local model before any paid writer only when the brief marks the item mechanical. Non-mechanical implementation is off the mandatory local rung.
2. Brief. Name the goal, file scope, behavior to preserve, acceptance checks, test command, and stop conditions. The writer does not choose scope, model, or effort. A brief that only names an issue is not a dispatch. A host session subagent is not the default writer. A same-model high subagent is a context split.
3. Nothing free is reachable. Ask the owner for explicit approval to install OpenCode/llama and free models fitting hardware (RAM, GPU VRAM, CPU, disk); do not install or open a paid writer that turn. Yes: install approved only, return to rung 1. No: rung 4 (`free=unreachable-declined`). Silence: do not dispatch. A host message to continue with best judgment after a dismissed question is silence. It is not owner approval.
4. Free models cannot do it or failed acceptance checks: record `free=too-complex`; use the cheapest qualified paid / metered models at the lowest task-appropriate effort (lowest reasoning effort sufficient). Tied cost: newer generation, never older generation.
5. Stay on rung 4 until acceptance checks fail. Raise effort to high before model tier; premium only if the cheaper tier fails. Keep lower effort when sufficient.

Adversarial review stays on a fresh-context host reviewer at most intelligent setting; the writer never reviews its diff. Direct host edit: only one tightly coupled change whose brief costs more than the edit (`rung=direct`). Receipt: `rung` (`free|ask|paid|direct`), `effort`, `why`, rung-2 brief; `paid` needs `free=unreachable-declined|too-complex`; `free` needs `high|max` unless mechanical. A timed follow-up agent is replaced by the pull-request watch `scripts/agents/watch_pr_checks.py` plus the 3–5 minute stall check.

## Check and deliver

- PDCA cap is 3, not a quota. Review 1 starts with the self-accept push (review 1 with the self-accept push) ([delivery cycle](../../references/delivery-cycle.md)). Do not start both reviewers in one step.
- Ordinary reversible: one fresh-context adversarial review. Public-contract or hard-to-reverse: two in sequence.
- Two failed attempts on one approach: step back and re-plan.
- Two adversarial reviews are the chain for one subject. The gate refuses another. A second failed review ends the chain: the next edit closes that class and the test proves the class. A further example is a follow-up.
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
