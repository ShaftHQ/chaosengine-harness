---
name: job-applications
description: "Use when choosing only the application channel (email, LinkedIn, or ATS). Draft and send stay in job-apply."
license: MIT
---

# Job applications, all channels

This skill only routes the channel. Send authority is [outbound-send.md](../../references/outbound-send.md). Research, the gate, and the draft are [job-apply](../job-apply/SKILL.md). Finding and ranking openings is [job-search](../job-search/SKILL.md).

Apply through whichever route the posting offers. Email, LinkedIn, and web forms are all in scope. Do not drop a fitting role because it has no email.

## Route

| Route | Do |
| --- | --- |
| `email` | CV attached, to an address printed on the official posting or careers page only. The send rule is outbound-send. |
| `linkedin` | Prefer Easy Apply. Read the resume file name and date LinkedIn will attach and use the current CV. A recruiter or hiring-manager note uses the reviewed text word for word. |
| `form` | Open the posting in the browser the user chose, or the host's own browser. Fill from the user's form answers and upload the CV. Salary and demographic answers come only from facts the user gave. Leave optional demographic fields at "prefer not to say" or blank unless the user chose an answer. Screenshot the filled form, then submit only when the send rule allows that form. Capture the confirmation page. |

A sign-in, captcha, one-time code, or new ATS account that needs the user is one step for them. Do the rest of the batch and come back. Do not restart the user's browser. Open a new tab. Do not prescribe an OS input API. A run stays on local tools unless the user approves a named cloud agent or an extra machine.

## Log

One tracker row per application: id, company, role, remote terms, route, recipient or URL, date and time in the user's zone, source URL, message id or confirmation text, and status. Keep a dated checkpoint of what went out, the shortfall, and blocked items. Report each application with its proof.

## Guardrails

- Never invent qualifications, postings, salaries, or deadlines. Never put secrets, client names, prices, or trainee data in outbound text.
- Do not re-apply through a channel already on the tracker. A different channel for the same role is fine when the user wants every channel used.
- One submit per form. If a submit looks like it failed, check for a confirmation or email before a retry.
- Never use AI-written answers where the posting forbids them. Ask the user for their own words.
