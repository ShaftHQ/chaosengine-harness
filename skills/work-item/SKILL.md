---
name: work-item
description: >-
  Use when opening or rewriting a work item on any git-based SCM. Source-control
  agnostic; GitHub, GitLab, and Azure Boards are adapters only.
license: MIT
permissions:
  - read
  - write
---

# Work item

Load this skill when the deliverable is **open or rewrite a work item**. Do not
vendor Spec Kit or create `.specify/`. Keep GitHub PR delivery on
`work-github-playbook.md`. One GitHub issue tracks the full plan. When the owner names a currently active PR, deliver the plan and the user-issue fix in that same PR.

## Session handoff

When a session must stop with work still open, finish what this session can still land, then create one GitHub ticket that states where the next session picks up. Do not open a second pickup ticket for the same handoff.

Contract and adapters: [work-item.md](../../references/work-item.md).

## One item, one problem

One work item owns one actionable problem. Trackers list children; they do not
absorb them. Preserve existing acceptance when rewriting.

## Required Spec Kit sections

Every body must include:

- User Scenarios & Testing
- Edge Cases
- Functional Requirements
- Success Criteria
- Assumptions or Out of scope

Keep adopter template headings (for example bug or feature fields) so existing
validators still match.

When rewriting an existing item for Spec Kit hygiene, specialize User Story,
`FR-*`, and `SC-*` from that issue's own acceptance. The helper
`scripts.agents.issue_filing.rewrite_body_spec_kit` lives in ShaftHQ/SHAFT_ENGINE,
not in this repository. Keep the shared heading checklist; never paste the
generic stamp `Deliver the stated acceptance` onto unrelated tickets. Trackers
may keep a campaign-level story.

## Explore before writing

Check duplicates and parents first. One item, one problem. Then look up prior
lessons for the area. Do that before any cause.

K1. Inventory every observable defect before naming a cause. For visual or
terminal output, record each item as found or checked-clean: row and element
counts versus the total the screen states, exact text in a code block,
duplicates, cursor, alignment and glyph width, proportions against the
canonical asset, truncation, wrapping, and leftover rows. Non-visual work
skips that list with one line. The spec lists D1..Dn.

K2. Each cause is a hypothesis until a SHA permalink or a reproduction confirms
it. Label it `hypothesis` or `confirmed: <permalink or repro>`. Do not write
"this is" for an unconfirmed mechanism.

K3. Verify maps 1:1 to the D-items and the SC-* items. No orphan verify line.

K4. Name the repo's existing tests, linters, and static checks. Do not invent
a new gate when one already covers the change.

K5. When the change holds terminal, file, or process state, name exit, error,
and interrupt cleanup.

K6. The brief runs in order: inspect and confirm, fix per defect, verify,
finalize.

K7. Visual and output specs cover non-TTY and CI logs, `NO_COLOR`, `LANG=C`,
narrow and wide terminals, and resize, or name them out of scope. Windows
parity is covered or out of scope.

K8. Each visual defect names a golden or snapshot that would have failed
before the fix.

Write from [spec-template.md](../../references/spec-template.md). TL;DR is at
most 5 lines. The agent brief is at most 150 lines. Research detail is a
linked doc, not a second copy of the brief. A small reversible typo may use
the TL;DR plus Verify only. Line references are SHA permalinks.

## Spec self-review

- [ ] Inventory complete: every K1 item is found or checked-clean.
- [ ] Every cause is labelled hypothesis or confirmed, with a link.
- [ ] Verify maps 1:1 to D-items and SC-*.
- [ ] Existing gates, interrupt and cleanup, and K7 cases are named or out of scope.
- [ ] A regression test is named for each defect.
- [ ] A fresh agent with only this issue and the repo can start step 1. A cheap-model dry run is optional, and required only for the public-contract or hard-to-reverse tier.
- [ ] Finalization is present: move research docs, update links, delete temporary branches by name and tip SHA.

## Taxonomy

Exactly one primary type, exactly one lifecycle, at least one subsystem or
module. Missing taxonomy fails closed with a named reason. Ready needs a proof
plan; blocked needs at least one https dependency URL.

## Adapter selection

Detect the live CLI from the adopter environment. Do not assume GitHub.
Command maps live in the adapters reference named from the contract. Live
create/edit remains whatever CLI the adopter already runs; dry-run and fake
runners prove the other maps.

## Repository

One defect, one repository. `runtime/issue_repository.py` chooses it.

- A ChaosEngine harness defect (installer, hooks, skills, doctor, CI, this repo) is opened on `ShaftHQ/chaosengine-harness`.
- A SHAFT_ENGINE product defect is opened on `ShaftHQ/SHAFT_ENGINE`.
- Naming the other repository as the place to file does not move the defect. The vendored `chaos-engine` tree inside SHAFT_ENGINE is not a reason to file a harness bug there.
