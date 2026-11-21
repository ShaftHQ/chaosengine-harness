# Test plan

Scope, in, out, and one mapping for every acceptance criterion.

## Risk register

Likelihood and impact are integers from 1 to 5. Level is likelihood times impact. A high impact (4 or 5) with no test is an owner decision, not a silent skip (`sdlc_flows.risk_register_gate`).

| Risk | Likelihood | Impact | Level | Minimum techniques | Test |
| --- | --- | --- | --- | --- | --- |
| | | | | | |

## Quality checklist

Mark each characteristic in or out. Names only. Do not quote a standard.

25010: functional suitability; performance efficiency; compatibility; interaction capability; reliability; security; maintainability; flexibility; safety.

25059 (AI system, when the subject is a model): functional correctness; robustness under input shift; controllability of the output; transparency of the decision.

## Requirement matrix

Embed the table from `sdlc_flows.traceability_matrix` (requirement, check, result).

## Techniques

Name the technique and the partition or boundary on each input-bearing check. See [test-design](../test-design.md).
