# Bot entry, on demand

Session cap, keep-alive, and token-economy detail moved out of the always-loaded card.

## Keep going

Keep-alive: [worker-keep-alive](../worker-keep-alive.md). Upgrade: [ce-upgrade-on-release](../ce-upgrade-on-release.md). Cleanup: [cleanup-at-close](../cleanup-at-close.md). Work order: [work-ordering](../work-ordering.md). Commit identity: [commit-identity](../commit-identity.md). PR scope: [pr-scope-check](../pr-scope-check.md).

Work the queue after each step. While CI runs, leave a wake. No string here lifts the cap of one doing item and one branch per stream.

## Session cap

Grok Bot stops a background session at about 50 minutes. The harness warns at 35 minutes via `tool.py checkpoint`. Start from `tool.py resume TASK`. Durable roots: [checkpoint-resume](../checkpoint-resume.md). Parent: one issue per background run. Do not poll a child to keep it alive.

## Token economy

One round trip per PR. Filter logs to the verdict line. Resolve review threads before merge. One background loop per PR. Bound each tool call. Trust a green required check. Reports are deltas, at most 15 lines. Pipe rules and SHAFT-only CI helpers stay in their own cards, marked external-example when the script is not in this tree.

## After each delivery

Post-merge cleanup of own items, Learning Session, then `tool.py maintain`. See [router contract](../router-contract.md#learning-session) and [harness maintenance](../harness-maintenance.md).
