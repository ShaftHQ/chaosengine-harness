# Test design

One card for choosing a technique. Each check may carry `technique` plus `partition` or `boundary`. An input-bearing criterion still needs one invalid partition or one boundary check (`missing-negative-check` in `runtime/sdlc_flows.py`).

## Equivalence partitioning

Use when many inputs should behave the same, so one representative stands for the class.

Valid class: a supported currency code. Invalid class: an empty code.
One check per class. Do not retest every member of a class you already represented.

## Boundary value analysis

Use when behavior changes at a limit: length, count, range, or capacity.

Minimum, just below minimum, and just above maximum.
Tag the check `boundary`. A missing edge here is `missing-negative-check` when the criterion takes input.

## Decision table

Use when two or more conditions combine and each combination can change the result.

Conditions are columns. Each rule is a row. One row is the impossible or rejected combination.
Write the action for that row. Do not leave a condition pair implicit.

## State transition

Use when the outcome depends on the current state and an event, not on the input alone.

Name the states and the event. Cover one legal transition and one illegal event from that state.
Record the state you start from. A diagram is optional; the table is enough.

## Pairwise

Use when many factors exist but faults usually come from a pair, not from every combination.

Pick the factors and the levels. Cover each pair once. Do not expand to the full cartesian product.
Keep one explicit invalid pair so the grid is not only happy paths.

## Metamorphic

Use when you have no single expected value, but a change in the input should change the output in a known way.

Relation: reversing a reversible operation returns the original.
If the relation fails, the check fails. Do not invent an absolute oracle you do not have.

## Scenario

Use when a user goal crosses several steps and the risk is the journey, not one field.

Actor, first step, last observable result.
One scenario is one path. Alternate and error paths are separate scenarios, not a paragraph of maybes.

## Error guessing

Use after the structured techniques, for mistakes history says this area makes.

Name the guessed fault and the observation that would catch it.
This does not replace a partition or a boundary on an input. It adds the case those techniques missed.
