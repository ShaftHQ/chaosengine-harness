---
name: kanban
description: >-
  Use when work has several deliverables, tickets, or delegates: board, WIP 1
  writer + 2 review, pull rule, Definition of Done, findings fixed or filed.
license: MIT
permissions:
  - read
  - write
---

# Kanban task flow

Use when work has more than one deliverable, more than one ticket, or any
delegate. Flow beats busyness: finish before starting.

## Board

Keep one board per task as JSON (models corrupt JSON less than prose) in the
session state directory, never in tracked files:

```json
{"wip": {"doing": 1, "review": 2},
 "cards": [{"id": "T1", "title": "...", "column": "ready",
            "acceptance": ["..."], "proof": "command that proves it",
            "evidence": null, "pr": null}]}
```

Columns: `backlog` -> `ready` -> `doing` -> `review` -> `done`.

- `ready` requires acceptance criteria and a proof command. No criteria, no pull.
- `doing` WIP **1 writer** per repository: one card being edited at a time.
- `review` WIP **2**: at two cards waiting for review or CI, pull nothing new.
  Ordinary reversible cards get one fresh-context adversarial review. A public-contract or hard-to-reverse card gets two, one after another.
  The open-PR advisory default is this review WIP times one stream. With no
  `hooks/open-pr-advisory.json`, the default stays one stream until that file
  sets `streams`. The advisory does not read a live parallel-stream set.
- `done` only when the Definition of Done holds.

## Pull rule

Every session, turn, and wake starts by draining right to left: open PRs and
`review` (red or `ACTION_REQUIRED` checks, behind base, conflicts, review
comments, auto-merge off), then `doing`, then shipped bugs or red default
branch. Pull a new `ready` card only when nothing downstream is actionable, and
only while `review` has capacity; waiting on CI counts as idle. Never leave a
started card to start another. Never push work forward. Group related cards
into the fewest safe pull requests. Avoid PRs that depend on other open PRs;
land them in order and merge base once before the final push.
When the owner asks to supersede pull requests that are already open, open one
mega pull request that contains their changes, then close those pull requests.
Do not leave them open beside the mega pull request.
Do not dodge the count by opening a draft, using another branch name, or splitting the work.

## Definition of Done

A card is done when all hold:

1. Every acceptance criterion is met and its proof command output is attached.
2. Tests for new behavior were red first, then green.
3. Review 1 starts with the push of the self-accepted head. Review 2 starts
   on the reconcile push, together with CI. Do not start both reviewers in
   one step ([delivery cycle](../../references/delivery-cycle.md)).
4. Required checks are green on the exact head after one blocking wait per push
   (`gh pr checks --watch --fail-fast` or `gh run watch`); retry once, then stop
   and report. Never re-verify what already passed.
5. Every finding raised while working is closed (see below), including
   static-analysis and code-quality review threads (fix or reply, then resolve)
   before the PR counts as ready.
6. Merged or handed off as instructed only after items 3, 4, and 5. A pending
   check is not success. Do not merge while a check is still running. Then the
   worktree is cleaned.
7. After any CE harness change merges, every agent and delegate reloads the
   latest harness from main before continuing. After each completed delivery
   run `python3 .chaos-engine/tool.py maintain` (fast-forward with local edits
   kept, reinstall, doctor, stale-store refresh, reload).
8. Ship each card as a small vertical slice (~90 changed lines or a named `size_waiver`). One grouped pull request is allowed when an epic or batch waiver names it.

Check items 2 and 4 plus labels and links with `python3 .chaos-engine/tool.py dod <PR>` ([`dod.py`](../../runtime/dod.py))
(table; exit 1 names each gap).

## Findings policy

Every finding ends as exactly one of:

- **fixed** in the current delivery, or
- **filed** as an issue, allowed only when it is both outside the task's scope
  and not critical, blocker, or high severity.

Nothing stays only in chat, a report, or a local file. The final report lists
each finding as fixed (with PR) or filed (with issue).

## Waste checklist

Before each pull, drop anything that is partially done work, extra process,
extra features, task switching, waiting, handoffs without context, or defects
passed downstream (Poppendieck's seven wastes).

## Status

Every status report is a Markdown table, one row per card
(`ID | Issue(s) | PR | Status | Proof or blocker`), then Risks. Never prose or
bullet lists. No separate status rituals. Report only rows that changed since
the last report; say nothing when nothing changed.
