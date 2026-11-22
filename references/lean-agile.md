# Lean and Agile coverage

Short map from principle to the file and the gate. This is not the always-loaded card. The manifesto is not pasted here.

Sources: Mary and Tom Poppendieck, *Lean Software Development* (seven wastes); David J. Anderson, *Kanban*; Masaaki Imai, *Kaizen*; [Principles behind the Agile Manifesto](https://agilemanifesto.org/principles.html).

| Principle | Where it is enforced |
| --- | --- |
| Lean: cut extra work, handoffs, and defects passed on | Waste digests on `tool.py usage` and the handoff receipt (`runtime/session_token_usage.py`, `runtime/handoff_receipt.py`). Numbers only. |
| Kanban: limit work in progress | `runtime/task_ledger.py` `wip_gate`. Default 1 doing item, 1 feature branch or worktree, and 1 open PR per stream. Over the cap denies. |
| Kaizen: stop and fix the recurring cause | `runtime/task_ledger.py` `defect_ratchet`. A repeated defect type blocks the next item until a preventive check id is recorded. |
| Satisfy the customer with working software | `runtime/sdlc_flows.py` `intent_match` and `test_plan_gate`. A note that cannot fail is not a check. |
| Welcome change without a second spec format | `references/spec-template.md` and `skills/work-item/SKILL.md`. One dual-audience document. |
| Deliver in thin slices | Size policy in `references/bot-entry.md` (about 90 changed lines, or `size_waiver`). Group only what still fits that policy. |
| Business and builders share one record | The issue body, not the chat. `references/work-item.md`. |
| Sustainable pace | Session cap in `references/bot-entry.md`. WIP caps above. |
| Technical excellence | `references/test-design.md` and `missing-negative-check`. |
| Simplicity | `references/eliminate-waste.md`. Do not add a tool-call cap the traces do not justify. |
| Reflect | Learning Session after delivery. `skills/self-improve/SKILL.md`. |

## Narrow mega-PR

Group related work only when the group still fits the size policy. The doing, branch, and open-PR caps fail closed. No string in this file or in the always-loaded card lifts them.

## Metric definitions

These fields are digests. They are not transcripts.

| Field | Meaning |
| --- | --- |
| tokenWaste | Tokens spent on repeated tool calls after the first. Count, not the call text. |
| contextWaste | Context tokens loaded minus the tokens the step actually used. |
| reworkWaste | Count of redo events, not a copy of the failed attempt. |
| WIP items | Doing items on the delivery ledger. |
| WIP branches | Feature branches or worktrees still open for the stream. |
| WIP open PRs | Pull requests still open for the stream. |
| prSize | Changed lines on the pull request. |
| cycleTimeSeconds | Seconds from start to done for the item. |
| softwareWastes | Poppendieck's seven, each tagged or waived: partially done work, extra processes, extra features, task switching, waiting, motion, defects. Names only. |
| feedbackReceipt | Id, accepted, and time. Not the feedback text. |
| leadTimeSeconds | Finish time minus create time. |
| blockedTimeSeconds | Seconds the item was blocked. |
| queueTimeSeconds | Start time minus create time. |

Unmeasured fields stay `unmeasured`. A run is not failed for an unmeasured digest.

## Fixture scorecard

Not a measured campaign. No n≥5 live snapshot was run. The numbers below are synthetic and labelled fixture.

| Metric | Value | Label |
| --- | --- | --- |
| tokenWaste | 120 | fixture |
| contextWaste | 400 | fixture |
| reworkWaste | 2 | fixture |
| WIP items | 1 | fixture |
| WIP branches | 1 | fixture |
| open PRs | 4 | fixture; allowed only with the waiver named above |
| prSize | 90 | fixture |
| cycleTimeSeconds | 86400 | fixture |

`session_token_usage.fixture_scorecard` returns the same figures with `source: fixture`.
