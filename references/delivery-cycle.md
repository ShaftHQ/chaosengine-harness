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
3. Self-accept, then push and start adversarial review 1 together. CI and
   that review run at the same time. Do not wait for CI before review 1.
   Do not start review 1 and review 2 in the same step. Do not run the two reviews in parallel.
   Never run two adversarial reviews of one change at
   the same time. Parallel reviews duplicate findings and waste the round.
   Kanban review WIP 2 is two cards, not two reviewers of one change.
   The second review is kaizen: it looks for what the first missed
   after those findings are fixed.
   The floor is one adversarial, unbiased, fresh-context review on the same
   model for every change, including a typo-sized diff and non-code work
   (specs, stories, test plans). There is no zero-review path. Automated
   checks and pre-done are not a substitute. A public contract, irreversible
   work, or an outbound action still needs two independent adversarial reviews,
   and those two run one after another. The author is neither reviewer.
   The sequence:

   1. Develop, then test, then self-accept. This Check is the author. It is
      not a review. Then, without waiting for either to finish, push the
      branch so CI starts and start Adversarial review 1 on that same head.
      One fresh-context reviewer, prompted to refute. The author is not the
      reviewer.
   2. Fix whichever of review 1 and CI returns first. Do not push during
      this step. A CI failure is reproduced and fixed locally. A review
      finding that refutes the change is applied and tested locally.
   3. Wait for the other result, then reconcile locally. A later CI failure
      is fixed only when it is still present after the review edits. A later
      review finding is applied only when it is still true after the CI
      fixes. One push follows that reconcile. That push is the only push for
      this cycle.
   4. That push starts CI and adversarial review 2 together. Review 2 is a
      new reviewer instance. Hand it review 1's verdict and the fixes, and
      ask it to refute what review 1 missed. Do not ask it to repeat
      confirmed findings. Do not start it beside review 1. Repeat steps 2
      and 3 for review 2 and that CI. One push follows.
   5. Develop, test, and accept review 2's findings before that push.
   6. Finalize. The last push starts the final CI. Do not open a third
      review for a CI-only repair that only makes the failing check pass.
      If that repair changes behavior beyond the failing check, repeat step
      4 once instead of opening a third reviewer. Arm `gh pr merge --auto`
      only when the platform queues the merge until required checks succeed.
      When that arm would merge immediately, watch until every check on the
      head has finished successfully and no review thread is unresolved,
      then merge with `gh pr merge --merge`. A pending check is not success.
      A skipped required check is not success.
      A skipped check outside the required set does not block.
      An empty check list is not success.
      A failed or cancelled check still blocks when it is required, and it
      still blocks when no check in the rollup is marked required.
      `gh pr merge` is refused until then, including when `--auto` is present.

   One-review work finalizes after step 3. Two-review work runs steps 4 and
   5 before finalize. A commit that acts on review N is the input to review
   N+1. It does not restart the finished reviews in parallel. Do not review
   an unchanged head a third time.
   Each reviewer gets a diff-scoped, time-bounded packet: the changed
   artifact, the SHA, acceptance criteria, proof commands, and the checklist
   (missing tests, hidden scope, unverified claims, reader-cost, safety).
   The packet does not include the author's plan, chain-of-thought, or tool
   transcript. A packet that contains a `## Plan` heading or author reasoning
   fails the packet lint. A passing review names the SHA and cites that
   checklist. LGTM alone is not a pass. A timeout counts as the round already
   used and falls back to self-review with no retry. A blocking finding is
   Act inside the sequence above. If no iteration remains, stop and report.

The default reviewer is the same local Grok path the owner already uses.
A missing second local CLI fails open to that same-model review and logs
one line (`second lens unavailable`). It does not spawn a cloud agent.

Future: when another local CLI subscription exists, the same packet can be
handed to that CLI. That path is not implemented here. No Cursor cloud agent
and no extra machine without an in-the-moment owner yes.

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
- **Next-review rule.** Logged follow-ups are not committed in this
  delivery, so the reviewed head stays the head that ships. A blocker fix is a
  new head and the input to the next sequential review, not a reason to
  restart finished reviews in parallel. That next review counts as a round. A
  timeout counts as the round already used and falls back to self-review
  with no retry. If no round is left within MAX, stop and report as the
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
Architect still comes first. Review 1 still starts with the push of the
self-accepted head, and the two reviewers still do not start in one step.
Do not review an unchanged head a third time unless that same
instruction lifts that sentence too.

## Complex media

Complex video or audio editing follows the standing rule in
[design-review-video-checklist.md](design-review-video-checklist.md).
That rule is not limited to the active session. The cap in this file
stays as written. For a complex video or audio edit, one accepted Check is not final.
Other work still stops when Check accepts. A new cut is a new head, so an
unchanged head is still not reviewed a third time.

## Git identity

Set `GIT_AUTHOR_NAME`, `GIT_AUTHOR_EMAIL`, `GIT_COMMITTER_NAME`, and
`GIT_COMMITTER_EMAIL` on the command that creates the commit.
Environment committer variables override `git -c user.*`.
`git rebase --onto <base> <base>` is a no-op and does not rewrite the committer.
When the intent is the commits after a revision, use `git format-patch <rev>..HEAD`.
`git format-patch -N <rev>` writes the N commits that end at that revision, not the N commits after it.

## Adoption

The core card, kanban Definition of Done, router contract, and delegation
point here for the count and for the order. The floor in this file is the
count: one review, or two when the stakes say two. The order is always
sequential. There is no zero-review path. Investigation
close rules: [investigate lessons](investigate-lessons.md).

## Decision

Ordinary changes get one fresh-context review. Public contracts, irreversible
work, and outbound actions still get two independent adversarial reviews,
one after another, because one pass was signing those changes and because
running both at once duplicated findings. Review 1 starts with the push of
the self-accepted head. The first fix starts from whichever of review 1 and
CI returns first. The next review starts only after the other result is
reconciled and one push lands. The cap stops the loop. A CI-only repair on
the final watch does not start a third reviewer.
There is no zero-review path. Merge waits for that sequence and for every
CI check on the head to finish successfully. A pending check is not success.
