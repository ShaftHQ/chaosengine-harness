---
name: job-apply
description: >-
  Use when applying for a job. Default is draft only. A recorded
  owner standing send permission that names the channel class may send only
  after the shared gate passes on the exact final text.
license: MIT
---

# Job apply

Load this skill when the deliverable is **apply for a job** (email a recruiter, ATS form, Easy Apply, or similar). Default is draft only. Send authority is [outbound-send.md](../../references/outbound-send.md). The 13-step procedure is [references/apply-steps.md](references/apply-steps.md).

**Applicant profile (private):** identity, education, experience counts, form defaults, cover-letter priorities, title exclusions, base country, and remote rule live in a **private per-user store**. Never copy them into this skill tree or its references.

## Decide

| Question | Move |
| --- | --- |
| No standing send permission for this channel | Draft only. Stop before send. |
| The permission names the channel class | Send only after the shared gate passes on the exact final text. |
| A form, share, or publish the permission did not name | Ask first. |
| A hiring quiz or answer-on-your-own assessment | Person-only. Do not sit it. See the [ethics card](../../companions/ethics-card.md). |
| Two identical ATS verification errors | Stop. Draft the next channel. |

## Iron rules

- Distinct contacts or channels are separate drafts. A draft-scope order is not a send permission.
- Two independent reviewers each record PASS on the exact final text, and neither is the writer. A review sign-off is not a send license.
- Read the Sent folder back after a send. Search Sent before any resend.
- Never invent achievements, features, or metrics. Never put applicant names, emails, phones, employers, or personal stats into this skill tree.
- The ledger is a cache. Read the tracker back after every write.
- Run [check_abstraction.sh](scripts/check_abstraction.sh) before claiming this skill tree is clean.

Detail cards: [research](references/research.md), [template](references/template.md), [gate](references/gate.md), [lessons](references/lessons.md).
