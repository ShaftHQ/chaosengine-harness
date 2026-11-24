---
name: ci-cd
description: >-
  Use when PR merge waits are long or CI/CD is being designed, audited, or sped
  up.
license: MIT
---

# CI/CD tiers and PR merge time

Fix the loop first, then the slowest leg. Commands and diagnostics: [references/ci-cd-playbook.md](references/ci-cd-playbook.md).

## Decide

| Question | Move |
| --- | --- |
| Gate p90 is over 10 minutes, or open-to-merge median is over 15 minutes | Measure, then move the slowest leg off the PR tier |
| A leg is over 5 minutes, caught no PR-only regression in its last ~20–30 runs, and main runs it | Move it to push-to-main or nightly |
| A quality layer looks unused | Keep it unless repeated evidence shows it is utter waste |
| A post-merge leg is red | Roll forward. One tracker issue. Never auto-revert |
| A release workflow publishes | Hard gate before publish. `continue-on-error` only after publish |
| A workflow is privileged | `pull_request_target` and `workflow_run` never check out PR code |

## Tiers

| Tier | Runs | Rule |
| --- | --- | --- |
| PR (blocking) | path-filtered affected-module build, unit tests, lint, required governance | only what must block |
| Push to main | the same path filters, never cancelled, plus slow OS and E2E legs | one tracker issue on red, auto-close on green |
| Nightly | full cross-OS, live suites, security scans, EAP verifiers | tracker issue, no `Closes` keyword |
| Release | full verify, always | never weakened |

## Iron rules

- Measure before moving a leg. Report p50, p90, max, and the open-to-merge median.
- Tests, static analysis, coverage, and review may move. They are not removed. A moved layer keeps equal or better coverage.
- A new gate is done only after one real pass and one real fail.
- Run the cheap local checks before every push. Contract tests that CI runs with plain `unittest` import only the standard library.
- One PR at a time. Babysit it to merged. Read `mergeQueueEntry`, not a null `autoMergeRequest`.
- A required check uses its own concurrency group (`github.run_id`) and `cancel-in-progress: false`.
- Pin actions to a full commit SHA. `permissions: contents: read` is the floor.
- Checked action docs: https://docs.github.com/en/actions/reference/workflows-and-actions/workflow-syntax.md, https://docs.github.com/en/actions/reference/security/secure-use.md, https://docs.github.com/en/actions/tutorials/store-and-share-data.md, https://docs.github.com/en/actions/how-tos/write-workflows/choose-what-workflows-do/run-job-variations.md, and https://docs.github.com/en/actions/how-tos/write-workflows/choose-what-workflows-do/find-and-customize-actions.md.

## Report

Before and after p50/p90 gate time, the open-to-merge median, the PRs merged, and the admin changes left for the owner.
