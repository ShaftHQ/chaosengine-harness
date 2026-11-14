<p align="center">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="assets/brand/lockup-dark.svg">
    <source media="(prefers-color-scheme: light)" srcset="assets/brand/lockup-light.svg">
    <img alt="ChaosEngine" src="assets/brand/lockup-light.svg" width="720">
  </picture>
</p>

# ChaosEngine

ChaosEngine is a portable, provider-neutral working contract for software
agents. Testers, frontend and backend developers, product owners, and scrum
masters use the same contract, independent of team, language, framework, or
product. One entrypoint covers research, planning, implementation,
verification, review, delivery, and learning. The contract discovers a
project's own engineering rules, routes each task to one surface, and requires
evidence before a claim that the work is done.

**Humans:** this page is the overview. Install steps and options stay in
[INSTALL.md](INSTALL.md).

**Agents:** load [skills/chaos-engine/SKILL.md](skills/chaos-engine/SKILL.md)
and follow it. This README is a map. Working policy stays in that skill.

## Who it is for

These roles share one contract. Every role loads the same entrypoint.

| Role | What they use the contract for |
| --- | --- |
| Tester | Reproduction, regression, and acceptance evidence before a claim of done. |
| Frontend developer | Interface changes through the same plan, implementation, and review loop. |
| Backend developer | Service, API, and contract changes through that same loop, including callers. |
| Product owner | Scope, priority, and an inspectable delivery state. In orchestrated mode this is the [process-owner](references/process-owner-scrum-master.md) duty. |
| Scrum master | Flow, WIP, and honest status when the session asks for the scrum-master alias of process-owner. |

Inside a session, agent accountability is a separate choice. The agent roles
are orchestrator, implementer, reviewer, tester, and mechanical-helper. See
[roles](references/roles.md).

## What it does

- **Evidence over inference.** Read and run the real system before making a
  claim.
- **Research before mutation.** Retrieve prior decisions, inspect current
  callers, and compare viable approaches first.
- **Plan, Do, Check, Act.** After approval, finish the accepted scope as one
  coherent batch. The [delivery cycle](references/delivery-cycle.md) allows at
  most three PDCA iterations.
- **Adversarial review.** After the accepted Check and green required checks,
  two independent reviews run on that head. The author is neither reviewer.
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
    A --> X[Two adversarial reviews<br/>after the green head]
    X --> V[Extra local tests]
    V --> G[Merge]
    G --> M[Confirmed merge]
    M --> L[Learning Session]
```

The canonical rules live in
[skills/chaos-engine/SKILL.md](skills/chaos-engine/SKILL.md). That entrypoint
sizes the task, loads the one relevant routed surface, and keeps detailed
guidance out of the always-loaded context until it is needed.

## Supported hosts

The installer accepts eight host ids (`INSTALL_HOST_IDS` in
[bootstrap.py](bootstrap.py)). Five have lifecycle hook adapters in
[hooks/kernel.py](hooks/kernel.py) and [hosts.py](hosts.py). OpenCode, Cursor,
and Grok Bot are instruction-only. Measured gaps, including exit-2 fidelity,
are in the [host parity matrix](references/host-parity-matrix.md).

| Id | Host | What this tree implements |
| --- | --- | --- |
| `claude` | Claude Code | Lifecycle hooks. Marketplace registration when the `claude` CLI is on `PATH`. |
| `codex` | Codex | Lifecycle hooks. Marketplace registration when the `codex` CLI is on `PATH`. |
| `gemini` | Gemini CLI | Lifecycle hooks. The hook launcher is Node.js ([hooks/launch.js](hooks/launch.js)). |
| `grok` | Grok | Lifecycle hooks. This host can ignore an exit-2 deny (GAP-EXIT2). |
| `copilot` | GitHub Copilot | Lifecycle hooks for the CLI. Cloud and IDE surfaces are checked statically. This host can ignore an exit-2 deny (GAP-EXIT2). |
| `opencode` | OpenCode | Instruction-only (`AGENTS.md`). Selecting the host writes `.opencode/plugins/chaos-engine-receipt.js`. |
| `cursor` | Cursor | Instruction-only (`AGENTS.md`). Selecting the host writes `.cursor/hooks.json`. No portable pre-tool hook (GAP-CURSOR-HOOKS). |
| `grok-bot` | Grok Bot | Instruction-only. Reads the [bot entry](references/bot-entry.md) at task start. The installer writes no receipt shim. |

[hosts.py](hosts.py) also maps `antigravity` to `AGENTS.md`. That id is
outside the installer host list. Independent agents that load nothing from the
checkout use the same bot-entry path as Grok Bot.

When the environment shows exactly one of Claude, Codex, Grok, or Cursor, the
one-liner completes that host. With no inferred host and no `--hosts` or
`CHAOS_ENGINE_HOST` value, it still writes the portable files and keeps the
unattended PATH shims. Naming rules, the silent one-liner, and the wizard are
in [INSTALL.md](INSTALL.md#clients-this-command-can-complete).

## Install

Until the installer switch in
[ShaftHQ/SHAFT_ENGINE#8057](https://github.com/ShaftHQ/SHAFT_ENGINE/issues/8057)
lands, the working one-liner fetches from `ShaftHQ/SHAFT_ENGINE`. Change into
the project directory first. The command does not need Python on the machine
beforehand.

The PyPI and npm projects named `chaosengine-harness` are reserved `0.0.1`
placeholders. Installation is the one-liner below.

Windows PowerShell ([install.ps1](install.ps1), from
[INSTALL.md](INSTALL.md#golden-path-first-run)):

```powershell
irm "https://raw.githubusercontent.com/ShaftHQ/SHAFT_ENGINE/main/chaos-engine/install.ps1" | iex
```

macOS or Linux ([install.sh](install.sh)):

```bash
curl -fsSL "https://raw.githubusercontent.com/ShaftHQ/SHAFT_ENGINE/main/chaos-engine/install.sh" | bash -s -- "https://raw.githubusercontent.com/ShaftHQ/SHAFT_ENGINE/main/chaos-engine/install.sh"
```

Host flags, add-ons, offline bundles, and every other option are in
[INSTALL.md](INSTALL.md). Read [install.ps1](install.ps1),
[install.sh](install.sh), and [bootstrap.py](bootstrap.py) first when your
trust policy requires review before execution. The public default is the
neutral `portable` profile ([profiles](profiles/README.md),
[distributions.json](distributions.json)).

### Doctor, upgrade, uninstall

After the command finishes, run doctor in that same project. On Windows use
`py -3` instead of `python3`. Restart an already-running host so it loads the
new plugin.

```text
python3 .chaos-engine/install.py doctor --project .
```

- **Upgrade:** run the same one-liner again. A failed or invalid download
  leaves the last verified installation unchanged.
- **Rollback:** `python3 .chaos-engine/install.py rollback --project .`
- **Uninstall:** `python3 .chaos-engine/install.py uninstall --project .`

Rollback and uninstall change only receipt-owned ChaosEngine files. Mixed or
unknown ownership stops and leaves unrelated project content in place. The
removed-versus-retained table and clean-reinstall steps are in
[INSTALL.md](INSTALL.md#uninstall--rollback-first-time-recovery).

Lifecycle, ownership, dependencies, trust boundaries, and the companion list
are in [guides/architecture.md](guides/architecture.md). That guide is
origin-only and stays in this repository.

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
   two independent adversarial reviews.
8. Report the exact checks, the delivery state, and the Learning Session
   result.

## Core concepts

| Topic | Document |
| --- | --- |
| Canonical router and completion contract | [skills/chaos-engine/SKILL.md](skills/chaos-engine/SKILL.md) |
| Delivery cycle | [references/delivery-cycle.md](references/delivery-cycle.md) |
| Phase gates | [references/delivery-phase-gates.md](references/delivery-phase-gates.md) |
| Agent roles | [references/roles.md](references/roles.md) |
| Process owner | [references/process-owner-scrum-master.md](references/process-owner-scrum-master.md) |
| Delegation | [references/delegation.md](references/delegation.md) |
| Host parity and measured gaps | [references/host-parity-matrix.md](references/host-parity-matrix.md) |
| Lifecycle hooks | [references/lifecycle-hooks.md](references/lifecycle-hooks.md) |
| Skill and route catalog | [references/catalog.md](references/catalog.md) |
| Harness map | [references/harness-map.md](references/harness-map.md) |
| Profiles and packs | [profiles/README.md](profiles/README.md) |
| Bot entry for hookless agents | [references/bot-entry.md](references/bot-entry.md) |
| Durable jobs | [references/durable-jobs.md](references/durable-jobs.md) |
| Zero-LLM doctor and repair | [references/zero-llm-catalog.md](references/zero-llm-catalog.md) |
| Context firewall | [references/context-firewall.md](references/context-firewall.md) |
| Token budget modes | [references/token-budget-modes.md](references/token-budget-modes.md) |
| Learning Session | [skills/self-improve/SKILL.md](skills/self-improve/SKILL.md) |
| Research and adoption record | [RESEARCH.md](RESEARCH.md) |
| Architecture notes (origin-only) | [guides/architecture.md](guides/architecture.md) |
| Optional local companions (origin-only) | [OmniRoute](guides/omniroute.md), [FreeToken](guides/freetoken.md), [Colibri](guides/colibri.md), [local agency](guides/local-agency.md), [OpenAI-compat runtimes](guides/local-openai-compat.md) |

ChaosEngine probes those local companions when the operator has already
installed them. Install, configuration, authentication, and process start stay
with the operator. Caveman, Ponytail, and ICM Architect are pinned skills the
installer provisions. Memory, MemPalace, and Graphify are provisioned with the
harness. Detail is in the architecture guide.

## Status and roadmap

Tree version: `0.4.20261114.5` ([VERSION](VERSION)). Notes for that version
are in [CHANGELOG.md](CHANGELOG.md).

This repository is ShaftHQ/chaosengine-harness. The tree sits at the
repository root. It was extracted from `ShaftHQ/SHAFT_ENGINE` `chaos-engine/`,
and the history was preserved.

- Epic: [ShaftHQ/SHAFT_ENGINE#8056](https://github.com/ShaftHQ/SHAFT_ENGINE/issues/8056)
- Standalone repository spec: [ShaftHQ/SHAFT_ENGINE#8057](https://github.com/ShaftHQ/SHAFT_ENGINE/issues/8057)

Still open on that spec: a bootstrap that accepts this root layout or the old
nested `chaos-engine/` prefix, release publishing, the installer pin and the
redirect from the `ShaftHQ/SHAFT_ENGINE` one-liner, issue transfer, and
role-based docs. This checkout already contains the changelog above and
[.github/workflows/ci.yml](.github/workflows/ci.yml). Origin-only migration
notes are in [STANDALONE.md](STANDALONE.md).

## Contributing

Read [CONTRIBUTING.md](CONTRIBUTING.md),
[CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md), and [SECURITY.md](SECURITY.md).

## License

MIT. Copyright ChaosEngine contributors. See [LICENSE](LICENSE) and
[THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).

## Reference: source-derived inventory

Repository validators parse the delimited blocks in this section. Keep each
block, and the heading directly above it, unchanged.

## OmniRoute decision-quality evidence

Transparent side-by-side results from the free OmniRoute walking skeleton
(#5522 / #5465). Values below are generated from the committed aggregate and
are published regardless of positive, neutral, negative, or inconclusive
outcome.

<!-- evidence:omniroute-calibration:start -->
This section is generated from
[`chaos-engine/decision-quality-calibration.aggregate.json`](decision-quality-calibration.aggregate.json).
Do not hand-edit the numbers; refresh with
`python3 scripts/ci/validate_chaos_engine_readme.py --write`.

Label: **directional walking skeleton** (n=12/12 observed/planned trials).
This is not a Harbor 95% CI powered pilot.

| Field | Value |
| --- | --- |
| Gate verdict | NO |
| Gate reason | correctness did not beat control |
| Correctness delta (treatment - control) | 0.0 |
| Models used | nvidia/nemotron-3-ultra-550b-a55b |
| Preferred model | agy/gemini-3.7-flash-high |
| Tasks | diagnosis-failure-trace, repair-regression-test, delivery-focused-proof |
| Status | complete |

| Metric | control | chaos-engine |
| --- | --- | --- |
| `correctness` | 0.0 | 0.0 |
| `tokens` | 351.6666666666667 | 371.1666666666667 |
| `latency_seconds` | 24.54195623733055 | 36.893572025665584 |
| `external_run_minutes` | UNAVAILABLE | UNAVAILABLE |
| `actions` | 1.0 | 1.0 |
| `retries` | 0.0 | 0.0 |
| `cost_usd` | UNAVAILABLE | UNAVAILABLE |
| `variance` | 0.0 | 0.0 |

Methodology and final report:
[decision-quality-calibration.md](decision-quality-calibration.md),
[decision-quality-report.md](decision-quality-report.md).
Missing telemetry remains the literal `UNAVAILABLE` (never `0`).
<!-- evidence:omniroute-calibration:end -->

## Source-derived inventory

These tables are generated from the dependency manifest, Python imports, skill
catalogs, lifecycle event registry, and host capability map. Their text remains
usable without Mermaid; unknown source entries fail the inventory validator.

### Prerequisites

<!-- inventory:prerequisites:start -->
| Item | Purpose | Source of truth | Status | Platforms | Provisioner | Owner | Failure behavior |
| --- | --- | --- | --- | --- | --- | --- | --- |
| Latest stable Python | Run bootstrap, installer, kernel, and tools without old-runtime defects. | install.ps1; install.sh; dependencies.json | managed | Windows, Linux, macOS | uv managed Python | user account | install stops before activation |
| PowerShell or POSIX shell | Launch the reviewed bootstrap wrapper. | install.ps1; install.sh | required | platform native | operating system | consumer environment | bootstrap does not start |
| curl or wget | Download immutable source on POSIX. | install.sh | required on POSIX | Linux, macOS | operator | consumer environment | download fails closed |
| Node.js, npm, and npx | Provision Memory, Context7 CLI, and plugin MCP runtimes. | dependencies.json; hooks/launch.js | managed | Windows, Linux, macOS | platform standard provider | user account | install stops before activation |
| network | Resolve source and provision a fresh or upgraded generation. | bootstrap.py; dependencies.py | required for fresh install or upgrade | Windows, Linux, macOS | operator | prior verified generation remains active |
| Git, managed Temurin JDK 25+, and managed Apache Maven | Build optional Maven Tools MCP cache when ambient JDK/Maven are missing. | dependencies.json; install.py; hosts.py | optional and managed with `--with-maven-tools` | Windows, Linux, macOS | managed Temurin/Maven cache plus upstream Maven wrapper | receipt-owned shared cache | optional component reports absent |
<!-- inventory:prerequisites:end -->

### Python Libraries

<!-- inventory:python-libraries:start -->
| Item | Purpose | Source of truth | Status | Platforms | Provisioner | Owner | Failure behavior |
| --- | --- | --- | --- | --- | --- | --- | --- |
| argparse | Portable runtime standard-library dependency. | chaos-engine/addons/design-skills/scripts/design_qc.py, chaos-engine/addons/design-skills/scripts/title_scope_gate.py, chaos-engine/backups_watch.py, chaos-engine/bootstrap.py, chaos-engine/ce_brief.py, chaos-engine/commit_identity.py, chaos-engine/content_scan_preflight.py, chaos-engine/context_rot.py, chaos-engine/deep_research.py, chaos-engine/dependencies.py, chaos-engine/draft_skill_pr.py, chaos-engine/external_reflection.py, chaos-engine/genai_spans.py, chaos-engine/harness_index.py, chaos-engine/harness_map.py, chaos-engine/heuristics.py, chaos-engine/hooks/receipt_shim.py, chaos-engine/hooks/reflection.py, chaos-engine/insight_extract.py, chaos-engine/install.py, chaos-engine/jobs.py, chaos-engine/learn_traces.py, chaos-engine/learning.py, chaos-engine/learning_session.py, chaos-engine/memory_provenance.py, chaos-engine/mempalace_privacy.py, chaos-engine/meta_optimize.py, chaos-engine/phase_ledger.py, chaos-engine/profile_installs.py, chaos-engine/prompt_evolve.py, chaos-engine/references/details/likeness_record_train.py, chaos-engine/retrieve.py, chaos-engine/rules/memory_full_dump.py, chaos-engine/self_modify.py, chaos-engine/session_token_usage.py, chaos-engine/significance.py, chaos-engine/silent_verify.py, chaos-engine/skill_compress_audit.py, chaos-engine/skills/colibri/scripts/probe.py, chaos-engine/skills/freetoken/scripts/probe.py, chaos-engine/skills/local-agency/scripts/assert_parent_rog_shell.py, chaos-engine/skills/local-agency/scripts/design_turn_gate.py, chaos-engine/skills/local-agency/scripts/dispatch.py, chaos-engine/skills/local-agency/scripts/executor_brief.py, chaos-engine/skills/local-agency/scripts/require_rog_freetoken.py, chaos-engine/skills/local-agency/scripts/tip_preflight.py, chaos-engine/skills/local-agency/scripts/worker_ce_entry.py, chaos-engine/skills/local-coding-delegate/scripts/probe_hardware.py, chaos-engine/skills/local-openai-compat/scripts/probe.py, chaos-engine/skills/omniroute/scripts/runner.py, chaos-engine/task_ledger.py, chaos-engine/wake_pack.py, chaos-engine/workflow_induce.py, chaos-engine/worktree_overlay.py | required | Windows, Linux, macOS | resolved latest stable Python | Python runtime | affected command fails closed |
| array | Portable runtime standard-library dependency. | chaos-engine/addons/design-skills/scripts/design_qc.py | required | Windows, Linux, macOS | resolved latest stable Python | Python runtime | affected command fails closed |
| ast | Portable runtime standard-library dependency. | chaos-engine/harness_map.py, chaos-engine/skills/local-agency/scripts/tip_preflight.py | required | Windows, Linux, macOS | resolved latest stable Python | Python runtime | affected command fails closed |
| atexit | Portable runtime standard-library dependency. | chaos-engine/install.py | required | Windows, Linux, macOS | resolved latest stable Python | Python runtime | affected command fails closed |
| base64 | Portable runtime standard-library dependency. | chaos-engine/hosts.py, chaos-engine/install.py, chaos-engine/secret_guard.py, chaos-engine/skills/local-agency/scripts/require_rog_freetoken.py | required | Windows, Linux, macOS | resolved latest stable Python | Python runtime | affected command fails closed |
| binascii | Portable runtime standard-library dependency. | chaos-engine/secret_guard.py | required | Windows, Linux, macOS | resolved latest stable Python | Python runtime | affected command fails closed |
| bisect | Portable runtime standard-library dependency. | chaos-engine/vendor/icm-architect/skills/icm-architect/scripts/quotes.py | required | Windows, Linux, macOS | resolved latest stable Python | Python runtime | affected command fails closed |
| collections | Portable runtime standard-library dependency. | chaos-engine/bootstrap.py, chaos-engine/hooks/guard.py, chaos-engine/hooks/lifecycle.py, chaos-engine/learn_traces_mrv.py, chaos-engine/mcp_policy.py, chaos-engine/silent_verify.py | required | Windows, Linux, macOS | resolved latest stable Python | Python runtime | affected command fails closed |
| concurrent | Portable runtime standard-library dependency. | chaos-engine/addons/design-skills/scripts/linkcheck.py, chaos-engine/bootstrap.py | required | Windows, Linux, macOS | resolved latest stable Python | Python runtime | affected command fails closed |
| contextlib | Portable runtime standard-library dependency. | chaos-engine/bootstrap.py, chaos-engine/dependencies.py, chaos-engine/hooks/guard.py, chaos-engine/hooks/kernel.py, chaos-engine/hooks/lifecycle.py, chaos-engine/hosts.py, chaos-engine/install.py, chaos-engine/jobs.py, chaos-engine/learning.py, chaos-engine/learning_session.py, chaos-engine/pack_binding.py, chaos-engine/packs/java/installer.py, chaos-engine/packs/java/maven_tools.py, chaos-engine/silent_verify.py, chaos-engine/skills/omniroute/scripts/runner.py, chaos-engine/stores.py | required | Windows, Linux, macOS | resolved latest stable Python | Python runtime | affected command fails closed |
| ctypes | Portable runtime standard-library dependency. | chaos-engine/bootstrap.py, chaos-engine/dependencies.py, chaos-engine/hosts.py, chaos-engine/jobs.py, chaos-engine/prerequisites.py, chaos-engine/skills/local-coding-delegate/scripts/probe_hardware.py | required | Windows, Linux, macOS | resolved latest stable Python | Python runtime | affected command fails closed |
| dataclasses | Portable runtime standard-library dependency. | chaos-engine/hooks/kernel.py, chaos-engine/mobile_retro.py, chaos-engine/rules/memory_full_dump.py | required | Windows, Linux, macOS | resolved latest stable Python | Python runtime | affected command fails closed |
| datetime | Portable runtime standard-library dependency. | chaos-engine/deep_research.py, chaos-engine/dependencies.py, chaos-engine/harness_mindset.py, chaos-engine/hooks/reflection.py, chaos-engine/hosts.py, chaos-engine/learn_traces.py, chaos-engine/learn_traces_mrv.py, chaos-engine/progress_log.py, chaos-engine/rules/ethics_check.py, chaos-engine/skills/omniroute/scripts/runner.py | required | Windows, Linux, macOS | resolved latest stable Python | Python runtime | affected command fails closed |
| difflib | Portable runtime standard-library dependency. | chaos-engine/addons/design-skills/scripts/craft_qc.py, chaos-engine/addons/design-skills/scripts/design_qc.py, chaos-engine/addons/design-skills/scripts/surface_qc.py, chaos-engine/worktree_overlay.py | required | Windows, Linux, macOS | resolved latest stable Python | Python runtime | affected command fails closed |
| email | Portable runtime standard-library dependency. | chaos-engine/bootstrap.py | required | Windows, Linux, macOS | resolved latest stable Python | Python runtime | affected command fails closed |
| errno | Portable runtime standard-library dependency. | chaos-engine/dependencies.py, chaos-engine/hooks/launch.py, chaos-engine/hosts.py, chaos-engine/packs/java/maven_tools.py | required | Windows, Linux, macOS | resolved latest stable Python | Python runtime | affected command fails closed |
| fcntl | Portable runtime standard-library dependency. | chaos-engine/dependencies.py, chaos-engine/hooks/kernel.py, chaos-engine/install.py, chaos-engine/learning.py, chaos-engine/packs/java/maven_tools.py, chaos-engine/stores.py | required | Windows, Linux, macOS | resolved latest stable Python | Python runtime | affected command fails closed |
| fnmatch | Portable runtime standard-library dependency. | chaos-engine/bootstrap.py, chaos-engine/delete_guard.py, chaos-engine/secret_guard.py | required | Windows, Linux, macOS | resolved latest stable Python | Python runtime | affected command fails closed |
| functools | Portable runtime standard-library dependency. | chaos-engine/mobile_retro.py, chaos-engine/pack_binding.py | required | Windows, Linux, macOS | resolved latest stable Python | Python runtime | affected command fails closed |
| glob | Portable runtime standard-library dependency. | chaos-engine/addons/design-skills/scripts/design_qc.py, chaos-engine/delete_guard.py | required | Windows, Linux, macOS | resolved latest stable Python | Python runtime | affected command fails closed |
| grp | Portable runtime standard-library dependency. | chaos-engine/skills/omniroute/scripts/runner.py | required | Windows, Linux, macOS | resolved latest stable Python | Python runtime | affected command fails closed |
| hashlib | Portable runtime standard-library dependency. | chaos-engine/addon_catalog.py, chaos-engine/addons/design-skills/scripts/design_qc.py, chaos-engine/addons/design-skills/scripts/motion_graphics_gate.py, chaos-engine/backups_watch.py, chaos-engine/bootstrap.py, chaos-engine/context_rot.py, chaos-engine/delete_guard.py, chaos-engine/dependencies.py, chaos-engine/external_reflection.py, chaos-engine/genai_spans.py, chaos-engine/harness_mindset.py, chaos-engine/heuristics.py, chaos-engine/hooks/guard.py, chaos-engine/hooks/kernel.py, chaos-engine/hooks/reflection.py, chaos-engine/hosts.py, chaos-engine/insight_extract.py, chaos-engine/install.py, chaos-engine/learning.py, chaos-engine/learning_session.py, chaos-engine/overlay_match.py, chaos-engine/packs/java/maven_tools.py, chaos-engine/prompt_evolve.py, chaos-engine/references/details/likeness_record_train.py, chaos-engine/rules/ethics_check.py, chaos-engine/rules/memory_full_dump.py, chaos-engine/rules/web_ui_gate.py, chaos-engine/self_modify.py, chaos-engine/significance.py, chaos-engine/skills/local-agency/scripts/tip_preflight.py, chaos-engine/skills/omniroute/scripts/runner.py, chaos-engine/stores.py, chaos-engine/token_economy.py, chaos-engine/tool.py, chaos-engine/workflow_induce.py, chaos-engine/worktree_overlay.py | required | Windows, Linux, macOS | resolved latest stable Python | Python runtime | affected command fails closed |
| hmac | Portable runtime standard-library dependency. | chaos-engine/delete_guard.py, chaos-engine/hooks/reflection.py, chaos-engine/hosts.py | required | Windows, Linux, macOS | resolved latest stable Python | Python runtime | affected command fails closed |
| html | Portable runtime standard-library dependency. | chaos-engine/addons/design-skills/scripts/hosted_cms_gates.py, chaos-engine/addons/design-skills/scripts/liveseo_gates.py, chaos-engine/addons/design-skills/scripts/surface_qc.py | required | Windows, Linux, macOS | resolved latest stable Python | Python runtime | affected command fails closed |
| importlib | Portable runtime standard-library dependency. | chaos-engine/addons/design-skills/scripts/craft_qc.py, chaos-engine/addons/design-skills/scripts/design_qc.py, chaos-engine/addons/design-skills/scripts/uncaptioned_speech.py, chaos-engine/bootstrap.py, chaos-engine/corpus_split.py, chaos-engine/dependencies.py, chaos-engine/draft_skill_pr.py, chaos-engine/heuristics.py, chaos-engine/hooks/guard.py, chaos-engine/hooks/kernel.py, chaos-engine/hooks/launch.py, chaos-engine/hooks/lifecycle.py, chaos-engine/hooks/retrieve_justification.py, chaos-engine/hosts.py, chaos-engine/insight_extract.py, chaos-engine/install.py, chaos-engine/learn_traces.py, chaos-engine/learning.py, chaos-engine/learning_session.py, chaos-engine/mempalace_fast_mine.py, chaos-engine/mempalace_privacy.py, chaos-engine/meta_optimize.py, chaos-engine/official_self_heal.py, chaos-engine/overlay_match.py, chaos-engine/pack_binding.py, chaos-engine/retrieve.py, chaos-engine/rules/ethics_check.py, chaos-engine/rules/lessons_2026_11_02.py, chaos-engine/rules/lessons_2026_11_06.py, chaos-engine/rules/operation_boundary.py, chaos-engine/session_logs.py, chaos-engine/silent_verify.py, chaos-engine/skills/local-agency/scripts/dispatch.py, chaos-engine/skills/local-agency/scripts/require_rog_freetoken.py, chaos-engine/skills/local-agency/scripts/tests/test_assert_parent_rog_shell.py, chaos-engine/skills/local-agency/scripts/tip_preflight.py, chaos-engine/skills/local-coding-delegate/hardware_probe.py, chaos-engine/stores.py, chaos-engine/token_economy.py, chaos-engine/tool.py, chaos-engine/worktree_overlay.py | required | Windows, Linux, macOS | resolved latest stable Python | Python runtime | affected command fails closed |
| inspect | Portable runtime standard-library dependency. | chaos-engine/install.py, chaos-engine/mempalace_fast_mine.py | required | Windows, Linux, macOS | resolved latest stable Python | Python runtime | affected command fails closed |
| io | Portable runtime standard-library dependency. | chaos-engine/bootstrap.py, chaos-engine/hooks/guard.py, chaos-engine/hooks/launch.py, chaos-engine/hooks/lifecycle.py, chaos-engine/overlay_match.py | required | Windows, Linux, macOS | resolved latest stable Python | Python runtime | affected command fails closed |
| json | Portable runtime standard-library dependency. | chaos-engine/addon_catalog.py, chaos-engine/addons/design-skills/scripts/craft_qc.py, chaos-engine/addons/design-skills/scripts/design_qc.py, chaos-engine/addons/design-skills/scripts/linkcheck.py, chaos-engine/addons/design-skills/scripts/liveseo_gates.py, chaos-engine/addons/design-skills/scripts/motion_graphics_gate.py, chaos-engine/addons/design-skills/scripts/surface_qc.py, chaos-engine/addons/design-skills/scripts/title_scope_gate.py, chaos-engine/addons/design-skills/scripts/uncaptioned_speech.py, chaos-engine/backups_watch.py, chaos-engine/bootstrap.py, chaos-engine/ce_brief.py, chaos-engine/context_rot.py, chaos-engine/corpus_split.py, chaos-engine/deep_research.py, chaos-engine/deja_ab_measure.py, chaos-engine/delete_guard.py, chaos-engine/dependencies.py, chaos-engine/dod.py, chaos-engine/draft_skill_pr.py, chaos-engine/external_reflection.py, chaos-engine/gate_fail_closed.py, chaos-engine/genai_spans.py, chaos-engine/grok_lean_config.py, chaos-engine/harness_index.py, chaos-engine/harness_map.py, chaos-engine/harness_mindset.py, chaos-engine/heuristics.py, chaos-engine/hooks/guard.py, chaos-engine/hooks/kernel.py, chaos-engine/hooks/launch.py, chaos-engine/hooks/lifecycle.py, chaos-engine/hooks/receipt_shim.py, chaos-engine/hooks/reflection.py, chaos-engine/hooks/repeat_reminder.py, chaos-engine/hooks/retrieve_justification.py, chaos-engine/hosts.py, chaos-engine/insight_extract.py, chaos-engine/install.py, chaos-engine/intent_converge.py, chaos-engine/jobs.py, chaos-engine/learn_traces.py, chaos-engine/learn_traces_mrv.py, chaos-engine/learning.py, chaos-engine/learning_counters.py, chaos-engine/learning_session.py, chaos-engine/mcp_policy.py, chaos-engine/memory_provenance.py, chaos-engine/meta_optimize.py, chaos-engine/mobile_retro.py, chaos-engine/official_self_heal.py, chaos-engine/overlay_match.py, chaos-engine/packs/java/installer.py, chaos-engine/packs/java/maven_tools.py, chaos-engine/phase_ledger.py, chaos-engine/pre_done_review.py, chaos-engine/prerequisites.py, chaos-engine/profile_installs.py, chaos-engine/prompt_evolve.py, chaos-engine/references/details/likeness_record_train.py, chaos-engine/retrieve.py, chaos-engine/rules/ethics_check.py, chaos-engine/rules/lessons_repeat_failure_pdca.py, chaos-engine/rules/memory_full_dump.py, chaos-engine/rules/operation_boundary.py, chaos-engine/secret_guard.py, chaos-engine/self_modify.py, chaos-engine/session_token_usage.py, chaos-engine/significance.py, chaos-engine/skill_compress_audit.py, chaos-engine/skills/colibri/scripts/probe.py, chaos-engine/skills/freetoken/scripts/probe.py, chaos-engine/skills/local-agency/scripts/assert_parent_rog_shell.py, chaos-engine/skills/local-agency/scripts/design_turn_gate.py, chaos-engine/skills/local-agency/scripts/dispatch.py, chaos-engine/skills/local-agency/scripts/executor_brief.py, chaos-engine/skills/local-agency/scripts/require_rog_freetoken.py, chaos-engine/skills/local-agency/scripts/tests/test_assert_parent_rog_shell.py, chaos-engine/skills/local-agency/scripts/tip_preflight.py, chaos-engine/skills/local-coding-delegate/scripts/probe_hardware.py, chaos-engine/skills/local-openai-compat/scripts/probe.py, chaos-engine/skills/omniroute/scripts/runner.py, chaos-engine/stores.py, chaos-engine/task_ledger.py, chaos-engine/token_economy.py, chaos-engine/tool.py, chaos-engine/vendor/icm-architect/skills/icm-architect/scripts/index.py, chaos-engine/vendor/icm-architect/skills/icm-architect/scripts/links.py, chaos-engine/vendor/icm-architect/skills/icm-architect/scripts/viz.py, chaos-engine/wake_pack.py, chaos-engine/workflow_induce.py, chaos-engine/worktree_overlay.py | required | Windows, Linux, macOS | resolved latest stable Python | Python runtime | affected command fails closed |
| math | Portable runtime standard-library dependency. | chaos-engine/addons/design-skills/scripts/craft_qc.py, chaos-engine/addons/design-skills/scripts/design_qc.py, chaos-engine/addons/design-skills/scripts/hosted_cms_gates.py, chaos-engine/addons/design-skills/scripts/surface_qc.py, chaos-engine/dependencies.py | required | Windows, Linux, macOS | resolved latest stable Python | Python runtime | affected command fails closed |
| msvcrt | Portable runtime standard-library dependency. | chaos-engine/dependencies.py, chaos-engine/hooks/kernel.py, chaos-engine/install.py, chaos-engine/learning.py, chaos-engine/packs/java/maven_tools.py, chaos-engine/stores.py | required | Windows, Linux, macOS | resolved latest stable Python | Python runtime | affected command fails closed |
| multiprocessing | Portable runtime standard-library dependency. | chaos-engine/mobile_retro.py | required | Windows, Linux, macOS | resolved latest stable Python | Python runtime | affected command fails closed |
| os | Portable runtime standard-library dependency. | chaos-engine/addon_catalog.py, chaos-engine/addons/design-skills/scripts/craft_qc.py, chaos-engine/addons/design-skills/scripts/design_qc.py, chaos-engine/addons/design-skills/scripts/linkcheck.py, chaos-engine/backups_watch.py, chaos-engine/bootstrap.py, chaos-engine/client_name_scrub.py, chaos-engine/commit_identity.py, chaos-engine/consumer_mode.py, chaos-engine/delete_guard.py, chaos-engine/dependencies.py, chaos-engine/draft_skill_pr.py, chaos-engine/git_hooks.py, chaos-engine/grok_lean_config.py, chaos-engine/grok_model_load.py, chaos-engine/harness_mindset.py, chaos-engine/hooks/guard.py, chaos-engine/hooks/kernel.py, chaos-engine/hooks/launch.py, chaos-engine/hooks/lifecycle.py, chaos-engine/hooks/receipt_shim.py, chaos-engine/hooks/reflection.py, chaos-engine/hooks/retrieve_justification.py, chaos-engine/hosts.py, chaos-engine/install.py, chaos-engine/jobs.py, chaos-engine/learn_traces.py, chaos-engine/learning.py, chaos-engine/learning_session.py, chaos-engine/mcp_policy.py, chaos-engine/mempalace_fast_mine.py, chaos-engine/mobile_retro.py, chaos-engine/official_self_heal.py, chaos-engine/overlay_match.py, chaos-engine/packs/java/installer.py, chaos-engine/packs/java/maven_tools.py, chaos-engine/prerequisites.py, chaos-engine/progress_log.py, chaos-engine/radio_silence.py, chaos-engine/retrieve.py, chaos-engine/secret_guard.py, chaos-engine/session_logs.py, chaos-engine/session_token_usage.py, chaos-engine/significance.py, chaos-engine/skills/job-apply/scripts/check_abstraction.py, chaos-engine/skills/job-search/scripts/check_abstraction.py, chaos-engine/skills/local-agency/scripts/assert_parent_rog_shell.py, chaos-engine/skills/local-agency/scripts/require_rog_freetoken.py, chaos-engine/skills/local-coding-delegate/scripts/probe_hardware.py, chaos-engine/skills/omniroute/scripts/runner.py, chaos-engine/stores.py, chaos-engine/task_ledger.py, chaos-engine/tool.py, chaos-engine/vendor/icm-architect/skills/icm-architect/scripts/links.py, chaos-engine/vendor/icm-architect/skills/icm-architect/scripts/viz.py, chaos-engine/windows_py_shim.py, chaos-engine/worktree_overlay.py | required | Windows, Linux, macOS | resolved latest stable Python | Python runtime | affected command fails closed |
| pathlib | Portable runtime standard-library dependency. | chaos-engine/addon_catalog.py, chaos-engine/addons/design-skills/scripts/craft_qc.py, chaos-engine/addons/design-skills/scripts/design_qc.py, chaos-engine/addons/design-skills/scripts/linkcheck.py, chaos-engine/addons/design-skills/scripts/liveseo_gates.py, chaos-engine/addons/design-skills/scripts/motion_graphics_gate.py, chaos-engine/addons/design-skills/scripts/surface_qc.py, chaos-engine/addons/design-skills/scripts/title_scope_gate.py, chaos-engine/addons/design-skills/scripts/uncaptioned_speech.py, chaos-engine/backups_watch.py, chaos-engine/bootstrap.py, chaos-engine/ce_brief.py, chaos-engine/client_name_scrub.py, chaos-engine/commit_identity.py, chaos-engine/consumer_mode.py, chaos-engine/content_scan_preflight.py, chaos-engine/context_rot.py, chaos-engine/corpus_split.py, chaos-engine/deep_research.py, chaos-engine/deja_ab_measure.py, chaos-engine/delete_guard.py, chaos-engine/dependencies.py, chaos-engine/draft_skill_pr.py, chaos-engine/external_reflection.py, chaos-engine/force_push_approve.py, chaos-engine/gate_fail_closed.py, chaos-engine/genai_spans.py, chaos-engine/git_hooks.py, chaos-engine/grok_lean_config.py, chaos-engine/grok_model_load.py, chaos-engine/harness_index.py, chaos-engine/harness_map.py, chaos-engine/harness_mindset.py, chaos-engine/heuristics.py, chaos-engine/hooks/guard.py, chaos-engine/hooks/kernel.py, chaos-engine/hooks/launch.py, chaos-engine/hooks/lifecycle.py, chaos-engine/hooks/receipt_shim.py, chaos-engine/hooks/reflection.py, chaos-engine/hooks/retrieve_justification.py, chaos-engine/hosts.py, chaos-engine/identity_md.py, chaos-engine/insight_extract.py, chaos-engine/install.py, chaos-engine/intent_converge.py, chaos-engine/jobs.py, chaos-engine/learn_traces.py, chaos-engine/learn_traces_mrv.py, chaos-engine/learning.py, chaos-engine/learning_counters.py, chaos-engine/learning_session.py, chaos-engine/mcp_policy.py, chaos-engine/memory_provenance.py, chaos-engine/mempalace_fast_mine.py, chaos-engine/mempalace_privacy.py, chaos-engine/meta_optimize.py, chaos-engine/mobile_retro.py, chaos-engine/official_self_heal.py, chaos-engine/overlay_match.py, chaos-engine/pack_binding.py, chaos-engine/packs/java/installer.py, chaos-engine/packs/java/maven_tools.py, chaos-engine/phase_ledger.py, chaos-engine/pre_done_review.py, chaos-engine/prerequisites.py, chaos-engine/profile_installs.py, chaos-engine/progress_log.py, chaos-engine/prompt_evolve.py, chaos-engine/radio_silence.py, chaos-engine/references/details/likeness_record_train.py, chaos-engine/retrieve.py, chaos-engine/rules/ethics_check.py, chaos-engine/rules/lessons_2026_11_01.py, chaos-engine/rules/lessons_2026_11_02.py, chaos-engine/rules/lessons_2026_11_06.py, chaos-engine/rules/lessons_l82_l92.py, chaos-engine/rules/lessons_repeat_failure_pdca.py, chaos-engine/rules/memory_full_dump.py, chaos-engine/rules/no_probe_live.py, chaos-engine/rules/operation_boundary.py, chaos-engine/rules/remote_credential_guard.py, chaos-engine/rules/web_ui_gate.py, chaos-engine/secret_guard.py, chaos-engine/self_modify.py, chaos-engine/session_logs.py, chaos-engine/session_token_usage.py, chaos-engine/significance.py, chaos-engine/silent_verify.py, chaos-engine/skill_compress_audit.py, chaos-engine/skills/job-apply/scripts/check_abstraction.py, chaos-engine/skills/job-search/scripts/check_abstraction.py, chaos-engine/skills/local-agency/scripts/assert_parent_rog_shell.py, chaos-engine/skills/local-agency/scripts/design_turn_gate.py, chaos-engine/skills/local-agency/scripts/dispatch.py, chaos-engine/skills/local-agency/scripts/executor_brief.py, chaos-engine/skills/local-agency/scripts/require_rog_freetoken.py, chaos-engine/skills/local-agency/scripts/tests/test_assert_parent_rog_shell.py, chaos-engine/skills/local-agency/scripts/tip_preflight.py, chaos-engine/skills/local-agency/scripts/worker_ce_entry.py, chaos-engine/skills/local-coding-delegate/hardware_probe.py, chaos-engine/skills/local-coding-delegate/scripts/probe_hardware.py, chaos-engine/skills/omniroute/scripts/runner.py, chaos-engine/stores.py, chaos-engine/task_ledger.py, chaos-engine/token_economy.py, chaos-engine/tool.py, chaos-engine/tool_output_store.py, chaos-engine/vendor/icm-architect/skills/icm-architect/scripts/index.py, chaos-engine/vendor/icm-architect/skills/icm-architect/scripts/links.py, chaos-engine/vendor/icm-architect/skills/icm-architect/scripts/quotes.py, chaos-engine/vendor/icm-architect/skills/icm-architect/scripts/viz.py, chaos-engine/wake_pack.py, chaos-engine/workflow_induce.py, chaos-engine/worktree_overlay.py | required | Windows, Linux, macOS | resolved latest stable Python | Python runtime | affected command fails closed |
| platform | Portable runtime standard-library dependency. | chaos-engine/bootstrap.py, chaos-engine/dependencies.py, chaos-engine/hosts.py, chaos-engine/skills/local-coding-delegate/scripts/probe_hardware.py | required | Windows, Linux, macOS | resolved latest stable Python | Python runtime | affected command fails closed |
| posixpath | Portable runtime standard-library dependency. | chaos-engine/hooks/guard.py | required | Windows, Linux, macOS | resolved latest stable Python | Python runtime | affected command fails closed |
| pwd | Portable runtime standard-library dependency. | chaos-engine/skills/omniroute/scripts/runner.py | required | Windows, Linux, macOS | resolved latest stable Python | Python runtime | affected command fails closed |
| queue | Portable runtime standard-library dependency. | chaos-engine/packs/java/maven_tools.py | required | Windows, Linux, macOS | resolved latest stable Python | Python runtime | affected command fails closed |
| re | Portable runtime standard-library dependency. | chaos-engine/addon_catalog.py, chaos-engine/addons/design-skills/scripts/craft_qc.py, chaos-engine/addons/design-skills/scripts/design_qc.py, chaos-engine/addons/design-skills/scripts/hosted_cms_gates.py, chaos-engine/addons/design-skills/scripts/linkcheck.py, chaos-engine/addons/design-skills/scripts/liveseo_gates.py, chaos-engine/addons/design-skills/scripts/motion_graphics_gate.py, chaos-engine/addons/design-skills/scripts/surface_qc.py, chaos-engine/addons/design-skills/scripts/title_scope_gate.py, chaos-engine/addons/design-skills/scripts/uncaptioned_speech.py, chaos-engine/bootstrap.py, chaos-engine/commit_identity.py, chaos-engine/content_scan_preflight.py, chaos-engine/context_rot.py, chaos-engine/corpus_split.py, chaos-engine/delete_guard.py, chaos-engine/dependencies.py, chaos-engine/dod.py, chaos-engine/enhancement_disposition.py, chaos-engine/external_reflection.py, chaos-engine/genai_spans.py, chaos-engine/grok_lean_config.py, chaos-engine/grok_model_load.py, chaos-engine/harness_map.py, chaos-engine/harness_mindset.py, chaos-engine/heuristics.py, chaos-engine/hooks/guard.py, chaos-engine/hooks/kernel.py, chaos-engine/hooks/launch.py, chaos-engine/hooks/reflection.py, chaos-engine/hooks/retrieve_justification.py, chaos-engine/hosts.py, chaos-engine/insight_extract.py, chaos-engine/install.py, chaos-engine/intent_converge.py, chaos-engine/jobs.py, chaos-engine/learn_traces.py, chaos-engine/learn_traces_mrv.py, chaos-engine/learning.py, chaos-engine/mcp_policy.py, chaos-engine/memory_provenance.py, chaos-engine/mempalace_privacy.py, chaos-engine/overlay_match.py, chaos-engine/packs/java/installer.py, chaos-engine/packs/java/maven_tools.py, chaos-engine/phase_ledger.py, chaos-engine/pre_done_review.py, chaos-engine/prerequisites.py, chaos-engine/prompt_evolve.py, chaos-engine/retrieve.py, chaos-engine/rules/lessons_2026_11_01.py, chaos-engine/rules/lessons_2026_11_06.py, chaos-engine/rules/lessons_l82_l92.py, chaos-engine/rules/mega_pr.py, chaos-engine/rules/memory_full_dump.py, chaos-engine/rules/operation_boundary.py, chaos-engine/rules/orchestrator_pre_publish.py, chaos-engine/rules/public_facts.py, chaos-engine/rules/remote_credential_guard.py, chaos-engine/rules/verify_dropped.py, chaos-engine/secret_guard.py, chaos-engine/self_modify.py, chaos-engine/session_token_usage.py, chaos-engine/significance.py, chaos-engine/skill_compress_audit.py, chaos-engine/skills/job-apply/scripts/check_abstraction.py, chaos-engine/skills/job-search/scripts/check_abstraction.py, chaos-engine/skills/local-agency/scripts/design_turn_gate.py, chaos-engine/skills/local-agency/scripts/executor_brief.py, chaos-engine/skills/local-agency/scripts/tip_preflight.py, chaos-engine/skills/local-agency/scripts/worker_ce_entry.py, chaos-engine/skills/omniroute/scripts/runner.py, chaos-engine/stores.py, chaos-engine/task_ledger.py, chaos-engine/tool.py, chaos-engine/vendor/icm-architect/skills/icm-architect/scripts/index.py, chaos-engine/vendor/icm-architect/skills/icm-architect/scripts/links.py, chaos-engine/vendor/icm-architect/skills/icm-architect/scripts/quotes.py, chaos-engine/vendor/icm-architect/skills/icm-architect/scripts/viz.py, chaos-engine/windows_py_shim.py, chaos-engine/workflow_induce.py | required | Windows, Linux, macOS | resolved latest stable Python | Python runtime | affected command fails closed |
| runpy | Portable runtime standard-library dependency. | chaos-engine/bootstrap.py, chaos-engine/dependencies.py, chaos-engine/hooks/guard.py, chaos-engine/hooks/launch.py, chaos-engine/install.py, chaos-engine/retrieve.py, chaos-engine/tool.py, chaos-engine/tool_output_store.py | required | Windows, Linux, macOS | resolved latest stable Python | Python runtime | affected command fails closed |
| secrets | Portable runtime standard-library dependency. | chaos-engine/delete_guard.py, chaos-engine/dependencies.py, chaos-engine/hooks/reflection.py, chaos-engine/hosts.py, chaos-engine/install.py, chaos-engine/overlay_match.py, chaos-engine/packs/java/maven_tools.py, chaos-engine/stores.py | required | Windows, Linux, macOS | resolved latest stable Python | Python runtime | affected command fails closed |
| shlex | Portable runtime standard-library dependency. | chaos-engine/addons/design-skills/scripts/design_qc.py, chaos-engine/bootstrap.py, chaos-engine/delete_guard.py, chaos-engine/dependencies.py, chaos-engine/hooks/guard.py, chaos-engine/hooks/reflection.py, chaos-engine/hooks/retrieve_justification.py, chaos-engine/skills/omniroute/scripts/runner.py, chaos-engine/tool_output_store.py | required | Windows, Linux, macOS | resolved latest stable Python | Python runtime | affected command fails closed |
| shutil | Portable runtime standard-library dependency. | chaos-engine/addons/design-skills/scripts/design_qc.py, chaos-engine/addons/design-skills/scripts/linkcheck.py, chaos-engine/addons/design-skills/scripts/liveseo_gates.py, chaos-engine/backups_watch.py, chaos-engine/bootstrap.py, chaos-engine/commit_identity.py, chaos-engine/dependencies.py, chaos-engine/dod.py, chaos-engine/draft_skill_pr.py, chaos-engine/git_hooks.py, chaos-engine/grok_lean_config.py, chaos-engine/hooks/guard.py, chaos-engine/hosts.py, chaos-engine/install.py, chaos-engine/jobs.py, chaos-engine/mobile_retro.py, chaos-engine/official_self_heal.py, chaos-engine/packs/java/installer.py, chaos-engine/packs/java/maven_tools.py, chaos-engine/prerequisites.py, chaos-engine/references/details/likeness_record_train.py, chaos-engine/secret_guard.py, chaos-engine/skills/colibri/scripts/probe.py, chaos-engine/skills/freetoken/scripts/probe.py, chaos-engine/skills/local-agency/scripts/dispatch.py, chaos-engine/skills/local-agency/scripts/tip_preflight.py, chaos-engine/skills/local-openai-compat/scripts/probe.py, chaos-engine/skills/omniroute/scripts/runner.py, chaos-engine/stores.py, chaos-engine/tool.py, chaos-engine/worktree_overlay.py | required | Windows, Linux, macOS | resolved latest stable Python | Python runtime | affected command fails closed |
| signal | Portable runtime standard-library dependency. | chaos-engine/install.py, chaos-engine/jobs.py, chaos-engine/skills/omniroute/scripts/runner.py | required | Windows, Linux, macOS | resolved latest stable Python | Python runtime | affected command fails closed |
| socket | Portable runtime standard-library dependency. | chaos-engine/jobs.py, chaos-engine/skills/local-agency/scripts/assert_parent_rog_shell.py, chaos-engine/skills/local-agency/scripts/require_rog_freetoken.py, chaos-engine/skills/local-agency/scripts/tests/test_assert_parent_rog_shell.py | required | Windows, Linux, macOS | resolved latest stable Python | Python runtime | affected command fails closed |
| sqlite3 | Portable runtime standard-library dependency. | chaos-engine/corpus_split.py, chaos-engine/dependencies.py, chaos-engine/hosts.py, chaos-engine/mempalace_privacy.py, chaos-engine/retrieve.py, chaos-engine/stores.py, chaos-engine/tool_output_store.py | required | Windows, Linux, macOS | resolved latest stable Python | Python runtime | affected command fails closed |
| ssl | Portable runtime standard-library dependency. | chaos-engine/bootstrap.py | required | Windows, Linux, macOS | resolved latest stable Python | Python runtime | affected command fails closed |
| stat | Portable runtime standard-library dependency. | chaos-engine/delete_guard.py, chaos-engine/dependencies.py, chaos-engine/git_hooks.py, chaos-engine/hosts.py, chaos-engine/packs/java/installer.py, chaos-engine/packs/java/maven_tools.py, chaos-engine/skills/omniroute/scripts/runner.py | required | Windows, Linux, macOS | resolved latest stable Python | Python runtime | affected command fails closed |
| statistics | Portable runtime standard-library dependency. | chaos-engine/addons/design-skills/scripts/craft_qc.py | required | Windows, Linux, macOS | resolved latest stable Python | Python runtime | affected command fails closed |
| struct | Portable runtime standard-library dependency. | chaos-engine/addons/design-skills/scripts/craft_qc.py, chaos-engine/addons/design-skills/scripts/surface_qc.py | required | Windows, Linux, macOS | resolved latest stable Python | Python runtime | affected command fails closed |
| subprocess | Portable runtime standard-library dependency. | chaos-engine/addons/design-skills/scripts/craft_qc.py, chaos-engine/addons/design-skills/scripts/design_qc.py, chaos-engine/addons/design-skills/scripts/linkcheck.py, chaos-engine/addons/design-skills/scripts/liveseo_gates.py, chaos-engine/backups_watch.py, chaos-engine/bootstrap.py, chaos-engine/client_name_scrub.py, chaos-engine/commit_identity.py, chaos-engine/consumer_mode.py, chaos-engine/corpus_split.py, chaos-engine/deja_ab_measure.py, chaos-engine/delete_guard.py, chaos-engine/dependencies.py, chaos-engine/dod.py, chaos-engine/draft_skill_pr.py, chaos-engine/force_push_approve.py, chaos-engine/git_hooks.py, chaos-engine/grok_lean_config.py, chaos-engine/harness_mindset.py, chaos-engine/hooks/guard.py, chaos-engine/hooks/retrieve_justification.py, chaos-engine/hosts.py, chaos-engine/install.py, chaos-engine/jobs.py, chaos-engine/learning.py, chaos-engine/learning_session.py, chaos-engine/mcp_policy.py, chaos-engine/mobile_retro.py, chaos-engine/overlay_match.py, chaos-engine/packs/java/installer.py, chaos-engine/packs/java/maven_tools.py, chaos-engine/prerequisites.py, chaos-engine/references/details/likeness_record_train.py, chaos-engine/retrieve.py, chaos-engine/rules/operation_boundary.py, chaos-engine/rules/remote_credential_guard.py, chaos-engine/secret_guard.py, chaos-engine/silent_verify.py, chaos-engine/skills/local-agency/scripts/tests/test_assert_parent_rog_shell.py, chaos-engine/skills/local-agency/scripts/tip_preflight.py, chaos-engine/skills/local-coding-delegate/scripts/probe_hardware.py, chaos-engine/skills/omniroute/scripts/runner.py, chaos-engine/stores.py, chaos-engine/tool.py, chaos-engine/windows_py_shim.py, chaos-engine/worktree_overlay.py | required | Windows, Linux, macOS | resolved latest stable Python | Python runtime | affected command fails closed |
| sys | Portable runtime standard-library dependency. | chaos-engine/addon_catalog.py, chaos-engine/addons/design-skills/scripts/design_qc.py, chaos-engine/addons/design-skills/scripts/linkcheck.py, chaos-engine/addons/design-skills/scripts/title_scope_gate.py, chaos-engine/backups_watch.py, chaos-engine/bootstrap.py, chaos-engine/ce_brief.py, chaos-engine/commit_identity.py, chaos-engine/content_scan_preflight.py, chaos-engine/deep_research.py, chaos-engine/deja_ab_measure.py, chaos-engine/delete_guard.py, chaos-engine/dependencies.py, chaos-engine/dod.py, chaos-engine/draft_skill_pr.py, chaos-engine/force_push_approve.py, chaos-engine/harness_index.py, chaos-engine/harness_map.py, chaos-engine/hooks/guard.py, chaos-engine/hooks/kernel.py, chaos-engine/hooks/launch.py, chaos-engine/hooks/lifecycle.py, chaos-engine/hooks/receipt_shim.py, chaos-engine/hooks/reflection.py, chaos-engine/hooks/repeat_reminder.py, chaos-engine/hosts.py, chaos-engine/install.py, chaos-engine/intent_converge.py, chaos-engine/jobs.py, chaos-engine/learn_traces.py, chaos-engine/learning.py, chaos-engine/learning_session.py, chaos-engine/mempalace_fast_mine.py, chaos-engine/mempalace_privacy.py, chaos-engine/mobile_retro.py, chaos-engine/overlay_match.py, chaos-engine/pack_binding.py, chaos-engine/packs/java/installer.py, chaos-engine/packs/java/maven_tools.py, chaos-engine/pre_done_review.py, chaos-engine/prerequisites.py, chaos-engine/profile_installs.py, chaos-engine/references/details/likeness_record_train.py, chaos-engine/retrieve.py, chaos-engine/rules/ethics_check.py, chaos-engine/rules/lessons_2026_11_02.py, chaos-engine/rules/operation_boundary.py, chaos-engine/rules/remote_credential_guard.py, chaos-engine/secret_guard.py, chaos-engine/session_token_usage.py, chaos-engine/silent_verify.py, chaos-engine/skills/colibri/scripts/probe.py, chaos-engine/skills/freetoken/scripts/probe.py, chaos-engine/skills/job-apply/scripts/check_abstraction.py, chaos-engine/skills/job-search/scripts/check_abstraction.py, chaos-engine/skills/local-agency/scripts/assert_parent_rog_shell.py, chaos-engine/skills/local-agency/scripts/dispatch.py, chaos-engine/skills/local-agency/scripts/executor_brief.py, chaos-engine/skills/local-agency/scripts/require_rog_freetoken.py, chaos-engine/skills/local-agency/scripts/tests/test_assert_parent_rog_shell.py, chaos-engine/skills/local-agency/scripts/tip_preflight.py, chaos-engine/skills/local-agency/scripts/worker_ce_entry.py, chaos-engine/skills/local-coding-delegate/scripts/probe_hardware.py, chaos-engine/skills/local-openai-compat/scripts/probe.py, chaos-engine/skills/omniroute/scripts/runner.py, chaos-engine/stores.py, chaos-engine/task_ledger.py, chaos-engine/tool.py, chaos-engine/tool_output_store.py, chaos-engine/vendor/icm-architect/skills/icm-architect/scripts/index.py, chaos-engine/vendor/icm-architect/skills/icm-architect/scripts/links.py, chaos-engine/vendor/icm-architect/skills/icm-architect/scripts/quotes.py, chaos-engine/vendor/icm-architect/skills/icm-architect/scripts/viz.py, chaos-engine/windows_py_shim.py, chaos-engine/worktree_overlay.py | required | Windows, Linux, macOS | resolved latest stable Python | Python runtime | affected command fails closed |
| tarfile | Portable runtime standard-library dependency. | chaos-engine/bootstrap.py, chaos-engine/dependencies.py, chaos-engine/overlay_match.py | required | Windows, Linux, macOS | resolved latest stable Python | Python runtime | affected command fails closed |
| tempfile | Portable runtime standard-library dependency. | chaos-engine/addons/design-skills/scripts/craft_qc.py, chaos-engine/addons/design-skills/scripts/design_qc.py, chaos-engine/addons/design-skills/scripts/liveseo_gates.py, chaos-engine/bootstrap.py, chaos-engine/content_scan_preflight.py, chaos-engine/delete_guard.py, chaos-engine/harness_mindset.py, chaos-engine/hooks/launch.py, chaos-engine/hooks/reflection.py, chaos-engine/hooks/retrieve_justification.py, chaos-engine/install.py, chaos-engine/learning.py, chaos-engine/overlay_match.py, chaos-engine/packs/java/installer.py, chaos-engine/prerequisites.py, chaos-engine/skills/local-agency/scripts/dispatch.py, chaos-engine/skills/omniroute/scripts/runner.py, chaos-engine/stores.py, chaos-engine/tool.py | required | Windows, Linux, macOS | resolved latest stable Python | Python runtime | affected command fails closed |
| textwrap | Portable runtime standard-library dependency. | chaos-engine/bootstrap.py | required | Windows, Linux, macOS | resolved latest stable Python | Python runtime | affected command fails closed |
| threading | Portable runtime standard-library dependency. | chaos-engine/bootstrap.py, chaos-engine/hooks/kernel.py, chaos-engine/learning.py, chaos-engine/packs/java/maven_tools.py, chaos-engine/prerequisites.py, chaos-engine/skills/omniroute/scripts/runner.py | required | Windows, Linux, macOS | resolved latest stable Python | Python runtime | affected command fails closed |
| time | Portable runtime standard-library dependency. | chaos-engine/addons/design-skills/scripts/design_qc.py, chaos-engine/backups_watch.py, chaos-engine/bootstrap.py, chaos-engine/delete_guard.py, chaos-engine/dependencies.py, chaos-engine/draft_skill_pr.py, chaos-engine/external_reflection.py, chaos-engine/harness_mindset.py, chaos-engine/heuristics.py, chaos-engine/hooks/kernel.py, chaos-engine/hooks/launch.py, chaos-engine/hooks/receipt_shim.py, chaos-engine/hooks/retrieve_justification.py, chaos-engine/insight_extract.py, chaos-engine/install.py, chaos-engine/jobs.py, chaos-engine/learning.py, chaos-engine/learning_counters.py, chaos-engine/memory_provenance.py, chaos-engine/meta_optimize.py, chaos-engine/mobile_retro.py, chaos-engine/packs/java/installer.py, chaos-engine/packs/java/maven_tools.py, chaos-engine/phase_ledger.py, chaos-engine/prerequisites.py, chaos-engine/session_token_usage.py, chaos-engine/significance.py, chaos-engine/skills/omniroute/scripts/runner.py, chaos-engine/stores.py, chaos-engine/task_ledger.py, chaos-engine/tool.py, chaos-engine/tool_output_store.py, chaos-engine/workflow_induce.py, chaos-engine/worktree_overlay.py | required | Windows, Linux, macOS | resolved latest stable Python | Python runtime | affected command fails closed |
| tomllib | Portable runtime standard-library dependency. | chaos-engine/overlay_match.py | required | Windows, Linux, macOS | resolved latest stable Python | Python runtime | affected command fails closed |
| traceback | Portable runtime standard-library dependency. | chaos-engine/bootstrap.py | required | Windows, Linux, macOS | resolved latest stable Python | Python runtime | affected command fails closed |
| types | Portable runtime standard-library dependency. | chaos-engine/bootstrap.py, chaos-engine/hooks/kernel.py, chaos-engine/install.py, chaos-engine/pack_binding.py, chaos-engine/skills/local-agency/scripts/dispatch.py | required | Windows, Linux, macOS | resolved latest stable Python | Python runtime | affected command fails closed |
| typing | Portable runtime standard-library dependency. | chaos-engine/addons/design-skills/scripts/hosted_cms_gates.py, chaos-engine/addons/design-skills/scripts/hosted_cms_live.py, chaos-engine/addons/design-skills/scripts/human_cue.py, chaos-engine/addons/design-skills/scripts/liveseo_gates.py, chaos-engine/addons/design-skills/scripts/motion_graphics_gate.py, chaos-engine/addons/design-skills/scripts/uncaptioned_speech.py, chaos-engine/client_name_scrub.py, chaos-engine/context_rot.py, chaos-engine/delete_guard.py, chaos-engine/draft_skill_pr.py, chaos-engine/external_reflection.py, chaos-engine/gate_fail_closed.py, chaos-engine/genai_spans.py, chaos-engine/harness_mindset.py, chaos-engine/heuristics.py, chaos-engine/hooks/kernel.py, chaos-engine/insight_extract.py, chaos-engine/jobs.py, chaos-engine/learning_counters.py, chaos-engine/memory_provenance.py, chaos-engine/meta_optimize.py, chaos-engine/mobile_retro.py, chaos-engine/moving_channel_pin.py, chaos-engine/official_self_heal.py, chaos-engine/phase_ledger.py, chaos-engine/prompt_evolve.py, chaos-engine/retrieve.py, chaos-engine/rules/avatar_likeness_gate.py, chaos-engine/rules/cms_block_identity.py, chaos-engine/rules/design_fix_loop.py, chaos-engine/rules/gate_proven_red.py, chaos-engine/rules/lessons_2026_11_01.py, chaos-engine/rules/lessons_2026_11_02.py, chaos-engine/rules/lessons_2026_11_06.py, chaos-engine/rules/lessons_l82_l92.py, chaos-engine/rules/lessons_repeat_failure_pdca.py, chaos-engine/rules/memory_full_dump.py, chaos-engine/rules/no_probe_live.py, chaos-engine/rules/operation_boundary.py, chaos-engine/rules/orchestrator_pre_publish.py, chaos-engine/rules/preview_at_real_width.py, chaos-engine/rules/public_facts.py, chaos-engine/rules/remote_credential_guard.py, chaos-engine/rules/verify_dropped.py, chaos-engine/rules/web_ui_gate.py, chaos-engine/secret_guard.py, chaos-engine/self_modify.py, chaos-engine/significance.py, chaos-engine/silent_verify.py, chaos-engine/skill_compress_audit.py, chaos-engine/skills/omniroute/scripts/proof.py, chaos-engine/skills/omniroute/scripts/runner.py, chaos-engine/stores.py, chaos-engine/workflow_induce.py | required | Windows, Linux, macOS | resolved latest stable Python | Python runtime | affected command fails closed |
| unicodedata | Portable runtime standard-library dependency. | chaos-engine/addons/design-skills/scripts/craft_qc.py | required | Windows, Linux, macOS | resolved latest stable Python | Python runtime | affected command fails closed |
| urllib | Portable runtime standard-library dependency. | chaos-engine/addons/design-skills/scripts/hosted_cms_live.py, chaos-engine/addons/design-skills/scripts/liveseo_gates.py, chaos-engine/bootstrap.py, chaos-engine/delete_guard.py, chaos-engine/dependencies.py, chaos-engine/learning.py, chaos-engine/packs/java/maven_tools.py, chaos-engine/prerequisites.py, chaos-engine/rules/remote_credential_guard.py, chaos-engine/skills/colibri/scripts/probe.py, chaos-engine/skills/freetoken/scripts/probe.py, chaos-engine/skills/local-agency/scripts/dispatch.py, chaos-engine/skills/local-openai-compat/scripts/probe.py, chaos-engine/skills/omniroute/scripts/runner.py, chaos-engine/vendor/icm-architect/skills/icm-architect/scripts/index.py, chaos-engine/vendor/icm-architect/skills/icm-architect/scripts/links.py, chaos-engine/vendor/icm-architect/skills/icm-architect/scripts/viz.py | required | Windows, Linux, macOS | resolved latest stable Python | Python runtime | affected command fails closed |
| uuid | Portable runtime standard-library dependency. | chaos-engine/jobs.py | required | Windows, Linux, macOS | resolved latest stable Python | Python runtime | affected command fails closed |
| wave | Portable runtime standard-library dependency. | chaos-engine/addons/design-skills/scripts/craft_qc.py | required | Windows, Linux, macOS | resolved latest stable Python | Python runtime | affected command fails closed |
| winreg | Portable runtime standard-library dependency. | chaos-engine/dependencies.py, chaos-engine/packs/java/installer.py | required | Windows, Linux, macOS | resolved latest stable Python | Python runtime | affected command fails closed |
| xml | Portable runtime standard-library dependency. | chaos-engine/addons/design-skills/scripts/surface_qc.py | required | Windows, Linux, macOS | resolved latest stable Python | Python runtime | affected command fails closed |
| zipfile | Portable runtime standard-library dependency. | chaos-engine/addons/design-skills/scripts/craft_qc.py, chaos-engine/addons/design-skills/scripts/surface_qc.py, chaos-engine/dependencies.py, chaos-engine/install.py | required | Windows, Linux, macOS | resolved latest stable Python | Python runtime | affected command fails closed |
<!-- inventory:python-libraries:end -->

### Managed Dependencies

<!-- inventory:managed-dependencies:start -->
| Item | Purpose | Source of truth | Status | Platforms | Provisioner | Owner | Failure behavior |
| --- | --- | --- | --- | --- | --- | --- | --- |
| graphify | Managed commands: graphify; packages: graphifyy==0.9.105, tree-sitter-sql==0.3.11. | chaos-engine/dependencies.json | required | Windows, Linux, macOS | immutable generation installer | installer receipt | repair full candidate or retain prior active generation |
| memory | Managed commands: memory, memory-mcp; packages: @aictx/memory@0.2.1. | chaos-engine/dependencies.json | required | Windows, Linux, macOS | immutable generation installer | installer receipt | repair full candidate or retain prior active generation |
| mempalace | Managed commands: mempalace, mempalace-mcp; packages: mempalace==3.11.0, chromadb==1.5.9. | chaos-engine/dependencies.json | required | Windows, Linux, macOS | immutable generation installer | installer receipt | repair full candidate or retain prior active generation |
| uv | Managed commands: uv; packages: uv==0.13.7. | chaos-engine/dependencies.json | required | Windows, Linux, macOS | immutable generation installer | installer receipt | repair full candidate or retain prior active generation |
<!-- inventory:managed-dependencies:end -->

### Skills

<!-- inventory:skills:start -->
| Item | Purpose | Source of truth | Status | Platforms | Provisioner | Owner | Failure behavior |
| --- | --- | --- | --- | --- | --- | --- | --- |
| architect | >- | chaos-engine/skills/architect/SKILL.md | optional routed | all hosts | core or pinned vendor installer | skill package | required skill blocks routing; optional skill reports capability gap |
| chaos-engine | >- | chaos-engine/skills/chaos-engine/SKILL.md | required | all hosts | core or pinned vendor installer | canonical skill | required skill blocks routing; optional skill reports capability gap |
| ci-cd | >- | chaos-engine/skills/ci-cd/SKILL.md | optional routed | all hosts | core or pinned vendor installer | skill package | required skill blocks routing; optional skill reports capability gap |
| colibri | >- | chaos-engine/skills/colibri/SKILL.md | optional routed | all hosts | core or pinned vendor installer | skill package | required skill blocks routing; optional skill reports capability gap |
| docs-hygiene | Use when editing source-of-truth docs or status tables: three sources, Done / In progress / Not started, and live hour formulas. On demand only. | chaos-engine/skills/docs-hygiene/SKILL.md | optional routed | all hosts | core or pinned vendor installer | skill package | required skill blocks routing; optional skill reports capability gap |
| freetoken | >- | chaos-engine/skills/freetoken/SKILL.md | optional routed | all hosts | core or pinned vendor installer | skill package | required skill blocks routing; optional skill reports capability gap |
| git-cleanup | Use when a git worktree is dirty or another local branch or worktree exists. Ask before cleanup unless the session is unattended. | chaos-engine/skills/git-cleanup/SKILL.md | optional routed | all hosts | core or pinned vendor installer | skill package | required skill blocks routing; optional skill reports capability gap |
| job-applications | Use when applying to jobs for the user by email, LinkedIn, or an ATS form. | chaos-engine/skills/job-applications/SKILL.md | optional routed | all hosts | core or pinned vendor installer | skill package | required skill blocks routing; optional skill reports capability gap |
| job-apply | >- | chaos-engine/skills/job-apply/SKILL.md | optional routed | all hosts | core or pinned vendor installer | skill package | required skill blocks routing; optional skill reports capability gap |
| job-search | >- | chaos-engine/skills/job-search/SKILL.md | optional routed | all hosts | core or pinned vendor installer | skill package | required skill blocks routing; optional skill reports capability gap |
| kanban | >- | chaos-engine/skills/kanban/SKILL.md | optional routed | all hosts | core or pinned vendor installer | skill package | required skill blocks routing; optional skill reports capability gap |
| learn-from-external-harnesses | >- | chaos-engine/skills/learn-from-external-harnesses/SKILL.md | optional routed | all hosts | core or pinned vendor installer | skill package | required skill blocks routing; optional skill reports capability gap |
| local-agency | >- | chaos-engine/skills/local-agency/SKILL.md | optional routed | all hosts | core or pinned vendor installer | skill package | required skill blocks routing; optional skill reports capability gap |
| local-coding-delegate | >- | chaos-engine/skills/local-coding-delegate/SKILL.md | optional routed | all hosts | core or pinned vendor installer | skill package | required skill blocks routing; optional skill reports capability gap |
| local-openai-compat | >- | chaos-engine/skills/local-openai-compat/SKILL.md | optional routed | all hosts | core or pinned vendor installer | skill package | required skill blocks routing; optional skill reports capability gap |
| local-runtimes | >- | chaos-engine/skills/local-runtimes/SKILL.md | optional routed | all hosts | core or pinned vendor installer | skill package | required skill blocks routing; optional skill reports capability gap |
| omniroute | >- | chaos-engine/skills/omniroute/SKILL.md | optional routed | all hosts | core or pinned vendor installer | skill package | required skill blocks routing; optional skill reports capability gap |
| pre-done-self-review | >- | chaos-engine/skills/pre-done-self-review/SKILL.md | optional routed | all hosts | core or pinned vendor installer | skill package | required skill blocks routing; optional skill reports capability gap |
| security-audit | >- | chaos-engine/skills/security-audit/SKILL.md | optional routed | all hosts | core or pinned vendor installer | skill package | required skill blocks routing; optional skill reports capability gap |
| self-improve | >- | chaos-engine/skills/self-improve/SKILL.md | optional routed | all hosts | core or pinned vendor installer | skill package | required skill blocks routing; optional skill reports capability gap |
| technical-presentations | >- | chaos-engine/skills/technical-presentations/SKILL.md | optional routed | all hosts | core or pinned vendor installer | skill package | required skill blocks routing; optional skill reports capability gap |
| work-item | >- | chaos-engine/skills/work-item/SKILL.md | optional routed | all hosts | core or pinned vendor installer | skill package | required skill blocks routing; optional skill reports capability gap |
| caveman | > | chaos-engine/vendor/caveman/skills/caveman/SKILL.md | required | all hosts | core or pinned vendor installer | skill package | required skill blocks routing; optional skill reports capability gap |
| ultracave | > | chaos-engine/vendor/caveman/skills/ultracave/SKILL.md | optional routed | all hosts | core or pinned vendor installer | skill package | required skill blocks routing; optional skill reports capability gap |
| icm-architect | Design a process, idea or body of knowledge into an ICM (Interpretable Context Methodology) workspace, where folder structure is the agent architecture, or restructure an existing folder, repo or vault into one. Use for "make this an ICM", "ICM this", "build me a workspace", "structure this for agents", "map this repo", "audit this folder", "what would a change hit", a second brain, team brain or context map, or turning transcripts and research into material for lectures, scripts or docs. | chaos-engine/vendor/icm-architect/skills/icm-architect/SKILL.md | optional routed | all hosts | core or pinned vendor installer | skill package | required skill blocks routing; optional skill reports capability gap |
| ponytail | > | chaos-engine/vendor/ponytail/skills/ponytail/SKILL.md | required | all hosts | core or pinned vendor installer | skill package | required skill blocks routing; optional skill reports capability gap |
<!-- inventory:skills:end -->

### Hosts

<!-- inventory:hosts:start -->
| Item | Purpose | Source of truth | Status | Platforms | Provisioner | Owner | Failure behavior |
| --- | --- | --- | --- | --- | --- | --- | --- |
| claude | Thin native event and JSON protocol adapter. | chaos-engine/hooks/kernel.py; chaos-engine/hosts.py | supported adapter | Windows, Linux, macOS | host installer | provider-neutral kernel | unsupported native events remain explicit capability gaps |
| codex | Thin native event and JSON protocol adapter. | chaos-engine/hooks/kernel.py; chaos-engine/hosts.py | supported adapter | Windows, Linux, macOS | host installer | provider-neutral kernel | unsupported native events remain explicit capability gaps |
| copilot | Thin native event and JSON protocol adapter. | chaos-engine/hooks/kernel.py; chaos-engine/hosts.py | supported adapter | Windows, Linux, macOS | host installer | provider-neutral kernel | unsupported native events remain explicit capability gaps |
| gemini | Thin native event and JSON protocol adapter. | chaos-engine/hooks/kernel.py; chaos-engine/hosts.py | supported adapter | Windows, Linux, macOS | host installer | provider-neutral kernel | unsupported native events remain explicit capability gaps |
| grok | Thin native event and JSON protocol adapter. | chaos-engine/hooks/kernel.py; chaos-engine/hosts.py | supported adapter | Windows, Linux, macOS | host installer | provider-neutral kernel | unsupported native events remain explicit capability gaps |
<!-- inventory:hosts:end -->

### Lifecycle Events

<!-- inventory:lifecycle-events:start -->
| Item | Purpose | Source of truth | Status | Platforms | Provisioner | Owner | Failure behavior |
| --- | --- | --- | --- | --- | --- | --- | --- |
| SessionStart | Normalize native input and evaluate one provider-neutral lifecycle event. | chaos-engine/hooks/lifecycle.py; chaos-engine/hooks/kernel.py | declared | capability-mapped hosts | generated host adapter | lifecycle kernel | missing mapping fails host parity validation |
| UserPromptSubmit | Normalize native input and evaluate one provider-neutral lifecycle event. | chaos-engine/hooks/lifecycle.py; chaos-engine/hooks/kernel.py | declared | capability-mapped hosts | generated host adapter | lifecycle kernel | missing mapping fails host parity validation |
| PreToolUse | Normalize native input and evaluate one provider-neutral lifecycle event. | chaos-engine/hooks/lifecycle.py; chaos-engine/hooks/kernel.py | declared | capability-mapped hosts | generated host adapter | lifecycle kernel | missing mapping fails host parity validation |
| PostToolUse | Normalize native input and evaluate one provider-neutral lifecycle event. | chaos-engine/hooks/lifecycle.py; chaos-engine/hooks/kernel.py | declared | capability-mapped hosts | generated host adapter | lifecycle kernel | missing mapping fails host parity validation |
| PostToolUseFailure | Normalize native input and evaluate one provider-neutral lifecycle event. | chaos-engine/hooks/lifecycle.py; chaos-engine/hooks/kernel.py | declared | capability-mapped hosts | generated host adapter | lifecycle kernel | missing mapping fails host parity validation |
| Stop | Normalize native input and evaluate one provider-neutral lifecycle event. | chaos-engine/hooks/lifecycle.py; chaos-engine/hooks/kernel.py | declared | capability-mapped hosts | generated host adapter | lifecycle kernel | missing mapping fails host parity validation |
| SubagentStop | Normalize native input and evaluate one provider-neutral lifecycle event. | chaos-engine/hooks/lifecycle.py; chaos-engine/hooks/kernel.py | declared | capability-mapped hosts | generated host adapter | lifecycle kernel | missing mapping fails host parity validation |
| PreCompact | Normalize native input and evaluate one provider-neutral lifecycle event. | chaos-engine/hooks/lifecycle.py; chaos-engine/hooks/kernel.py | declared | capability-mapped hosts | generated host adapter | lifecycle kernel | missing mapping fails host parity validation |
| SessionEnd | Normalize native input and evaluate one provider-neutral lifecycle event. | chaos-engine/hooks/lifecycle.py; chaos-engine/hooks/kernel.py | declared | capability-mapped hosts | generated host adapter | lifecycle kernel | missing mapping fails host parity validation |
<!-- inventory:lifecycle-events:end -->

### External Services

<!-- inventory:external-services:start -->
| Item | Purpose | Source of truth | Status | Platforms | Provisioner | Owner | Failure behavior |
| --- | --- | --- | --- | --- | --- | --- | --- |
| GitHub API and raw content | Resolve immutable source and deliver pull requests. | bootstrap.py; work-github-playbook.md | required for remote install and delivery | network | operator credentials | GitHub and repository owner | install or delivery blocks |
| PyPI and uv package service | Provision uv, MemPalace, and Graphify packages. | dependencies.json | required when generation repair needs Python packages | network | uv | installer generation | candidate is discarded |
| npm registry | Provision project-local Memory commands. | dependencies.json | required when Memory is missing or stale | network | npm | installer generation | candidate is discarded |
| five host APIs | Run scheduled paired promotion trials. | scripts/ci/chaos_engine_promotion.py | required for promotion only | scheduled/manual CI | host credentials | promotion evaluator | promotion remains Blocked |
| ShaftHQ/shafthq.github.io | Publish companion functional documentation. | repository documentation policy | required in same delivery campaign | GitHub | documentation PR | documentation repository | campaign remains incomplete |
<!-- inventory:external-services:end -->

### Generated Assets

<!-- inventory:generated-assets:start -->
| Item | Purpose | Source of truth | Status | Platforms | Provisioner | Owner | Failure behavior |
| --- | --- | --- | --- | --- | --- | --- | --- |
| dependency generations | Immutable project-local tools and interpreters. | dependencies.py | generated | Windows, Linux, macOS | installer | receipt-owned | unselected candidate is removed; foreign content is preserved |
| active and previous pointers | Atomically select current and rollback generations. | dependencies.py | generated | Windows, Linux, macOS | installer | installer control plane | invalid pointer fails closed |
| host adapters and receipts | Install native hook, skill, plugin, and MCP projections. | hosts.py | generated and trackable | five hosts | host installer | receipt-owned | rollback restores exact prior bytes |
| Memory, MemPalace, and Graphify state | Persist canonical Memory/relations (tracked) plus derived indexes (`graphify-out/`, MemPalace palace data, `.memory` runtime). | .gitignore; hosts.py | durable Memory tracked; derived indexes untracked | project local | owned tools | project or derived single writer | doctor reports recovery-required |
| reports, caches, and evaluation receipts | Carry bounded diagnostics without transcripts or secrets. | .gitignore; chaos_engine_promotion.py | generated and never tracked | local and CI | requesting command | ephemeral evidence owner | missing evidence blocks promotion |
<!-- inventory:generated-assets:end -->
