# Delegation

The only writer-selection rule is the [delegation ladder](../skills/chaos-engine/SKILL.md#delegation-ladder). This file is orchestration, review procedure, and receipts. Do not restate the ladder.

A direct host edit is only the ladder's one-change exception.

Delegation distributes work, never responsibility. Select capability from
uncertainty, blast radius, and reversibility. Never bind policy to a vendor,
product name, or runtime setting.

## Capability levels

The delegation ladder names the writer. These words are not a second selection rule.

- Most intelligent model: the orchestrator who writes the brief, and the fresh host reviewer.
- Free model: the writer rung.
- Paid model: the fallback rung.
- Mechanical model: a smaller local model only when the brief marks the item mechanical. The `helper` adapters carry that role from [roles](roles.md).

EXIT 0 with zero tool calls is writer failure: run that command yourself; do not retry an oversized prompt. ChaosEngine never `ft launch` / `ft serve` and never pins model ids in receipts.


## Research / explore firewall

For research or multi-file explore, prefer an isolated subagent (or host Task)
over dumping explore noise into the parent. Return contract and when-to-spawn
rules live in [context firewall](context-firewall.md). Isolation is for context
economy (HumanLayer), not org-chart role-play. Hosts without subagents distill
in-place under the same return contract. Never treat this as always-on
observation.

## Main-thread duties

Orchestrator retains decomposition, architecture, consultation, assignment,
synthesis, integration, and final verification. Stay available to the owner
for realignment and delegate questions. Select and switch modes only through
[execution workflows](execution-workflows.md); this file does not redefine
their criteria or writer limits. Each writer owns an isolated worktree and its own branch. Before dispatching a second writer, run the ownership and conflict checks in [parallel streams](parallel-streams.md) and hand the brief template from that card. A `.chaos-engine` symlink stays untracked. The orchestrator alone pushes the pull-request branch. While
a writer, subagent, or required check is live, automatically follow
[orchestrator follow-through](orchestrator-follow-through.md); never a
heartbeat.

Treat agent lifetime as part of the assignment. Each delegated subagent runs the
same entry path as the main agent before its first action, and on exit runs an
end-of-stream retrospective in the same shape as the main agent. Collect the
writer's bounded failures, findings, and durable-learning candidates for the
root session. A delegate returns durable lessons to the root and does not open the terminal Learning Session pull request.
The root session runs one delegation retrospective after the stream merges.
Then close every no-longer-needed agent
and its descendants before moving to the next phase. Never use `followup_task`
to reactivate a completed or finished assignment; a new review round gets a new
reviewer instance.
Preserve the closed relationship as history instead of deleting it. A final
answer with an unneeded live agent is incomplete.

## Cost-aware delegation & effort scaling

Vendor-neutral. The host names the models; this policy does not pin a vendor.

1. The Architect-Orchestrator is the most capable model at high reasoning. It refines requirements, decides architecture, writes the detailed plan and spec, decomposes tasks, selects model and effort, and oversees verification. It does not implement when it is delegating.
2. Model and effort follow the delegation ladder in the router. Do not add a second effort rule here.
3. Quota-exhaustion failover: when the active delegate exhausts usage or quota, checkpoint state and continue on the next cheapest qualified model named by the delegation ladder. Do not open a second fallback ladder.
4. Plan persistence: record an orchestrated multi-step plan in a GitHub tracking issue so any later agent can resume from that ticket.
5. PR model attribution: on orchestrated pull requests, report transparently in the PR description or review summary which model and reasoning effort executed each implementation wave and each independent review, with a short field note of what worked and what hit quota or stalled. Do not persist provider or model IDs into machine receipts or vendor-lock policy with this reporting.
6. Pre-dispatch canary & stall failover: before assigning real work to a free or unproven third-party delegate gateway, run a fast pre-dispatch canary (a short-timeout prompt/tool-call readiness check). A stall is no product-file change and no delegate-log progress for 3–5 minutes. Tool calls and tokens in the delegate log are progress. When breached, cancel immediately and fail over through the delegation ladder.
7. Test-runner parallelism probe (`xdist`): before dispatching full-suite pytest runs in delegate briefs, probe `python3 -c "import xdist"`. When `xdist` is absent, run targeted local suites plus offline validators per wave and let CI run `pytest -n auto` (or run the full serial suite only once before PR creation) rather than burning ~25 min per wave serially.

### OpenCode free-model dispatch workflow (Rung 1)

1. **Probe reachable free models:** run `opencode models` to list reachable `$0` models (or resolve a local loopback runtime via `dispatch.py resolve`) and select `--variant high`.
2. **Stage the brief inside the isolated worktree:** write each worker's brief inside its own git worktree (for example `.ce-brief.md`, kept untracked and never staged or committed) so OpenCode's `external_directory` permission guard does not auto-reject reading the brief.
3. **Record the Rung 1 receipt before dispatch:** run `python3 .chaos-engine/hooks/delegation_gate.py record --rung free --free selected --effort high --brief <brief-path> --why "..."` before invoking `opencode run --model <free-model> --variant high "..."`. For parallel fan-out across N isolated worktrees, either record a master brief referenced in each command or record sequentially per stream.
4. **Parallel rate-limit hygiene:** spread parallel free writers across distinct free models (or cap to 1–2 concurrent workers per free endpoint) so concurrent `--variant high` sessions do not hit a shared free-tier rate limit.
5. **Stall or complexity escalation to Rung 4:** if a free writer stalls (no product-file change and no delegate-log progress for 3–5 minutes; tool calls and tokens in the delegate log are progress) or fails acceptance checks on large or multi-file modules, cancel the stalled process, switch to another reachable free model if available or record Rung 4 (`--rung paid --free too-complex --effort low --tier cheapest --brief <brief-path> --why "<evidence>"`), and dispatch parallel cheapest-paid host subagents (lowest sufficient tier) across the same file-disjoint worktrees.
6. **Subagent edit receipt note:** a spawned subagent with a valid paid receipt may edit. The main session still records `rung=direct` for its own direct edit.

## Delegation ladder

The only writer-selection rule is the [delegation ladder](../skills/chaos-engine/SKILL.md#delegation-ladder). Hook hosts run it from `hooks/guard.py` on PreToolUse. Hookless clients receive it from `tool.py entry`. Do not restate the ladder.

## Orchestrator duties

Same class of standing duties: stay available, keep the live status table
current after every dispatch and every finished agent, group related work into
the fewest PRs that still keep one problem per issue (`Closes #N` per completed
subtask), and keep working until every in-scope ticket is delivered. Do not
treat planning, a status table, or one PR as session complete.

After grouping, the done condition is: every in-scope ticket is merged or
explicitly out of scope. After each chunk merges, destroy that writer: run
[post-merge own cleanup](parallel-streams.md#post-merge-own-cleanup) for that
writer's ownership-manifest row (worktree, local branch, remote head if still
present, prune), start the next from a fresh `ChaosEngine/*` branch off the
fetched configured default branch, update the live status table, and continue.
Stop only when the in-scope set is empty, the owner narrows scope, or a real
blocker needs the owner.

Same-subsystem leftovers share one PR. Split only when writers would collide on
the same files and cannot be sequenced, or when the work truly belongs to
different categories. If a delegate omitted an actionable leftover, file the
missing issue or Memory as an owner-command; do not implement the leftover work.

After every dispatch and after every subagent finishes, post or update the
**default live status table** from
[process-owner status report format](process-owner-scrum-master.md#status-report-format)
so the owner can read progress without reconstructing the session. Use columns
`Task ID | Ticket(s) | PR | Scope | Status | Elapsed | ETA` with Status
`Done` | `InProgress` | `ToDo` (optionally `Blocked`). Include out-of-scope rows
explicitly in Scope/Status rather than dropping them. Enhance Details in Scope
or adjacent prose with blocker notes, HEAD SHA, and root-learning handoff
(`findings` / `nothing durable`) when needed. Do not put secrets in the table.

## Independent adversarial review

Follow [delivery cycle](delivery-cycle.md) for review 1 with the self-accept push, the reconcile push that starts review 2, the required-check merge rule, and `gh pr merge --squash` in this repository. Do not start both reviewers in one step. One subject gets at most two adversarial reviews in sequence, and an unchanged head is never reviewed a third time. Never review individual implementation steps. A pull request that changes an existing test contract, or whose CI does not run the changed surface ([UI delivery](ui-delivery.md)), does not skip that pair. Time pressure never skips this pair.
Independence:

- The reviewer is a **separate agent instance, never the author** of the work.
- Choose a disposable review mechanism. When the host provides reliable terminal
  close, use a native reviewer subagent and close it after the verdict. Without
  reliable terminal close, use an artifact-bounded ephemeral reviewer and pass
  the exact revision or diff plus its directly required guidance as immutable
  input. It must not depend on repository shell access to discover the artifact.
  Each review records a valid receipt only when the active host
  adapter records its successful receipt, bound to that artifact. Until an
  adapter supports that receipt, obtain an independent pull-request review too;
  prose claiming the one-shot review happened is not evidence.
- The reviewer is prompted to **refute** the work — find where it is wrong,
  unverified, or over-claimed — not to approve it.
- The reviewer uses the headings `regression`, `missing-adoption`, `broken-verification`, `unbound-check`, and `verdict` from [roles](roles.md#reviewer).
- The reviewer is handed **the exact revision under review** and a way to read
  it that does not touch the shared working tree: `gh pr diff <n>`,
  `git show <ref>:<path>`, or its own `git worktree add`. A read-only reviewer
  owns no worktree, so left unsaid it inherits whatever branch the shared tree
  happens to hold, which is routinely not the one under review.
- The reviewer's **first action confirms the revision is what it thinks it is**,
  before any finding is written. If it cannot confirm, it says so and stops. A
  search that misses because the tree is wrong returns a clean no-match, which
  is indistinguishable from a real absence and is the most confident wrong
  answer a review can produce.
- Depth scales with the pull request, matching consult triage. Each of the two
  reviewers uses correctness, reproduction, and blast-radius lenses.
- Escalate to the most intelligent model for a new subsystem, a migration, a
  dependency swap, or any decision that is expensive to unwind.

A self-review is not a review. Neither is a delegate's own report on its own
work.

When implementation is delegated to a local runtime (FreeToken / OpenCode),
OmniRoute, or any writer that is not the host session model, the orchestrator
**must** still trigger the required fresh-context adversarial reviews (one for
ordinary reversible work; two independent adversarial reviews in sequence for
public-contract, irreversible, or outbound work) as **new instances of the same
host model** (native reviewer subagents). Never assign that review to the local
or OmniRoute writer. Transport does not change the reviewer.
When FreeToken is READY and the owner selected orchestrator mode, the
orchestrator must not implement product or overlay chunks; dispatch a
file-disjoint local writer. OPENCODE `context_length_exceeded` is a writer
failure: shrink the prompt, do not retry the same text.

### Recording a finding

Each finding is one block, in this form. A finding that cannot fill `Scenario`
and `Evidence` is not confirmed and is not written.

```
F<n>      <one-line claim>
Verdict:  confirmed | refuted | unproven     (refuted is dropped, not softened)
Blocking: yes | no                           (yes = wrong behavior ships; docstrings,
                                              commit messages and PR prose are never yes)
Where:    <path>:<line>                      repository-relative
Scenario: <the concrete sequence that produces the wrong result>
Evidence: <what was run or read, and what it returned>
Class:    <recurrence class, or "new: <name>">
Fix:      patch | ticket | decision_needed | dismiss
```

`Class` is the load-bearing field, and it is why the block exists: when a class
reaches three entries it earns a mechanical check, or an explicit "cannot be
mechanised, and here is why". Extend the list below; never invent a synonym for
a row that already exists.

| Class | Shape | What catches it now |
| --- | --- | --- |
| `vacuous-check` | a test, pin or self-test that cannot fail | mutation checks and the `setUp`-patch pin in `test_agent_router_contract.py` |
| `unspecified-predicate` | the rule re-guesses a decision the ticket never made | nothing -- it needs a ruling on the issue |
| `credit-not-in-diff` | prose credits work the diff does not contain | the credit scan in `validate_pr_closing_keywords.py` |
| `sibling-left` | the instance was fixed and its twin was not | the docstring duplicate scan in `validate_agent_guidance.py` |
| `fires-on-correct-work` | the gate refuses work that satisfied it | nothing yet, and it is past three: R19 refusing an out-of-repo write, R13 refusing an already-merged branch, and three more recorded refusals -- so it has earned that item's check, which runs every new rule against the branch adding it |
| `live-state-in-tests` | the test's answer depends on the machine | `StopTestsAreIndependentOfLiveStateTest` |
| `wrong-width-check` | the command measured is not the command that matters | nothing yet |

### Review disposition

Run the adversarial reviews the delivery cycle names (one for ordinary
reversible work; two in sequence for public-contract, irreversible, or outbound
work). On a two-review chain, a blocking finding on the first review is fixed,
then the second review runs on that new head. A blocking finding on the second
review closes that class in the edit. The test proves the class. That edit does
not start another reviewer, and it does not repeat both reviews. A finding
outside the brief's fixtures and the recorded non-goals is filed. The head stays.
Do not add a third review of an unchanged head, or a third review that hunts the
next example of a closed class. A finding that changes architecture returns work
to planning. Extra local tests run only after this terminal review stage.

Post the findings as a pull-request review, not only in chat. Findings that live
only in a transcript die with the session, which is how the same class gets
re-found by a reviewer instead of accumulating into a check.

## Delegate covenant

[Roles](roles.md) states how each host carries this. Either way, every dispatch
carries it:

> Load the canonical ChaosEngine entrypoint before all other work. Evidence over
> inference: read or run before claiming. Stay inside assigned scope; report
> adjacent findings. Cite repository-relative `file:line` evidence. Behavior
> complete the bounded implementation before consolidated validation. Never
> claim an unrun check. Escalate architecture or ambiguity instead of deciding it.
> Report failures plainly. Before waiting or after a material finding, send a
> substantive handoff: done evidence, current step, blockers, and whether a
> decision is needed.

A default-model delegate may add: mechanical, spec-exact, or bulk slices may go
to the mechanical model with this covenant; inspect their actual output before
using it. The mechanical model omits that clause because it may not delegate.

## Returned-work review

Read diff and tests in the two passes [roles](roles.md) gives the reviewer.
Route every finding to `patch`, `ticket`, `decision_needed`, or `dismiss`.
Orchestrator owns final severity because it has full context. Use the
[verification-gap lens](verification-gap-lens.md) for behavior that could break
without a failing check.
