# Security pyramid

Read-only audit and in-repo test design. Name the oracle and the expected status. Do not write exploit procedures, payloads, or covert access steps. An active probe runs only when `scan_posture` is `authorized` for a named local, disposable, or owner-authorized target.

## Standards map

Cite each finding with the ids that apply:

| Standard | How to cite |
| --- | --- |
| OWASP Top 10 2025 | The published category name and id. |
| OWASP ASVS 5.0.0 | `v5.0.0-V<ch>.<sec>.<req>` |
| OWASP API Security Top 10 2023 | API1 BOLA, API2 Broken Authentication, API3 Broken Object Property Level Authorization (mass assignment), API5 BFLA, API7 SSRF, API8 Security Misconfiguration. Also API4 Unrestricted Resource Consumption, API6 Unrestricted Access to Sensitive Business Flows, API9 Improper Inventory Management, API10 Unsafe Consumption of APIs when they apply. |
| OWASP MASVS v2.1.0 + MASTG | Mobile surfaces only. Pair the MASVS control with the MASTG test case. Do not apply MASVS to a server API. |
| CWE | The weakness id. Examples: BOLA CWE-639, broken authentication CWE-287, mass assignment CWE-915, BFLA CWE-285, SSRF CWE-918, path traversal CWE-22, bad JWT signature CWE-347. |
| NIST SSDF SP 800-218 | The producer task group: PO prepare, PS protect, PW produce, RV respond. |

## Stack

Each layer assumes the one above it. A gap at a lower layer is not a reason to skip to an active scan.

1. **Requirements.** Name the asset, the trust boundary, and the acceptance oracle before choosing a tool. Map the requirement to ASVS 5.0.0 and, for an API, to the 2023 API Top 10 item.
2. **SAST.** Semgrep, CodeQL, Bandit, and SpotBugs with FindSecBugs on the owned repository. A match is unconfirmed until the second pass. Do not treat a rule id as proof of exploitability.
3. **SCA and SBOM.** Trivy, OSV-Scanner, Grype, `pip-audit`, and `npm audit`. Produce a CycloneDX or SPDX SBOM for the build that was tested. Record the package, the version, and the advisory id.
4. **Secrets and IaC.** `runtime/secret_guard.py` on commit and push. Gitleaks or TruffleHog for history. Checkov or Trivy config for infrastructure. A detected secret is rotated by the owner. Do not copy the secret into the finding.
5. **Executable security tests.** In-repo negative tests at `design-only` posture. Assert the oracle and the expected status only:
   - Authorization matrix: each role and operation expects 200, 403, or 404. A missing credential expects 401.
   - JWT: `alg` none, expired, and bad signature each expect 401. Do not include a token value.
   - CORS, CSP, and security headers: expect the configured allow-list and header names. A reflected origin or a missing CSP is a finding.
   - Path traversal: a traversal segment expects 400 or 404. Do not assert file contents.
   - Mass assignment: an extra or privileged field is ignored or expects 400, and the stored record does not change.
   - Local-sink SSRF: a blocked internal target expects 400 or the documented timeout. Do not name a metadata address or a callback host.
6. **Passive DAST.** ZAP baseline or safe mode against a local or disposable instance the owner already runs. Passive mode does not attack. Findings stay unconfirmed until the second pass.
7. **Authorized-only active DAST.** Only when `scan_posture` returns `authorized` and the target is the named disposable or owner-authorized host. Refuse a production host, an unnamed host, and any target we do not own and the owner has not authorized. Stop on `stop`.

## Confirmation

`classify` returns `confirmed` only when the repository is owned, the verifier is not the writer, and the second pass verified the finding. Otherwise the finding stays `unconfirmed` or the task `stop`s.
