# Delivery cycle

Standard order for ChaosEngine work. A one-file reversible change still uses
this order, with a one-line bigger-picture note. The cap is not a quota.

## Order

1. Architect. Bigger picture first, then the architect tier for the blast
   radius. A public contract records the premise, the options, the choice,
   and the non-goals.
2. Run at most 3 PDCA iterations. Each iteration is Plan, Do, Check, Act. Check
   is the tests and evidence for that iteration, including the in-session
   review phase. Stop when Check accepts. Do not start a fourth iteration.
3. Run two independent adversarial reviews of that accepted head, after required checks are green on that head.
   The author is neither reviewer. The
   reviewers are separate instances, both prompted to refute, and both must
   pass on the same head SHA. A blocking finding is Act. If an iteration
   remains, fix it, Check again, and repeat both reviews on the new SHA. If
   none remains, stop and report. Do not review an unchanged head a third time.
   A new commit invalidates both passes.

A finding outside the brief's fixtures and recorded non-goals is filed. The
head stays. The iteration is not spent. On the fourth iteration the
orchestrator stops and reports, with the open pull request and the filed
residuals. Reviewers run the brief's named test once and cite it. They do not
each re-execute the history. The parent does not run that suite again on a
SHA a reviewer just ran.
A watcher that exits because the branch moved is not a new review.

## Review budget

Set the budget at plan time, before the first review, and record it.

- **Inputs.** Diff size (files and lines), public contract (yes or no),
  irreversible or outbound action (yes or no), and blast radius (who or what
  breaks if the change is wrong).
- **MIN rounds.** At least 1. There is no zero-review path. Who reviews in a
  round, and how many reviewers it needs, stays as step 3 says. The
  one-versus-two reviewer floor (two for a public contract, irreversible work,
  or an outbound action) is owned by ShaftHQ/SHAFT_ENGINE#8048 R2 and ShaftHQ/SHAFT_ENGINE#8055.
  This budget does not lower it.
- **MAX rounds.** For small, reversible work (docs only, or one file),
  MAX = MIN. For medium work, MIN + 1. For large or cross-cutting work, or a
  high blast radius, MIN + 2. MAX never exceeds the PDCA cap above.
- **At MAX.** A finding blocks only if it is wrong, unsafe, or untruthful.
  Every other finding (polish, should-fix wording, nit, style) is logged as a
  follow-up, either an issue or a "Follow-ups" list in the pull request body.
  It does not start another round.
- **Same-SHA rule unchanged.** Logged follow-ups are not committed in this
  delivery, so the reviewed head stays the head that ships. A blocker fix is a
  new head. Step 3 applies to it: both reviews repeat on the new SHA, and that
  counts as a round. If no round is left within MAX, stop and report as the
  PDCA cap says.
- **Handoff.** Record `review_budget` (min, max, inputs),
  `review_rounds_used`, and the logged follow-ups in the handoff receipt
  (ShaftHQ/SHAFT_ENGINE#8054).
- **Owner override.** An explicit owner instruction may set the budget for a
  session or a work item, but never below MIN. When that instruction also says
  to fix blockers and then merge without another round, it lifts the
  new-commit sentence for that item only, as Session lift describes. Record
  that in the handoff.

Spec: ShaftHQ/SHAFT_ENGINE#8063.

## Not a quota

"At most 3" does not mean three iterations are required. Zero extra
iterations is the normal case when the first Check accepts.

## Session lift

The caps above are the default. An explicit owner instruction may lift
the iteration cap or the review cap for the active session only when it
names the cap. Deliver, finalize, and ship do not name the cap.
Architect still comes first. Reviews still start only after required
checks are green on that head. A new commit still invalidates earlier
passes. Do not review an unchanged head a third time unless that same
instruction lifts that sentence too.

## Complex media

Complex video or audio editing follows the standing rule in
[design-review-video-checklist.md](design-review-video-checklist.md).
That rule is not limited to the active session. The cap in this file
stays as written. For a complex video or audio edit, one accepted Check is not final.
Other work still stops when Check accepts. A new cut is a new head, so an
unchanged head is still not reviewed a third time.

## Adoption

The core card, kanban Definition of Done, router contract, and delegation
point here. They do not keep a one-review exception. Investigation close
rules: [investigate lessons](investigate-lessons.md).

## Decision

Chosen over a single fresh review, with a second pass only when a blocker
appears, because one pass was signing public-contract changes, and an
uncapped loop was repeating review on heads whose checks were not green.
Dual review starts only on a green head. The cap stops the loop.
