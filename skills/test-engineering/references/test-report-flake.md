# Reports and flake triage

Load this for red CI, a flake, CTRF, JUnit, Allure, or an ISO 29119 completion or incident report. The technique menu stays in [test-design.md](../../../references/test-design.md).

## Machine-readable first

1. CTRF JSON when the file declares a pinned schema.
2. Else JUnit XML.
3. Else one summary line: `tests=<n> failed=<n> errors=<n> skipped=<n>`.

Cite Allure HTML, Playwright HTML, and `trace.zip` as artifact paths. Never paste HTML.

## ISO 29119-3

Completion and incident stay Markdown.

Completion sections: scope tested, the `traceability_matrix_full` table, what was not measured, and open defects.

Incident sections: summary, severity, how to reproduce, impact, the evidence path, and the preventive check id.

Six columns, one data row per check. Every cell is required. A blank cell is `incomplete-trace-row`. A header row or a `| --- |` separator does not satisfy `iso_29119_template("completion")`.

| Requirement | Risk | Technique | Check | Result | Defect |
| --- | --- | --- | --- | --- | --- |
| FR-1 | 12 | 3-value BVA | check-1 | failed | D-1 |

## Flake triage

Rerun the failing check three times, isolated, with the same seed. `flake_quarantine_gate` follows `rerun_flake`.

- Three identical failures: `stable-failure`. A quarantine record cannot turn that into a pass.
- Any disagreement, or fewer than three runs: a flake. Quarantine is mandatory, and it is never a pass.
- Required fields: non-empty `owner`, non-empty `ticket`, `cause` of `timing-async`, `state-leakage`, `network-env`, `locator`, `order-dependence`, or `time-random`, and an ISO date `expires` from today through today plus 30 days.
- A missing, unknown, or out-of-window field is `flake-quarantine`.
- The gate returns `defect_type` set to that `cause` for `task_ledger.defect_ratchet`. A repeated cause blocks the next item until a preventive check id exists.

## Agent report (about 150 tokens)

Verdict, counts (passed, failed, quarantined), the first failure (name, oracle, one-line reason), and artifact paths. Then at most 15 lines of that first failure. Stop. No raw HTML, no full SARIF, and no second dump unless asked.
