# Bot entry

Grok Bot, custom GPTs, and other bots auto-load nothing. `AGENTS.md` is not read for you. Host hook launchers and tests run on Python 3.11+. The installer managed runtime pin stays 3.14.0.

## Every task, before discovery

1. Bigger picture first ([card](bigger-picture-first.md)) before retrieve or a patch: name the goal, the larger context, and the local hotfix a narrow patch would miss. Do not skip this for a review comment, a CI failure, or "just hotfix it".
2. With a shell: `python3 .chaos-engine/tool.py entry`. It bundles `identity.md`, `skills/chaos-engine/SKILL.md`, the ethics card, `companions/caveman-ultra.md`, and `companions/ponytail-ultra.md`. Else read those files. Then one `python3 .chaos-engine/tool.py retrieve` before a broad search ([retrieve-first](retrieve-first.md)).
3. Before any delete, `tool.py delete-check <paths>`. Lesson: backup dir = push.

## Mechanical gates

Judgement stays prose. Commands: `tool.py pre-done --gate OBS.json` (proof, tests, ~90 lines or `size_waiver`), `tool.py dod <PR>`, `tool.py delete-check <paths>`, `tool.py resume TASK`.

Default is a small vertical slice (~90 changed lines or a named `size_waiver`). One grouped pull request is allowed when an epic or batch waiver names it.

## Caps

Two failed attempts on one approach: step back and re-plan. At most 3 local PDCA loops before review. Babysit an open pull request until merged or a true external blocker or `blocking: unverifiable` (`runtime/owner_gate.py`).

Never arm `gh pr merge --auto`. Merge with `gh pr merge --squash` only after required checks are green and review threads are resolved.

Learning Session after every final delivery. Then `python3 .chaos-engine/tool.py maintain`.

## Delivery ledger

Several tasks: `tool.py checkpoint TASK --item ID --group G --status todo`. One doing item per stream. Same files: stack pull requests. Disjoint files: [parallel streams](parallel-streams.md).

## Entry coverage

Gate `tests/scripts/test_ce_entry_coverage.py`. Host routes: `.agents/skills/README.md`. Retro specs: [index](details/retro-spec-index.md). Box checklist: [box-durability](box-durability.md). Session, token, and keep-alive detail: [on demand](details/bot-entry-on-demand.md).
