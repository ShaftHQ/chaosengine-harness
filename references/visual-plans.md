# Visual plans

`tool.py plan` stores a `ce-plan/v1` checklist beside the task ledger and renders it. The command does not call a model and does not use the network. A one-file reversible task does not need a plan.

Schema: `schemas/ce-plan.v1.json`. Text is whitespace-collapsed and capped at 500 characters. A plan has at most 100 steps. Step status is `pending`, `in_progress`, `done`, `failed`, `skipped`, or `blocked`. The task ledger row `kind: plan-step` is the status record. `<TASK>.plan.json` keeps the definition and a cached projection.

Three-state hosts map `blocked` to `pending` and `skipped` to `completed`. `failed` maps to `pending`. OpenBot and Codex use `inProgress`. ACP and Claude use `in_progress`.

## Commands

```text
tool.py plan new TASK (--from plan.json | --from-md checklist.md) [--goal TEXT] [--triage public-contract]
tool.py plan show TASK [--format term|md|mermaid|html|json] [--out PATH] [--pr-section]
tool.py plan step TASK STEP --status STATUS [--evidence KIND:REF]... [--note TEXT]
tool.py plan edit TASK (--add TITLE [--after ID] | --remove ID | --move ID --after ID | --retitle ID TEXT)
tool.py plan approve TASK [--comment STEP:TEXT]... [--code CODE] [--ref TEXT]
tool.py plan approve TASK --request-code
tool.py plan stop TASK
tool.py plan gate TASK
tool.py plan watch TASK
tool.py plan walkthrough TASK [--format md|html] [--out PATH]
```

Exit codes: 0 ok, 1 validation, 2 usage, 4 awaiting approval, 5 stopped, 6 no plan.

`plan new` requires approval when `--triage public-contract` is set or the plan has at least three steps. Fewer steps are not required. `--from-md` reads an OpenBot checklist: text above the boxes is the explanation, `- [ ]` is pending, and `- [x]` is done.

`plan show --format term` prints `Plan: <title>  N/M done`. The title is the explanation when it is 1 to 80 characters, otherwise `Plan`. A UTF-8 tty uses `✓ ◉ · ✗ ⊘ ⏸`. A non-tty or a non-UTF-8 stream uses `[x] [>] [ ] [!] [-] [=]` and no colour. The running step shows `activeText`. `--format md` is a GitHub task list. `--pr-section` adds a `## Plan` heading. `--format mermaid` is a `flowchart TD`. `--format html` is one self-contained file with no external request.

`plan edit` bumps `revision` and returns a required plan to `awaiting` when a step that is not done is added, removed, moved, or retitled. Status and evidence do not.

## Approval

Set `CHAOS_ENGINE_ENFORCE_PLAN_APPROVAL=1` to enforce the gate. The default is off. `plan_approval_block(task)` in `runtime/plan_gate.py` returns a denial that names `plan approve` while the current revision is not approved, and `None` after approval. With enforcement on, `plan approve` accepts only a one-use code from `plan approve --request-code`. A missing, wrong, reused, or expired code is refused. A code relayed by an agent is not approval. `plan stop` blocks edits until a new approval.

`hooks/guard.py` is not wired in this change. Hook hosts call `plan_approval_block` from that module. Hookless hosts print `plan show --format md`, wait for the owner, run `plan approve`, then `plan gate` before the first edit.

## Evidence

A step with `verify` cannot become `done` without `--evidence KIND:REF` or `--note "no-evidence: <reason>"`. File evidence stores `ref`, `sha256`, and a trailing `exit:` code when the log has one. The file stays where the producer wrote it. `plan walkthrough` lists the goal, steps, changes taken from commit, pr, and diff evidence, validation results, and open items. A missing or changed file is marked, not hidden.

`tool.py pre-done --gate` reports `plan evidence: step <id> is done with verify and no evidence` for that case. An approved required plan with no walkthrough is also reported. `scripts/ci/docs_drift.py` is consulted only when that file exists.

## Live status

`plan watch` polls the plan file at most once a second and exits when every step is terminal. `on_checkpoint(task, step)` records a plan step when the id matches. `tool.py checkpoint` does not call it yet. `resume_block` is the plan text, including approval comments, that belongs under the existing `Resume at:` line.

## Host UI

`tests/fixtures/plan/host-ui-probe.json` records hosts that were not driven as `skipped`. A skipped host is not a pass. Folding a known `TodoWrite`, `TaskCreate`, `TaskUpdate`, Codex `update_plan`, or ACP `plan` payload is `fold_tool_call`. An unknown payload is ignored. No sticky pull-request or issue comment is posted. That mirror stays off.

## Router pointer

For a public-contract task or a plan of at least three steps, write the plan with `tool.py plan new`, show it, and wait for `tool.py plan approve` before editing. Details stay in this file.
