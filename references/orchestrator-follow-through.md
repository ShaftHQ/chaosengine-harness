# Orchestrator follow-through

Orchestrators inspect live writers and required checks, consult, remove
impediments, and continue delivery. Assignment alone is not progress. Enforce
[process-owner](process-owner-scrum-master.md) MUST gates by
link; do not restate those invariants here.

## Cadence and inspection

While any writer or required check is live, including a live subagent, choose
one cadence from task scope: 5 minutes for short or high-risk work, 10 minutes
for normal work, or 15 minutes for long stable jobs. Inspect automatically,
without the owner asking. Do not inspect more often than the selected cadence
except on dispatch, completion, failure, or owner/delegate interrupt. First
inspect as soon as dispatch yields a live handle. Use the host timer or
scheduler when available; otherwise the next main-thread wake still owes the
inspection.
While a writer, reviewer, or required check is live, inspect at least once
every 15 minutes. A shorter selected cadence still applies. Each inspection
asks whether the delegate needs consultation or facilitation, then gives that
help inside granted authority. Each inspection also reads progress. If the
delegate is not progressing, or is going the wrong way, decide whether to
direct it or move the implementation to another model, and record the evidence
for that decision. A status line that does not ask and does not help is a
heartbeat.
No live writers or required checks: no scheduler — **unless** the owner asked
for unattended babysitting or adaptive follow-ups; then follow
[process-owner adaptive follow-up](process-owner-scrum-master.md#adaptive-follow-up-orchestrator-duty)
and retune **x** each cycle from evidence (tighten under active CI/downloads,
stretch when quiet, stop when terminal).

Each inspection is a process-owner duty: establish blocked or unblocked state,
report status with evidence, apply pressure when progress stalls, consult on
ambiguity, and remove blockers within granted authority. Then keep, re-spec,
upgrade, or kill. Never send a heartbeat. Validate errors and progress before
the next handoff; bound retries and escalate instead of waiting indefinitely.

## Review loop

With a reviewer agent, deliver through the
[multi-agent PDCA loop](multi-agent-pdca.md).

## Delivery ledger

For a multi-item ask, the orchestrator owns the
[delivery ledger](bot-entry.md#delivery-ledger): build and show it before
dispatching, pass `tool.py resume TASK` as each delegate's brief, and update
item status at every inspection that sees a milestone. Enforce the
[WIP limit](bot-entry.md#delivery-ledger): do not dispatch the next item while
an earlier item's PR is unmerged, unless it is stacked on that PR.

## Consult and impediments

Ask what is blocked and what would unblock. Do not rewrite a healthy writer's
task. Remove tooling, access, and environment impediments;
coach the owner through how-to-work impediments; escalate owner-only decisions.

## Delivery and escalation

Writer dispatch follows the [delegation ladder](../skills/chaos-engine/SKILL.md#delegation-ladder). The one-change exception is [when-to-use-local](../skills/local-agency/references/when-to-use-local.md).

Opening a PR does not complete follow-through. Continue until the in-scope
delivery condition is met. Unattended watch is one blocking
`python3 scripts/agents/watch_pr_checks.py --pr <n> --until-merged`: one line (repo-only)
on GREEN, RED, or MERGED. No second poll, no heartbeat, no status table.
A host "you will be notified" line does not end the turn. Ending the turn,
a completion summary, or a worker_completed record while that watch is pending
is a failed delivery. If the host backgrounds the command, resume attaches to
that same task id and does not start another poller. Resume text is
`scripts/agents/unattended_delivery.py`.

A scheduled status routine, a babysit poll, and parent narration about the same PR are overlapping status channels and a contract failure; the live watch lease owns status ([one status channel](process-owner-scrum-master.md#one-status-channel)).

When the owner asks to **deliver**, **babysit**, or keep the work going, that
is the goal: finalize the in-scope outcome in the best honest way. Keep
iterating after red CI, a merged partial slice, or a stalled delegate. Re-spec,
expedite, and support writers. Compaction is not stop. Compaction restores the
watch task id, pull request number, repository, head SHA, and the
not-done-until-merged bit. The resumed turn waits on that task. It does not
re-read the router before MERGED or RED. A quiet interval with no
live writer is not permission to end babysit until the delivery condition is
met or a named HALT applies.

Escalate using portable capability levels: mechanical, default, and most
intelligent. Host dispatch prompts may map those levels to their own capability
labels; portable policy never binds them to a vendor.

## Delegate artifacts

A delegate removes the worktree, local branch, and other artifacts it created before it finishes, unless that branch is the open delivery branch the orchestrator still needs. The orchestrator does not leave those artifacts after the stream is merged or abandoned.


## Session close

After the delivery commit is on `origin/main`, clean the local checkout, pull `origin/main`, then run `python3 .chaos-engine/tool.py stores refresh --if-stale`. The Graphify stamp is that `origin/main` commit. The next session in this directory starts fresh while `origin/main` is still that commit.
