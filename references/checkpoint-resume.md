# Checkpoint and resume after interruption

## Rule

1. Checkpoint every major step with `tool.py checkpoint TASK STEP --branch B --pr N --next "..."`.
2. An interrupted worker **cannot** be resumed in place. Start a **new** worker
   from the checkpoint file (`tool.py resume TASK`); do not replay chat history
   as source of truth.
3. When pausing a worker mid-item, write a checkpoint with finished plan, head
   SHA, paths, and exact next step before stopping.

## Crash-safe long tasks (#8065)

- Start with `tool.py checkpoint TASK STEP --start --workdir PATH --prereq swap --prereq disk:5`.
  `/tmp` and `/dev/shm` are refused (exit 5); `$TMPDIR` and tmpfs warn. Keep
  clones, drafts and logs under the work root.
- Every step records the work root's git HEAD (or `--head SHA`).
  `tool.py checkpoint TASK --verify` exits 7 when the pushed HEAD has no
  checkpoint; run it before reporting done.
- `tool.py entry` and the SessionStart card list unfinished tasks for this
  project, newest first, with `Resume at:`. Older than
  `CHAOS_ENGINE_RESUME_STALE_DAYS` (default 7) is marked `[stale]`.
- `tool.py resume TASK` re-checks the prerequisites and names the cause in one
  line: box restart (boot after the last checkpoint), planned stop, or likely
  host cap. Put that line in the owner report.
- Exit 3 records a planned stop. Finish or roll back the current step, report
  "stopped at step X, next Y", and start no new step.

## Why

Host session caps (~50 min wall; enforce 35) kill in-flight workers. Chat
context is lossy; a file checkpoint is the handoff.

## Unknown outcome

After a side-effecting tool whose completion is unknown (interrupted, no result,
or a crash mid-body), do not automatically retry the same effect. Record an
unknown outcome, not automatic retry. Prefer `tool.py checkpoint` before an
irreversible or externally visible tool. This overlay does not wrap a host
model stream and does not add a session event log.

A repeated identical tool call is advice only. The counter lives in
[repeat_reminder.py](../hooks/repeat_reminder.py). It does not deny the call.

Shell environment for the host's own command tool is not owned here.
Receipt sanitization already drops credential-shaped keys. Harness git and
gh keep token-shaped variables because those commands need them. No second
env scrub is added.

## Check

`tool.py resume TASK` prints `Resume at:` matching the last checkpoint.
Adversarial: kill mid-step → replacement worker continues from file without
re-deriving the plan from chat.

## Follow-up

[bot entry](bot-entry.md) Session cap; [task isolation](task-isolation.md).

## Generated assets

When a render, encode, or other generated media file lands, checkpoint or
commit that **explicit path** in the same turn (L54).
A box restart must not be the first thing that discovers the file is gone.
Never rely on `git commit -a` / `git add -A` for this — stage the asset paths
by name.

## Per-task budget override (L80)

`--kind test-run` → 90 min budget (default 35). Explicit `--minutes` wins.
A test-run step that is not done must pass `--next` containing `methods:`, `hypothesis:`, and `command:`, each followed by non-whitespace. A missing label is printed to stderr, no ledger row is written, and the checkpoint exits non-zero. `resume` still prints `Resume at:` plus that `--next`, so the open methods, hypothesis, and exact command are the resume line.
`classify_surefire` returns one `CLASSIFIED` line with the Surefire counts only when the runner exit is 0, the device is present, and every non-pass result is a skip whose message has a whole-token id (letters then digits, bounded by non-alphanumerics, such as `G54` in `BLOCKED G54`; `G54extra` does not count, and an id on a line that is not the skip message does not count). It returns `FAILED` when the summary is absent, the exit is non-zero, the device is lost, there is a failure or error, or any skip is unclassified.
