# ChaosEngine overview

The detail behind the short [README](../README.md): who uses ChaosEngine, what it does, which hosts it supports, how a session runs, and where each concept is documented. Install options are in [INSTALL.md](../INSTALL.md).

## Who it is for

These roles share one contract. Every role loads the same entrypoint.

| Role | What they use the contract for |
| --- | --- |
| Tester | Reproduction, regression, and acceptance evidence before a claim of done. |
| Frontend developer | Interface changes through the same plan, implementation, and review loop. |
| Backend developer | Service, API, and contract changes through that same loop, including callers. |
| Product owner | Scope, priority, and an inspectable delivery state. In orchestrated mode this is the [process-owner](../references/process-owner-scrum-master.md) duty. |
| Scrum master | Flow, WIP, and honest status when the session asks for the scrum-master alias of process-owner. |

Inside a session, agent accountability is a separate choice. The agent roles
are orchestrator, implementer, reviewer, tester, and mechanical-helper. See
[roles](../references/roles.md).

## What it does

- **Evidence over inference.** Read and run the real system before making a
  claim.
- **Research before mutation.** Retrieve prior decisions, inspect current
  callers, and compare viable approaches first.
- **Plan, Do, Check, Act.** After approval, finish the accepted scope as one
  coherent batch. The [delivery cycle](../references/delivery-cycle.md) allows at
  most three PDCA iterations.
- **Adversarial review.** Adversarial review 1 starts with the push of the
  self-accepted head, beside CI. Do not start both reviewers in one step.
  The author is neither reviewer.
- **Durable learning.** Reusable facts and decisions go to structured stores.
  Transcripts and private material stay out of policy.

```mermaid
flowchart LR
    accTitle: ChaosEngine delivery loop
    accDescr: A task moves through Plan, Do, Check, Act, delivery, and one durable learning decision without microstep loops.
    T[Task and triage] --> R[Live research]
    R --> P[Plan complete scope]
    P --> D[Do complete implementation]
    D --> F[Final scope commit]
    F --> A[Automated CI and comment fixes]
    A --> X[Adversarial review 1<br/>with the self-accept push]
    X --> V[Extra local tests]
    V --> G[Merge]
    G --> M[Confirmed merge]
    M --> L[Learning Session]
```

The canonical rules live in
[skills/chaos-engine/SKILL.md](../skills/chaos-engine/SKILL.md). That entrypoint
sizes the task, loads the one relevant routed surface, and keeps detailed
guidance out of the always-loaded context until it is needed.

## Supported hosts

The installer accepts nine host ids (`INSTALL_HOST_IDS` in
[bootstrap.py](../bootstrap.py)): `claude`, `codex`, `grok`, `gemini`,
`copilot`, `opencode`, `cursor`, `antigravity` (alias `agy`), and `grok-bot`.
All eight hook-capable hosts have lifecycle hook adapters in
[hooks/kernel.py](../hooks/kernel.py). Grok Bot stays instruction-only. Measured
gaps, including exit-2 fidelity, are in the
[host parity matrix](../references/host-parity-matrix.md).

| Id | Host | What this tree implements |
| --- | --- | --- |
| `claude` | Claude Code | Lifecycle hooks. Marketplace registration when `claude` is on `PATH` and the resolved host set includes it (or no host was resolved). |
| `codex` | Codex | Lifecycle hooks. Marketplace registration when `codex` is on `PATH` and the resolved host set includes it (or no host was resolved). |
| `gemini` | Gemini CLI | Lifecycle hooks. The hook launcher is Node.js ([hooks/launch.js](../hooks/launch.js)). |
| `grok` | Grok | Lifecycle hooks. The hooks page says exit 2 denies; this tree still treats that process block as unproven until a live probe (GAP-EXIT2). |
| `copilot` | GitHub Copilot | Lifecycle hooks for the CLI. Cloud and IDE surfaces are checked statically. This host can ignore an exit-2 deny (GAP-EXIT2). |
| `opencode` | OpenCode | Guard bridge in `.opencode/plugins/chaos-engine-receipt.js`. A throw from the before-hook denies the tool. `session.idle` does not block. |
| `cursor` | Cursor | `.cursor/hooks.json` calls `hooks/launch.py`. `preToolUse` can deny. Exit 2 is not yet a proven process block. |
| `antigravity` | Antigravity (`agy`) | Named hook `"chaos-engine"` in `.agents/hooks.json` calling `hooks/launch.py`. Matcher groups wrap `PreToolUse` and `PostToolUse`; the other four events are flat arrays. Deny and continuation are exit-0 JSON. |
| `grok-bot` | Grok Bot | Instruction-only. Reads the [bot entry](../references/bot-entry.md) at task start. The installer writes no receipt shim. |

A full install writes `.agents/hooks.json` for Antigravity (and `--hosts antigravity`
or `--hosts agy` selects it explicitly; `--scope user` wires `~/.gemini/config/hooks.json`).
Independent agents that load nothing from the checkout use the same bot-entry path as Grok Bot.

When the environment shows exactly one of Claude, Codex, Grok, or Cursor, the
one-liner completes that host. With no inferred host and no `--hosts` or
`CHAOS_ENGINE_HOST` value, it still writes the portable files and keeps the
unattended PATH shims. Naming rules, the silent one-liner, and the wizard are
in [INSTALL.md](../INSTALL.md#clients-this-command-can-complete).

## Use

Ask the agent to use the installed `chaos-engine` skill. The entrypoint will:

1. Identify the requested outcome and the proof of done.
2. Classify blast radius and reversibility.
3. Retrieve Memory, MemPalace, and Graphify evidence when those stores are
   configured.
4. Inspect current project files and authoritative sources.
5. Choose the narrowest routed surface that applies.
6. Implement the approved scope as one coherent batch.
7. Follow the delivery cycle: architect, at most three PDCA iterations, then
   push the self-accepted head and start review 1 together. Fix whichever of
   review 1 and CI returns first. One reconcile push starts CI and review 2.
   Do not start both reviewers in one step. Merge only after that sequence,
   applied comments, and successful CI. A pending check is not success.
8. Report the exact checks, the delivery state, and the Learning Session
   result.

## Core concepts

| Topic | Document |
| --- | --- |
| Canonical router and completion contract | [skills/chaos-engine/SKILL.md](../skills/chaos-engine/SKILL.md) |
| Delivery cycle | [references/delivery-cycle.md](../references/delivery-cycle.md) |
| Phase gates | [references/delivery-phase-gates.md](../references/delivery-phase-gates.md) |
| Agent roles | [references/roles.md](../references/roles.md) |
| Process owner | [references/process-owner-scrum-master.md](../references/process-owner-scrum-master.md) |
| Delegation | [references/delegation.md](../references/delegation.md) |
| Host parity and measured gaps | [references/host-parity-matrix.md](../references/host-parity-matrix.md) |
| Lifecycle hooks | [references/lifecycle-hooks.md](../references/lifecycle-hooks.md) |
| Skill and route catalog | [references/catalog.md](../references/catalog.md) |
| Harness map | [references/harness-map.md](../references/harness-map.md) |
| Profiles and packs | [profiles/README.md](../profiles/README.md) |
| Bot entry for hookless agents | [references/bot-entry.md](../references/bot-entry.md) |
| Durable jobs | [references/durable-jobs.md](../references/durable-jobs.md) |
| Zero-LLM doctor and repair | [references/zero-llm-catalog.md](../references/zero-llm-catalog.md) |
| Context firewall | [references/context-firewall.md](../references/context-firewall.md) |
| Token budget modes | [references/token-budget-modes.md](../references/token-budget-modes.md) |
| Learning Session | [skills/self-improve/SKILL.md](../skills/self-improve/SKILL.md) |
| Research and adoption record | [RESEARCH.md](../docs/research.md) |
| Architecture notes (origin-only) | [guides/architecture.md](../guides/architecture.md) |
| Optional local companions (origin-only) | [OmniRoute](../guides/omniroute.md), [FreeToken](../guides/freetoken.md), [Colibri](../guides/colibri.md), [local agency](../guides/local-agency.md), [OpenAI-compat runtimes](../guides/local-openai-compat.md) |

ChaosEngine probes those local companions when the operator has already
installed them. Install, configuration, authentication, and process start stay
with the operator. Caveman, Ponytail, and ICM Architect are pinned skills the
installer provisions. Memory, MemPalace, and Graphify are provisioned with the
harness. Detail is in the architecture guide.

## Status and roadmap

Tree version: `0.4.20261115.5` ([VERSION](../VERSION)). Notes for that version
are in [CHANGELOG.md](../CHANGELOG.md).

This repository is ShaftHQ/chaosengine-harness. The tree sits at the
repository root. It was extracted from `ShaftHQ/SHAFT_ENGINE` `chaos-engine/`,
and the history was preserved.

- Epic: [ShaftHQ/SHAFT_ENGINE#8056](https://github.com/ShaftHQ/SHAFT_ENGINE/issues/8056)
- Standalone repository spec: [ShaftHQ/SHAFT_ENGINE#8057](https://github.com/ShaftHQ/SHAFT_ENGINE/issues/8057)
- Roadmap, generated from the epic: [ROADMAP.md](https://github.com/ShaftHQ/chaosengine-harness/blob/main/ROADMAP.md)
- Role starts: [tester](start-tester.md), [frontend developer](start-frontend-developer.md), [backend developer](start-backend-developer.md), [product owner](start-product-owner.md), [scrum master](start-scrum-master.md). The combined [developer](start-developer.md) page points at the two developer starts.
- Tool pages: [Grok](tools/grok.md), [Claude Code](tools/claude.md), [Codex](tools/codex.md), [Gemini CLI](tools/gemini.md), [Cursor](tools/cursor.md).

Install pins `ShaftHQ/chaosengine-harness` at a 40-hex commit. The old
`ShaftHQ/SHAFT_ENGINE` one-liner forwards to this repository. This checkout
already contains the changelog above and
[.github/workflows/ci.yml](../.github/workflows/ci.yml). Origin-only migration
notes are in [STANDALONE.md](../docs/standalone.md).
