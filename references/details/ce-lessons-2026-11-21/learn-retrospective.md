# Lessons from the 2026-11-21 session retrospective

Source: host learn run `~/.grok/learn/runs/20261121-121105`, 102 kept sessions since 2026-10-13. The host wrote four skills under `~/.grok/skills`. Those copies are not the portable contract. This file is the generalized record. Each repeated phrase joins the skill or reference that already owns the job.

## What happened

The owner repeats instructions that ChaosEngine already states, and four instructions that no portable skill stated. On 2026-11-21 the owner also said to delegate a consulting subagent when needed and not to ask again, and to track the lessons in this repository.

## Why

Host `/learn` writes `~/.grok/skills`. [harness-learn](../../harness-learn.md) says a home-directory skill is not a valid learning. The phrases kept coming back because the portable owners did not say them.

## Continue

- Join an existing owner. Do not add a second skill for work-item, kanban, consult, or execution workflow selection.
- Keep asking material follow-ups until a plan is decision-ready.
- After that, and whenever the owner says not to ask again, dispatch a consultant instead of reopening the decision.
- Leave zero-use bundled skills, the Figma plugin, `shaft-mcp`, and the host workflows installed. The owner kept them on 2026-11-21. Zero hits is not a delete.

## Stop

- Do not treat `~/.grok/skills/session-handoff`, `issue-orchestrator`, `supersede-open-prs`, or `openbot-developer-instructions` as the ChaosEngine source of truth.
- Do not copy the OpenBot teammate prompt into this overlay. It names host tools (`openbot.history_search`, `openbot.send_feedback`, `openbot__name`). [learn-traces](../../learn-traces.md) forbids vendoring host runner mechanics.

## Start

- Session end with work still open: one pickup ticket, owned by [work-item](../../../skills/work-item/SKILL.md).
- Already-open pull requests the owner wants replaced: one mega pull request, then close the superseded ones, owned by [kanban](../../../skills/kanban/SKILL.md).
- "Work as orchestrator and parallelize": file-disjoint streams on the parallel workflow, owned by [execution-workflows](../../execution-workflows.md).
- "Do not ask me again" / "you decide": read-only consultant subagent, owned by [consult-first](../../consult-first.md).

## Outcome changed

A later session that would have asked the owner to disable unused surfaces, or that would have filed a second pickup ticket, or that would have left superseded pull requests open, now follows the owning contract instead of a home-directory skill.

## Evidence

| Phrase | Sessions | Portable owner |
| --- | --- | --- |
| Finalize in-progress work and file one GitHub ticket | 3 | work-item, Session handoff |
| Work as orchestrator and parallelize | 7 | execution-workflows |
| One mega PR that supersedes and closes open PRs | 2 | kanban, Pull rule |
| Do not ask again; delegate a consultant | this session | consult-first |
| OpenBot plain-words and tool bridge | 61 host slash hits, no portable skill | not ported; host-only |
