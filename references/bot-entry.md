# Bot entry

Any AI client without native auto-load (chat bots, generic CLIs, custom agents, IDE assistants), including a Grok Bot or a custom GPT. `AGENTS.md` is not read for you. `<python>` is `py -3` on Windows and `python3` on Linux/macOS. Hooks and tests use Python 3.11+. Installer pin: 3.14.0.

## Every task, before discovery

1. Bigger picture first ([card](bigger-picture-first.md)) before retrieve or a patch: name the goal, the larger context, and the local hotfix a narrow patch would miss. Do not skip this for a review comment, a CI failure, or "just hotfix it".
2. Shell: `<python> .chaos-engine/tool.py entry` bundles `identity.md`, `skills/chaos-engine/SKILL.md`, the ethics card, `companions/caveman-ultra.md`, and `companions/ponytail-ultra.md`. No shell: read those files. Then one `<python> .chaos-engine/tool.py retrieve` ([retrieve-first](retrieve-first.md)).
3. Before any delete, `tool.py delete-check <paths>`. Lesson: backup dir = push.

## Mechanical gates

Judgement stays prose. `tool.py pre-done --gate OBS.json` (proof, tests, ~90 lines or `size_waiver`), `tool.py dod <PR>`, `tool.py delete-check <paths>`, `tool.py resume TASK`.

Default is a small vertical slice (~90 changed lines or a named `size_waiver`). One grouped pull request is allowed when an epic or batch waiver names it.

## Caps

Two failed attempts on one approach: step back and re-plan. At most 3 local PDCA loops before review. Babysit an open pull request until merged or `blocking: unverifiable` (`runtime/owner_gate.py`).

Never arm `gh pr merge --auto`. Merge with `gh pr merge --squash` only after required checks are green and review threads are resolved. A `merge_queue` rule enqueues with `gh pr merge` and no strategy flag ([delivery cycle](delivery-cycle.md)).

Learning Session after every final delivery. Then `<python> .chaos-engine/tool.py maintain`.

## Delivery ledger

Several tasks: `tool.py checkpoint TASK --item ID --group G --status todo`. One doing item per stream. Same files: stack pull requests. Disjoint files: [parallel streams](parallel-streams.md).

## Entry coverage

`tests/scripts/test_ce_entry_coverage.py`. Host routes: `.agents/skills/README.md`.
