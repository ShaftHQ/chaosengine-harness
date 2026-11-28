# Bot entry

Any AI client without native auto-load (chat bots, CLIs, agents, IDEs), including Grok Bot, OpenBot, and a custom GPT. `AGENTS.md` is not read for you. `<python>`: `py -3` Windows, `python3` Linux/macOS. Hooks/tests: Python 3.11+. Installer pin: 3.14.0. The delegation ladder inside the entry bundle is mandatory on these clients too.

## Every task, before discovery

1. Bigger picture first ([card](bigger-picture-first.md)) before retrieve or a patch: name the goal, the larger context, and the local hotfix a narrow patch would miss. Never skip for a review comment, CI failure, or "just hotfix it".
2. Shell: `<python> .chaos-engine/tool.py entry` bundles `identity.md`, `skills/chaos-engine/SKILL.md`, the ethics card, `companions/caveman-ultra.md`, and `companions/ponytail-ultra.md`. No shell: read those files. Then one `<python> .chaos-engine/tool.py retrieve` ([retrieve-first](retrieve-first.md)).
3. Before any delete, `tool.py delete-check <paths>`. Lesson: backup dir = push.

## Mechanical gates

Judgement stays prose. `tool.py pre-done --gate OBS.json` (proof, tests, ~90 lines or `size_waiver`), `tool.py dod <PR>`, `tool.py delete-check <paths>`, `tool.py ethics-check`, `tool.py resume TASK`.

Default is a small vertical slice (~90 changed lines or a named `size_waiver`). One grouped pull request is allowed when an epic or batch waiver names it.

## Caps

Two failed attempts on one approach: step back and re-plan. At most 3 local PDCA loops before review. Babysit an open pull request until merged or `blocking: unverifiable` (`runtime/owner_gate.py`).

Never arm `gh pr merge --auto`. Merge with `gh pr merge --squash` only after required checks pass and review threads resolve. A `merge_queue` rule enqueues with `gh pr merge`, no strategy flag ([delivery cycle](delivery-cycle.md)).

Learning Session after every final delivery. Then `<python> .chaos-engine/tool.py maintain`.

## Delivery ledger

Several tasks: `tool.py checkpoint TASK --item ID --group G --status todo`. One doing item per stream. Same files: stack PRs. Disjoint files: [parallel streams](parallel-streams.md).

## Entry coverage

`tests/scripts/test_ce_entry_coverage.py`. Host routes: `.agents/skills/README.md`.

## Grok Bot

This section is Grok Bot only. OpenBot keeps the shared steps above and does not use these Custom rules.

Grok Bot has no hook runtime and no repo file for Custom rules. On first run, add the rules in Settings, General, Bot, Custom rules. The labels on that screen are Custom rules, Ask first, and Allow automatically. An Ask first rule always stops a matching action.

Add an Ask first rule for each of these three actions: send, pay, and delete. The how-it-works page also says sending, publishing, and deleting. Approving every payment means not saving the card in Vault.

Enable the private skill for this Bot under Connect apps, Private skills. Do not publish it to a team, and do not call Publish. The skill points at `skills/chaos-engine/SKILL.md` and `references/bot-entry.md`. It does not repeat these rules.

Doctor reports instruction-plus-custom-rules. It does not report hook health. A missing Custom rule is not a healthy enforcement report. A settings screen this session cannot open is `blocking: unverifiable`, not a pass. That check does not record the Custom rules as present.
