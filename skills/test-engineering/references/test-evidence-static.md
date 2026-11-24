# Test evidence and static gates

Load this for coverage, mutation, linters, type checks, or SARIF. Merge policy stays in [static-analysis-gate.md](../../../references/static-analysis-gate.md) and [complexity-gate.md](../../../references/complexity-gate.md). Do not restate it. Parse a JSON, CSV, or XML summary. Do not paste the tool's HTML.

## Coverage hierarchy

Line, then branch (decision), then condition, then MC/DC when safety is in scope. Mutation score is `killed / (killed + survived)`. Exclude timeouts, uncovered mutants, and equivalent mutants from that denominator.

## Patch gate and ratchet

`coverage_gate`: patch coverage is at least 80%, and at least 90% when `strict` is set (risk level 8 or higher, or security or safety in scope). Whole-repo coverage must be greater than or equal to the recorded base. A drop is `coverage-ratchet`. Equal to the floor passes. Below the floor is `patch-coverage`.

## Diff-scoped mutation

Run mutants on the changed lines only. Record the target path. `mutation_target_gate` requires that path when risk is 8 or higher (`missing-mutation-target` when it is empty or not a file under `repo_root`) and fails `survived-mutant` when any survivor entry is listed.

| Stack | Coverage | Mutation |
| --- | --- | --- |
| Python | pytest-cov, diff-cover | mutmut |
| JS/TS | Vitest or Jest (V8 or Istanbul) | StrykerJS |
| Java | JaCoCo | PITest |
| .NET | coverlet | Stryker.NET |
| Go | `go test -coverprofile` | summary JSON or CSV only |
| Rust | cargo-llvm-cov | cargo-mutants |

Read that summary. Ignore HTML dashboards.

## Static testing

Review the spec or contract, complexity, types, dead code, dependencies and licenses, and IaC (Dockerfile and CI YAML). Style lint is not the whole check.

| Target | Tools |
| --- | --- |
| Python | Ruff, mypy, Bandit |
| JS/TS | ESLint, Biome, tsc |
| JVM | SpotBugs, PMD, Checkstyle, ErrorProne |
| Go | golangci-lint |
| Rust | Clippy |
| Multi | Semgrep |
| Shell | ShellCheck |
| Image | Hadolint |
| Actions | actionlint |
| IaC | Checkov |

## SARIF 2.1.0

`sarif_gate` accepts `version == "2.1.0"` only. A result at `error` or `warning`, or with the level omitted, blocks when its artifact URI matches a changed path (POSIX, slash-normalized). `note` and `none` are recorded and do not block. The gate returns at most 20 rows (`max_rows`). One blocking row is `static-finding`. Paste at most 15 lines of that slice, never the raw document.
