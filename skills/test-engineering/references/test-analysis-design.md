# Test analysis and design

Load this for new tests, a test plan, or analysis of acceptance criteria, an ADR, or a diff. The technique menu and the negative-check rule stay in [test-design.md](../../../references/test-design.md). RED-GREEN-REFACTOR stays in [tdd.md](../../../references/tdd.md) and [tdd-failure-modes.md](../../../references/tdd-failure-modes.md). An AI subject also loads [ai-sut](../../../profiles/ai-sut/README.md).

## Shift-left

1. Name the test basis (criterion, ADR decision, or diff hunk) and give it one id.
2. Split it into atomic conditions. One check must be able to fail that condition alone.
3. Set `input_bearing` true when the condition accepts data. Otherwise set it false.
4. Score product risk as likelihood 1..5 times impact 1..5.
5. Testability requires all three, or the condition is not ready: controllability (you can set the inputs), observability (you can read the outcome), and determinism (same inputs, same outcome, or a recorded seed).

## Risk to design depth

| Level | Depth |
| --- | --- |
| 1-3 | One valid class. |
| 4-7 | That valid class, plus an invalid class or 2-value boundary analysis. |
| 8-14 | 3-value boundary analysis, or a decision table, or a 0-switch transition, plus a real `mutation_target` path. |
| 15-25 | Add a 1-switch, pairwise, or a property. If a Q4 characteristic is in scope, add that non-functional check. |

`bva_depth_gate` returns `insufficient-bva-depth` at level 8 or higher when the check has neither 3-value points nor a `decision-table` or `state-transition` technique.

## Technique rules

These add precision to the menu. They do not restate it.

- 2-value boundary analysis: the on-point and one off-point. Enough below level 8.
- 3-value boundary analysis: the off-point and the inner neighbor, `min-1` with `min+1`, or `max-1` with `max+1`. Two or more distinct boundary points also satisfy the level-8 gate.
- Decision table: a don't-care cell is `-`. Keep the rejected or impossible row, and name its action. Do not drop that row.
- State transition: 0-switch is one event from a state (one legal, one illegal). 1-switch is two consecutive events. Level 8 can stop at 0-switch. Level 15 adds 1-switch when the sequence is the risk.
- Pairwise: cover each pair of factor levels once, with PICT or `allpairspy`. Do not expand to the full product. Keep one invalid pair.
- Metamorphic: state the relation between two outputs. A broken relation fails the check.
- Property-based: Hypothesis, jqwik, fast-check, proptest, rapid, or FsCheck. Record the seed. Commit the shrunk counterexample next to the test.
- Mutation-guided: at level 8 or higher, `mutation_target` is a real source path. A survivor on a changed line is `survived-mutant`, not a pass.

## Oracles

Use the first that applies, in this order: `specified`, `derived`, `differential`, `metamorphic`, `human`. Record that type on the check. `human` is never recorded as an automated pass.

## Quadrants, trophy, pyramid

Agile Testing Quadrants: Q1 is unit and component depth from the table above; Q2 is business-facing examples and scenarios; Q3 is exploratory and usability; Q4 is performance, security, reliability, and the other in-scope characteristics (`quality_scope_gate`). The testing trophy puts integration and contract checks at the boundary ahead of a large unit pile. The pyramid still holds when the unit is the product. Do not invert either picture to skip the invalid class.

## Refuse these

- An expected value copied from the output under test (a mirror or a tautology).
- A mock of the subject, rather than of an external boundary.
- Happy-path-only coverage of an input-bearing condition.
- A smoke test with no assertion (`assertion_signal_gate`).
- A check tied to the wall clock, order, or a live network with no quarantine cause.
