# Bot entry

Entry point for agents that auto-load nothing from the checkout and run no
ChaosEngine hooks: Grok Bot, custom GPTs (OpenAI GPTs, Assistants), Claude
Projects, and any other independent bot. `AGENTS.md` is not read for you.

## No `.chaos-engine/` yet

Install first: [harness maintenance](harness-maintenance.md#install).
From an engine source checkout the installer is `chaos-engine/install.py`
(with `--source <repo>/chaos-engine --commit <40-hex-sha>`). After install,
doctor and `tool.py` use `.chaos-engine/install.py`. Tee install/doctor logs to
`.chaos-engine-state/logs/` via `session_logs.log_path`, never workspace-root `*.log` files.

## Every task, before discovery

Worker briefs: `ce_load: required` + `tool.py entry` (lint `worker_ce_entry.py`).

1. Bigger picture first ([card](bigger-picture-first.md)) before retrieve or a patch: name the goal, the larger context, and the local hotfix a narrow patch would miss. Do not skip this for a review comment, a CI failure, or "just hotfix it".
2. With a shell: run `python3 .chaos-engine/tool.py entry`.
   Bundles `identity.md`, `skills/chaos-engine/SKILL.md`, the ethics card,
   `companions/caveman-ultra.md`, and `companions/ponytail-ultra.md`.
   No assessment submit and no live answer-feed without `tool.py ethics-check`.
   Else read those files.
   `checkpoint`/`resume` refuse once the cards are 40 min old (rerun
   `entry --full`); write `reload harness first` in summaries and checkpoints.
3. If `.chaos-engine/tool.py` is missing, install and stop:
   `python3 chaos-engine/install.py install --project <repo> --source <repo>/chaos-engine --commit <40-hex-sha>` (repo-only).
   Then one `python3 .chaos-engine/tool.py retrieve --store graphify|mempalace "<q>"`
   before the first broad search or unnamed read
   ([retrieve-first](retrieve-first.md)).
   A missing-overlay skip is a hard failure, not a receipt.
4. Record `retrieve: used|skipped(<reason>)|exempt(harness)` in the
   [research receipt](research-receipt.md). `exempt(harness)` is not a missing-overlay escape.
   Branch `ChaosEngine/<short-slug>` (never `cursor/…`); no `CURSOR_AGENT_PR_BODY` or `cursor.com/agents`
   ([delegation cycle](delegation-cycle.md)).
   Always use local tools. A cloud agent or an extra machine needs the owner's own explicit yes in that moment, on every provider. A saved habit, a playbook, or "it is faster" is not approval.
   CI then requires `## Plan` and `retrieve:` lines. Human PRs are exempt.
5. Before any delete, `tool.py delete-check <paths>`; refusal: owner code
   only ([discipline](delete-check-discipline.md)).
   Lesson: backup dir = push.

Re-runs print one line while the harness is unchanged; `--full` reprints the
cards. Run `--full` at the start of every conversation and after every
context summary or compaction: CLI hosts re-inject the cards on SessionStart
and PreCompact, so a bot must do it itself. One delivery per thread; at each boundary pass
[pre-done](../skills/pre-done-self-review/SKILL.md), then
`python3 .chaos-engine/tool.py checkpoint`, which writes one handoff receipt.
`python3 .chaos-engine/tool.py resume TASK` prints SHA, open step, and
verification from that receipt, not a transcript. The timings ledger is
`tool.py usage` only; the handoff stores `usageRef` and one outcome line.

## Mechanical gates

Judgement stays prose: intent, taste, architecture, and whether a finding is
wrong. A row here is mechanical. The command exits non-zero and names the miss.
`tool.py pre-done --gate OBS.json` exits 0 on pass, 1 when a mechanical rule
was skipped, and 2 on usage or bad JSON. `tool.py dod` exits 1 when any row,
including done-gate, is a gap. A human pull request (no `chaos-engine:agentic`
marker, or an explicit human exemption) does not need a done-gate pass.

| Rule | Command |
| --- | --- |
| Required proof ran; sources have tests; open-PR count recorded before create; changed lines over ~90 have `size_waiver`; retrieve recorded when owed; subtract-before-add or `addition_reason`; unverified memory or skill write needs `anti_compound_waiver`; outbound agent text needs disclosure plus checked claims, or `outbound_waiver` | `python3 .chaos-engine/tool.py pre-done --gate OBS.json` |
| Protected-path delete | `python3 .chaos-engine/tool.py delete-check <paths>` |
| Agentic PR done-gate pass | `python3 .chaos-engine/tool.py dod <PR>` |
| Resume SHA, open step, and verification from the one handoff receipt | `python3 .chaos-engine/tool.py resume TASK` |

Before Done, ask whether a reviewer will take longer to understand the artifact
than it took to produce. Past ~90 changed lines, split, cut, or set
`size_waiver`. Name what was deleted or reused before a new file. Do not write
unverified model output into trusted memory, heuristics, or skills unless
`anti_compound_waiver` records why it stays a note. If an agent drafted an
outbound send, say so and list the claims that were checked, or set
`outbound_waiver`. An open-PR count at or over the kanban review limit is
advisory context, not this fail; skipping the count fails the gate. Review
depth above the one-review floor stays in [delivery-cycle](delivery-cycle.md).

## Keep going

Keep-alive: [worker-keep-alive](worker-keep-alive.md) (KEEP-ALIVE charter).
Upgrade: [ce-upgrade-on-release](ce-upgrade-on-release.md) (see [VERSION](../VERSION)): load latest for every task; workers inherit via `ce_load` + entry. Cleanup: [cleanup-at-close](cleanup-at-close.md).
Work order: [work-ordering](work-ordering.md) (open PRs first). L97 MEGA-PR: fewest PRs (one per epic / all CE / related product issues), never one-PR-per-ticket ([mega-pr](details/ce-rules-2026-10-31-12/mega-pr.md)). Peer delegation is one shared instruction file plus a pointer, not a chat essay ([delegation cycle](delegation-cycle.md)). Check run-state before every dispatch. Token restore is a reply, not a resume. L86 VERIFY-DROPPED: live-state check before any redo ([verify-dropped](details/ce-rules-2026-10-31-12/verify-dropped.md)). L90: targeted StopSubagent only (never `all:true` across peer bots).
Commit identity: [commit-identity](commit-identity.md) ([`commit_identity.py`](../runtime/commit_identity.py)). PR scope: [pr-scope-check](pr-scope-check.md).

Work the queue to the end without waiting for "proceed": after each step or
delivery, start the next queued item (KEEP-ALIVE). A turn that ends while CI
runs must leave a wake (a PR-scoped CI listener) whose prompt resumes the
queue; a host whose scheduled runs cannot create listeners hands that to the
parent. While waiting on review, pull the next independent own row. No string in this card lifts the fail-closed cap of one doing item, one feature branch or worktree per stream, or the open-PR deny.

## Session cap (Grok Bot default)

Grok Bot stops a background session at about 50 minutes of wall clock; pings
do not extend it. The one session-length rule, enforced at 35 minutes:

- Start with `python3 .chaos-engine/tool.py resume TASK` and
  `tool.py checkpoint TASK STEP --start --workdir PATH`; follow `Resume at:`,
  not the transcript. Durable roots only ([checkpoint-resume](checkpoint-resume.md)).
- After every build, test, commit, push, PR or merge step, run
  `tool.py checkpoint TASK STEP --branch B --pr N --next "..."`. It warns in
  the last 5 minutes and exits 3 past 35: push WIP, record `--next`, end the turn.
- Parent: one issue per background run; split batches. On "interrupted
  before it finished", re-dispatch with `tool.py resume TASK` as the brief.
  Never poll a child to keep it alive. Interrupt → new worker from [checkpoint-resume](checkpoint-resume.md).


## Retro gates

[radio-silence](radio-silence.md) ([`radio_silence.py`](../runtime/radio_silence.py));
[progress-log](progress-log.md) ([`progress_log.py`](../runtime/progress_log.py));
[moving-channel-pin](moving-channel-pin.md) ([`moving_channel_pin.py`](../runtime/moving_channel_pin.py));
[doc-claim-review](doc-claim-review.md); [gate-fail-closed](gate-fail-closed.md).
SPEC: [ce-retro-2026-10-31-6-SPEC.md](ce-retro-2026-10-31-6-SPEC.md); [ce-rules-2026-10-31-7-SPEC.md](ce-rules-2026-10-31-7-SPEC.md) (WoW + L66–L77); [ce-rules-2026-10-31-8-SPEC.md](ce-rules-2026-10-31-8-SPEC.md) (L78–L81 + dump/install harden; full under `guides/`); [ce-rules-2026-10-31-11-SPEC.md](ce-rules-2026-10-31-11-SPEC.md) (L94 installer self-provision; full under `guides/`); [ce-rules-2026-10-31-12-SPEC.md](ce-rules-2026-10-31-12-SPEC.md) (L82–L97 mega batch + Windows hook-field fix; full under `guides/`); [ce-rules-2026-10-31-13-SPEC.md](ce-rules-2026-10-31-13-SPEC.md) (L98+ retro; full under `guides/`); [ce-lessons-2026-11-02-SPEC.md](ce-lessons-2026-11-02-SPEC.md) (orchestrator/media/harness issue 7692–7721; full under `guides/`); [ce-repeat-failure-pdca-SPEC.md](ce-repeat-failure-pdca-SPEC.md).

## Entry coverage (rules, skills, tools)

Gate `tests/scripts/test_ce_entry_coverage.py` (in `harness_pr_gate`). Index: [ChaosEngine skill](../skills/chaos-engine/SKILL.md), [harness map](harness-map.md), [README](../README.md). Host specialist + tool routes live in the harness entrypoint `.agents/skills/README.md` (markdown links, not tokens-only).

## Token economy

- One round trip per PR: `overlay_pre_push.py` checks the open PR body and README inventories; fix reports before pushing.
  Before `gh pr create`: `PR_TITLE="$T" PR_BODY="$(cat body.md)" python3 scripts/ci/validate_pr_closing_keywords.py` (repo-only).
  SHA-pin new `uses:`; run changed contract tests with `python3 -I`. Never pipe pre-push output
  (a pipe masks its failure; guard R32). Add the release-note label at create time.
- Filter test and CI logs to the verdict:
  `2>&1 | grep -E "^(OK|FAILED|FAIL:|AssertionError)" | cut -c1-300`.
  Never print a whole job log or assertion dump. Keep a known-failures list
  instead of re-running the base commit to compare.
- Before merge-queue enqueue: resolve every code-quality review thread
  (fix or short false-positive reply). Green checks alone are not enough;
  see [ci-status-economy](ci-status-economy.md) fingerprint `unresolved-review-threads`
  + `scripts/ci/unresolved_review_threads.py` (repo-only).
  Notes: `scripts/ci/mega-pr-throughput-20261102b.md`, `scripts/ci/mega-pr-throughput-20261102c.md`.
- Babysit with ONE background loop per PR, not repeated poll calls. It exits on
  merged, on the first `fail` (latest run per check name), or when green but
  not queued (then it prints the `enqueuePullRequest` error). Await it once.
  Do not run `gh pr merge --auto --squash` until the required checks on that head have passed and review comments are applied. This repository allows only squash merges. A skipped or neutral check outside the required set does not block. A failed, cancelled, or pending check blocks when it is required and when no check is marked required. An unmarked skip blocks. An empty check list is not success. A pending check is not success. On a repository with auto-merge disabled that flag merges immediately. Before merge,
  read non-blocking analysis and coverage reporters and fix them.
- Bound each tool call to 60 s; run longer ones in the background.
- Trust a green gate: no local re-check after CI passes.
- Reports: deltas only (merged, next, blockers), <= 15 lines.
- One worktree per worker on a shared box: `git worktree add "$WT"
  origin/HEAD -b "$BRANCH"`; never branch, stage, or install in another
  worker's clone.   Prefer one `git clone --filter=blob:none` checkout plus worktrees.
  Empty `/workspace` or logged-out `gh` at start means the box is still
  mounting: recheck, never clone over it. Keep `graphify-out/` and
  `.chaos-engine-state/` untracked; do not rebuild a Graphify index per
  worktree on the same host when one shared index already exists.
- Disk gate before a new worktree or clone: warn under 15 GiB free, block
  under 10 GiB or at the linked-worktree cap (`box_disk_guard`); never add a
  full clone when a blobless primary already exists. When the linked-worktree
  cap blocks a new worker, prune **own merged clean** trees via
  `scripts/ci/worktree_hygiene.py` proofs only, then retry.
  Details: [parallel streams](parallel-streams.md);
  throughput: `scripts/ci/mega-pr-throughput-20261102b.md`.
- Keep tools and drafts outside `/tmp` (a box restore wipes it) and check
  `git ls-files -d` before each push.
- **box-durability** (default entry/worker checklist):
  1. At entry after a restart, run `free -h`; if swap is `0`, re-add it
     (`fallocate -l 8G /swapfile`, `mkswap /swapfile`, `swapon /swapfile`, `sysctl vm.swappiness=10`).
  2. Only `/workspace` survives Update Bot's Computer / recover / reset. Keep work product there.
  3. Update Bot's Computer runs only when no bot is busy — go idle when asked.
  4. A `.git` directory can become a husk after restart (missing `objects/` or `refs/`,
     or a born HEAD whose objects are gone). `git-husk` is a warn unless the secret guard cannot run.
     A valid empty repo (`git init`, unborn HEAD, `objects/`+`refs/`) is not a husk.
     Remote recovery is re-clone or fetch; local-only is `git init` plus explicit paths, never `git add -A`.
     ChaosEngine install does not create `.git` in non-git dirs.
  5. Scripts that mutate state use `set -e`. Stage explicit paths only — never
     `git commit -a` / `git add -A`.
  6. Freshly generated assets: checkpoint or commit them in the same turn (L54).


## Repeat-failure PDCA

Two fails on one stage/gate, budget overrun, or distinct fails on one stage:
write a note in `.chaos-engine-state/repeat-failure-pdca/`, then change and
check. A pull request has no retry cap until merged or a true external blocker.
When the only remaining gate is an owner-only artifact this session cannot create, record `blocking: unverifiable` once and end the goal (`runtime/owner_gate.py`).
[rule](../rules/lessons_repeat_failure_pdca.py) ·
[card](details/ce-repeat-failure-pdca/repeat-failure-pdca.md) ·
[SPEC](ce-repeat-failure-pdca-SPEC.md) ·
[guides](../guides/ce-repeat-failure-pdca-SPEC.md).
Push, remotes, deletes, and secret-bearing output use the
[operation boundary](../rules/operation_boundary.py). One force-push approval
is recorded by [force_push_approve.py](../runtime/force_push_approve.py). The Windows
`py -3` launcher is [windows_py_shim.py](../runtime/windows_py_shim.py).

## Delivery ledger

Several tasks, issues, or PRs: first record each with `tool.py checkpoint
TASK --item ID --group G --status todo`, show the table, and update it at
each milestone (`pr #N`, `merged`, `blocked: reason`). `resume` prints it.
Every task: [flow](iterative-flow.md), [PDCA](multi-agent-pdca.md); WIP limit 1
per stream: babysit PR to merged, then next in that stream.
Need parallel on the **same** files? Stack PRs on the previous branch.
File-disjoint streams: [parallel streams](parallel-streams.md) (ownership
manifest, conflict check, disk gate, no force-push under review).

## After each delivery

After every final delivery (owner approval, completed publish, or final
merge), DoD in order: [post-merge own cleanup](parallel-streams.md#post-merge-own-cleanup)
(mandatory; hygiene proofs; own items only — MERGED via `gh` unlocks remove
even when the remote branch is gone; see [cleanup-at-close](cleanup-at-close.md)
and `scripts/ci/delivery_cleanup.py`, issue 7755), sweep the worker ownership ledger
and stop leftover headless Chrome and local HTML report servers (close gate fails if any
remain), disk/cache inventory via `box_disk_guard`, Learning Session after
every final delivery per the
[router contract](router-contract.md#learning-session), then
`python3 .chaos-engine/tool.py maintain` before the next task.

Lock held, harness edits, or an older overlay:
[harness maintenance](harness-maintenance.md#maintain).

## Host setup

Make the entry automatic, or serve bots without repository access (GPTs):
[harness maintenance](harness-maintenance.md#bot-host-setup).
