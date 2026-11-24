---
name: security-audit
description: >-
  Use when auditing a repository we own or designing executable security
  tests in that repository. An independent second pass confirms each finding.
license: MIT
---

# Security audit

Route row; load this body on demand. Do not paste the body into the always-loaded card.

License check 2026-11-10: the studied Cloudflare skill was MIT. This file is original and does not copy that skill.

## Scope

Audit only a repository the owner names and that we are allowed to change. If the target is not a repository we own, stop. Do not produce attack steps.

## Mode

| Mode | Posture |
| --- | --- |
| `audit` | Read-only review of the owned repository. |
| `executable-tests` | In-repo negative tests. `scan_posture` stays `design-only`. |
| `active-scan` | Only when `scan_posture` returns `authorized` for a named local, disposable, or owner-authorized target. |

Call `scan_posture(repo_owned, target_named, active_requested, authorized_target=False)` in [verify.py](verify.py). `stop` ends the task. `design-only` may design tests and must not send active traffic.

## Findings

A finding is unconfirmed until a second pass by someone other than the writer verifies it. The writer cannot confirm their own finding.

Do not include exploit procedures, payloads, or covert access steps.

Classifier: `classify(repo_owned, verifier_is_writer, second_pass_verified)` in [verify.py](verify.py).

Standards and the control stack: [security pyramid](references/security-pyramid.md).
