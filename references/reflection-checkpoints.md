# Reflection checkpoints

Reflection is a task-scoped circuit breaker, not a diary. It extends the
existing append-only session ledger with bounded structured outcomes and
receipts. Never store prompts, transcripts, raw logs or errors, credentials,
source excerpts, or user-specific absolute paths.

## Triggers and depth

- Two attempted failures do not demand a receipt.
- The third attempted failure stops for a receipt (`third-fix`, or
  `repeated-fingerprint` when every fingerprint matches). A fourth distinct
  failure without a new receipt is forbidden. Distinct fingerprints count
  toward `third-fix` only within the last 30 minutes, so unrelated failures
  spread over a long goal session do not block it. Repeated fingerprints and
  explicit triggers count since the last receipt. The denial leads with the
  exact receipt command for this session: the controller the gate executed,
  the session id, and short flags (`--assumption`, `--alternative`,
  `--change`, `--proof`, `--outcome`). Fill them in and run it. The token is
  read from the session ledger. Do not read `reflection.py`.
- A valid receipt authorizes one following `git commit` of that fix. The
  receipt and the commit are separate commands. A combined shell does not
  hide the third failure. A Stop does not demand a one-hour terminal receipt.
  Set `GIT_COMMITTER_NAME` and `GIT_COMMITTER_EMAIL` on the command that
  creates the commit. Environment committer variables override `git -c user.*`.
  `git rebase --onto <base> <base>` is a no-op and does not rewrite the
  committer. When the intent is the commits after a revision, use
  `git format-patch <rev>..HEAD`. `git format-patch -N <rev>` writes the N
  commits that end at that revision, not the N commits after it.
- Also stop after two local/CI disagreements, repeated
  review or user corrections, repeated guard blocks, a safety incident, scope
  expansion, an invalidated premise, or an unchanged rerun.
- A diagnostic or capability probe recorded as `non_attempt` does not advance
  the counter, but it also does not clear a pending checkpoint.
- When a session exceeds one hour, SessionEnd files enhancement notes from
  the scratch folder SessionStart created for that session and its
  subagents, and writes the report. If a note is still missing from
  filed.txt, a later SessionEnd files it. A pass that left nothing unfiled
  does not file again. A Stop in the middle of the session does not run
  the retrospective. Every SessionEnd report includes this prevention question: what can we learn from what happened so far for our harness or memory modules to avoid such failures in the future? Enhancement filing stays after one hour.

The failure fingerprint is a digest of low-cardinality fields only: phase,
target, failure class, platform, invariant, and head. Raw host error text is
never fingerprint input or ledger content.

## Checkpoint workflow

While reflection is pending, read-only diagnosis, planning/tracker updates, a
changed diagnostic experiment, and receipt creation remain available.
Implementation mutation and unchanged test reruns are blocked.

1. Reconstruct the bounded fingerprint and classify the failure.
2. State the failed assumption and challenge it.
3. Compare at least two approaches.
4. Choose one changed diagnostic experiment and improve observability if needed.
5. Run the experiment, record its outcome, route any durable learning, and
  append a validated receipt with `scripts/agents/reflection.py`.
6. Resume only after the receipt matches the exact pending fingerprint set.

The receipt schema requires `schemaVersion`, task/session identity, a trigger
enum (`second-failure`, `repeated-fingerprint`, `third-fix`,
`platform-disagreement`, `review-repeat`, `user-correction`, `guard-repeat`,
`safety-incident`, `scope-expansion`, `premise-invalidated`, or
`long-session-completion`), `failureFingerprints`, `failedAssumption`, `approachesCompared`,
`chosenExperiment`, `changedApproach`, `proofCommandOrCheck`, `proofOutcome`,
and a `durableDisposition` enum (`guidance-fixed`, `issue-filed`,
`knowledge-recorded`, `nothing-durable`, or `degraded`). An optional `issue`
must be a GitHub issue URL.
Stores and GitHub are optional: an unavailable service never prevents the
local receipt or resumption. Receipt commands do not create issues. The
session-end retrospective files enhancement notes when the session exceeded
one hour.

For semantic events the hook cannot infer safely, record the trigger explicitly
with (repo-only) `py -3 scripts/agents/reflection.py trigger --session-id {id} --trigger
{enum}`. Append a receipt with the short flags from the denial, or with
(repo-only) `py -3 scripts/agents/reflection.py receipt --session-id {id} --json
{receipt-json}`. `--session-token` is optional and defaults to the ledger token. Mark only a proved setup, syntax, or capability
probe by exact ID with the `non-attempt` subcommand. Portable installs use the
same subcommands through `.chaos-engine/hooks/reflection.py`.

An optional value which may start with `-` (including `--session-token`) is
accepted as `--name=value` and as a following token that does not itself start
with `--`. The regression is
`test_cli_json_receipt_accepts_session_token_that_looks_like_a_flag` in
`tests/scripts/test_guard_lifecycle.py`. Do not reimplement that parser.

For a terminal receipt, the final user-facing summary is one retrospective:
what happened, why it happened, continue doing, stop doing, start doing, and
one next action. A line-leading `Why:`, `Continue:`, `Stop:`, or `Start:`
heading counts for those four topics. The live Stop asks once after background
work has exited. A later Stop does not ask again. A valid note is still accepted.
Write the learning retrospective only after the merge SHA exists and after subagents and monitors have exited. A non-required check must not start the note and must not be the only reason the note waits.
That is the Start-Stop-Continue close (gather the facts,
name the cause, decide the behaviors, commit one action). An actionable line
would change a later session and is not already shipped or already open.
File it with `gh` before the note. A ChaosEngine change (skills, hooks,
installer, roles, identity, companions, or overlay references) is an issue on
the configured upstream repository (`scripts/ci/chaos-engine-upstream.txt` or
`CHAOS_ENGINE_UPSTREAM_REPO`). A project-only change is an issue on the
repository of the project that uses ChaosEngine. Cite each issue URL on
its line. `nothing actionable` is the only close with no URL. Local memory
and the chat note are not tracking. Do not estimate tokens or cost there.
[`session_token_usage.py`](../runtime/session_token_usage.py) records local dispatch
usage. Finalize does not copy that ledger
into the summary.

Leftover risks and out-of-scope items must not remain only in chat. Search for
duplicates, then open GitHub issues with `gh` (never GitHub MCP). Put those
URLs on the receipt as `trackingIssues`. Use `noDeferredOrRiskWork: true` only
when nothing was deferred and no residual risk remains. The hook never creates
issues; a terminal receipt without tracking URLs or that attestation fails.

## Enhancements

The stop hook reads only the final Enhancements block, not the rest of the chat.
A bullet must lead with shipped, tracked, or rejected, each followed by a colon.
Shipped and tracked rows carry a github.com pull, issues, or commit URL.
Rejected rows carry a reason that is not a deferral phrase such as later.
Use nothing actionable for this block when it lists only shipped and rejected rows.
The terminal root reflection consumes the root session receipt and receipts from
every delegate created during the runtime. Delegate termination does not discard
its failures, recoveries, blockers, dead ends, or improvement ideas;
the root deduplicates them before the one Learning Session. Persist only the
minimal privacy-safe evidence and never persist provider, model, private route,
credential, transcript, or machine-local path data.

The root creates an open runtime registry before delegation. Every dispatch
atomically registers its participant before process launch. Finalization closes
and freezes the registry, then terminal reflection reads that stored membership
rather than a caller-supplied list reconstructed at the end.
Each registered main or delegate must have dispositions for its incidents or a
no-learning attestation. Only an unreachable delegate may use an explicit
unavailable attestation; absence is never treated as no learning.

## Lessons markdown on ChaosEngine improvement PRs

After a reflection or retrospective that motivates a ChaosEngine improvement
PR (skills, hooks, installer, roles, identity, companions, or overlay
references), attach the **full detailed markdown lessons file** to that PR —
committed in-tree or linked from the PR body with the complete safe-to-share
text. A compressed summary is not enough: reviewers need the reasoning,
evidence, and the concrete rule changes. Strip personal data, credentials,
client names, and prices before attaching.

