---
name: test-engineering
description: Use when you route test analysis, coverage evidence, flake triage, and an ISO 29119 report.
license: MIT
---

# Test engineering

Load exactly one L2 reference this turn. Do not load a second one.

| Need | Load |
| --- | --- |
| New tests, a test plan, or AC, ADR, or diff analysis | [test-analysis-design.md](references/test-analysis-design.md) |
| Coverage, mutation, linters, type checks, or SARIF | [test-evidence-static.md](references/test-evidence-static.md) |
| Red CI, flake quarantine, CTRF, JUnit, Allure, or an ISO 29119 completion or incident report | [test-report-flake.md](references/test-report-flake.md) |

## Already specified elsewhere

Link these. Do not copy them.

- Techniques: [test-design.md](../../references/test-design.md)
- RED-GREEN-REFACTOR: [tdd.md](../../references/tdd.md) and [tdd-failure-modes.md](../../references/tdd-failure-modes.md)
- Merge policy: [static-analysis-gate.md](../../references/static-analysis-gate.md) and [complexity-gate.md](../../references/complexity-gate.md)
- AI system under test: `profiles/ai-sut/README.md` (source profile, not in the portable payload).

## Rules

Run the mechanical gate in [sdlc_flows.py](../../runtime/sdlc_flows.py) before claiming Done. A skipped gate is not Done.

Report the summary first (about 150 tokens): verdict, counts, first failure, oracle, and artifact paths. Paste at most 15 lines of a failure slice. Never paste raw HTML or a full SARIF document.

Never weaken a test, a threshold, or an analyzer to go green.
