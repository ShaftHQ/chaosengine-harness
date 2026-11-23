# Consult

Triage already selected a depth past the trivial row. Name what good looks like and how the change will be proved before any edit.

## Contents

- [Full pass](#full-pass)
- [Executable specification for consequential work](#executable-specification-for-consequential-work)
- [Plan artifact destination](#plan-artifact-destination)
- [Cross-artifact consistency](#cross-artifact-consistency)
- [Constitution Check](#constitution-check)
- [New-product decision](#new-product-decision)
- [Lifecycle](#lifecycle)
- [Output](#output)

A trivial task never loads this file. If triage and the user's framing disagree about size, say so in one line and work to the larger. During planning, keep asking material follow-ups until the plan is decision-ready. After owner approval, execution is unattended; dispatch a consultant agent for implementation ambiguity. When the owner says not to ask again, or closes a decision with "you decide", do not reopen it. Dispatch a read-only consultant subagent for the remaining ambiguity and proceed on its guidance. Irreversible or externally visible actions still need explicit owner approval ([ethics card](../companions/ethics-card.md)).

Card precedence when cards disagree: [delivery-cycle](delivery-cycle.md) wins on review and merge, [kanban](../skills/kanban/SKILL.md) wins on WIP, the ethics card wins on irreversible or outbound actions, and the ChaosEngine skill wins on routing. The deeper file wins on its own topic.

## Full pass

1. **Deliverable and proof of done.** Name the artifact and the one observation that proves it. No observation means you do not yet understand the request.
2. **Unknowns.** List what could invalidate the approach. Settle the cheapest fatal unknown first.
3. **Invariants.** Name what must not break: public API, persisted or wire format, security and trust boundaries, accessibility, error handling, performance, and behavior users already rely on.
4. **Two rival approaches.** Write both. Steelman the one you intend to reject. If the steelman wins, switch. One approach is the first idea, not a decision.
5. **Choose by removability.** When both hold, take the one that is easier to delete later. Fix the root owner of the invariant, not each symptom.
6. **The RED test.** State the focused check that fails today for the right reason, where it lives, and the command that runs it. If no check can observe the change, say what evidence replaces it.
7. **Delegation shape.** State what stays on the main thread and what is bounded enough to assign. Compare file scopes before concurrent writers.
8. **Completion gate.** State what you will run, read, and show, and who reviews it.
9. **Reflection boundary.** Resolve failure fingerprints, diagnostic/recovery actions, receipt proof, and the session-end retrospective in the matrices when repeated failure or a long session is plausible.

## Executable specification for consequential work

For cross-cutting or hard-to-reverse work, the three matrices below are mandatory. Every required cell must be resolved. Blank cells, TODO, TBD, placeholders, and guesses are invalid, even when qualified by explanatory text. Any unresolved cell blocks RED/GREEN. Every acceptance criterion and invariant must map to positive and negative proof. At least one sibling/caller omission mutation must fail. Record the completed matrices on the target GitHub issue comment before the first implementing commit.

Use exactly these names and columns, in this order. Add one resolved data row for every caller/site, every state/transition/failure mode, and every acceptance criterion/invariant.

### Resolved caller matrix

| Site | Effective cwd/path | Runtime/version/platform | Permissions/trust | Configuration precedence | Input existence |
| --- | --- | --- | --- | --- | --- |

### State/failure matrix

| State | Immutable ownership | Preflight | Mutation order | Mixed state | Atomicity | Concurrency | Idempotency | Recovery | Fail-closed |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |

### Acceptance-to-proof map

| Criterion or invariant | Positive proof | Negative or mutation proof | Command |
| --- | --- | --- | --- |

Treat these as mandatory regression prompts when relevant:

- Effective working-directory/path resolution.
- Interpreter/version/conditional dependency marker.
- Mixed owned+unknown preflight.
- Immutable ownership.
- Atomic backup/concurrent replacement.
- Post-migration adapter/link resolution.

## Plan artifact destination

Choose the repository-safe destination before any imported design or planning workflow writes a file. For issue-backed work, persist the approved design and implementation plan on the target GitHub issue. For non-issue work, keep them transient unless the owner explicitly approves an existing operational-guidance location. Never create or write `docs/superpowers/**` in this repository; this rule overrides an imported skill's default path.

## Cross-artifact consistency

The analyze phase is read-only. Check the work item against its task list for duplication, ambiguity, underspecification, alignment with `identity.md` and the iron laws, coverage of every `FR-*` and `SC-*`, and inconsistency between obligations. Report id, category, severity, locations, summary, and recommendation. Cap the table at 50 rows. Do not modify files in this pass. The mechanical check is [intent_converge.py](../runtime/intent_converge.py).

## Constitution Check

A consequential plan on the GitHub issue includes this gate before research and re-checks it after design. Cite `identity.md` Principles and the iron laws. Pass, or fill the table. Fill the table only when a principle or iron law is violated. A passing plan may omit the table. Do not add a second constitution file. `identity.md` remains the only source of principles.

## New-product decision

An idea that would be a new product records exactly one of `decision: go`, `decision: needs-clarification`, or `decision: kill`, plus the evidence and the reason. `kill` closes the question. `go` may open a work item.

## Lifecycle

Work runs in this order. Each phase ends before the next begins:

architect -> analyze -> plan -> design -> RED -> GREEN -> refactor -> commit -> pull request -> babysit (fix review comments, failed tests, and unresolved threads, then resolve them) to green -> prove epic and tracker initial scope is complete -> merge -> terminal reflection when owed -> one root Learning Session -> final report.

The close is the [delivery cycle](delivery-cycle.md). Never force a review between earlier phases.

## Output

Report the triage result, the depth you took, and only the points that depth included. A partial pass reports partially. Do not pad it with points you were told to skip.
