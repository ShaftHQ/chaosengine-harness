<!-- chaos-engine:agentic -->
Parent / related / duplicates checked: #…
retrieve: …

Length budget: TL;DR is at most 5 lines. The agent brief is at most 150 lines.
Research detail goes in `docs/research/<date>-<slug>/` and is linked, not pasted.

## TL;DR

Problem, why it matters, and what done looks like. Five lines or fewer.

## Evidence

Verbatim quotes in code blocks, counts versus the total the screen states, captures, and SHA permalinks. No bare `file:line`.

## Defect inventory

| Id | Observed | Expected | Cause |
| --- | --- | --- | --- |
| D1 | | | hypothesis, or `confirmed: <permalink or repro>` |

List every observable defect before any cause. For visual or terminal output, record each inventory item as found or checked-clean: row count versus the stated total, exact text, duplicates, cursor, alignment, proportions, truncation and leftover rows. Non-visual work skips that checklist with one line. A small reversible typo may keep only the TL;DR and Verify.

## Agent brief

### Goal and role

### Context

Only what a fresh agent cannot find in one search.

### File scope

Confirmed files only. Anything else is a stop-and-ask.

### Steps

1. Inspect and confirm each cause in code.
2. Fix per D-item. State the invariant; a mechanism is a suggestion until confirmed.
3. Verify.
4. Finalize.

### Constraints and non-goals

Assumptions or Out of scope. Name existing tests, linters, and static checks. Name exit, error, and interrupt cleanup when the change holds terminal, file, or process state. Cover non-TTY, `NO_COLOR`, `LANG=C`, narrow and wide terminals, and resize, or mark them out of scope. Windows parity is covered or out of scope.

### Stop and ask when

The file scope is unconfirmed, a cause is still a hypothesis you would have to treat as fact, or the change would overwrite a human-edited test the owner did not name.

### Report back

Per D-item status, commands run, and evidence links.

## User Scenarios & Testing

Given / When / Then, one independent test per scenario.

## Edge Cases

Boundaries, fail-closed paths, and the non-visual or trivial-tier notes above.

## Functional Requirements

- FR-1: …

## Success Criteria

- SC-1: …

## Assumptions or Out of scope

The agent brief's constraints and non-goals are this section. Do not restate them.

## Verify

One line per D-item and one line per SC-* item. No orphan line.

- [ ] D1: …
- [ ] SC-1: …

## Definition of done

- [ ] Finalization: move research docs to `main` under `docs/research/<date>-<slug>/`, update links, and delete temporary branches by name and tip SHA.
