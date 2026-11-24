# Delivery cycle

Standard order. A one-file reversible change uses the 1-line bigger-picture note, retrieve-first, and the read/fix/prove path. No multi-page spec. The cap is not a quota.

## Order

1. Architect. Bigger picture first, then the architect tier for the blast radius.
2. Run at most 3 PDCA iterations (Plan, Do, Check, Act). Stop when Check accepts. Do not start a fourth iteration. Two failed attempts on one approach: step back and re-plan. "At most 3" is a cap, not a quota.
3. Self-accept, then push and start adversarial review 1 together. Do not wait for CI before review 1. Do not start review 1 and review 2 in the same step. Do not run the two reviews in parallel.

Ordinary reversible changes, including a typo-sized diff and non-code work, get one fresh-context adversarial review. There is no zero-review path. Public-contract or hard-to-reverse changes, irreversible work, or an outbound action get two independent adversarial reviews, and those two run one after another. The author is neither reviewer.

Sequence:

1. Develop, then test, then self-accept. Then, without waiting for either to finish, push the branch so CI starts and start Adversarial review 1 on that same head.
2. Fix whichever of review 1 and CI returns first. Do not push during this step.
3. Wait for the other result, then reconcile locally. One push follows. One-review work finalizes after this step.
4. That push starts CI and adversarial review 2 together. Review 2 is a new reviewer instance. Do not start it beside review 1. Two-review work runs this step before finalize.
5. Develop, test, and accept review 2's findings before that push.
6. Finalize. The last push starts the final CI. Do not open a third review for a CI-only repair that only makes the failing check pass. A CI-only repair on the final watch does not start a third reviewer.

Merge:

- Never arm `gh pr merge --auto`.
- When the base branch ruleset includes a `merge_queue` rule, enqueue with `gh pr merge` and pass no strategy flag (`--merge`, `--squash`, or `--rebase`). The merge queue owns the merge method.
- Otherwise, including this repository, merge with `gh pr merge --squash` only after required checks are green and review threads are resolved.
- A pending check is not success.
- A skipped required check is not success.
- A skipped or neutral check outside the required set does not block.
- A failed, cancelled, or pending check blocks when it is required and when no check is marked required.
- If the pull-request diff touches `install.py`, `bootstrap.py`, `runtime/dependencies.py`, `install.sh`, or `install.ps1`, a failed, cancelled, or pending `installer-contract` check blocks squash-merge even when another required check is green. When the pull-request file list is truncated or incomplete, the gate fails closed on red `installer-contract` checks.
- An unmarked skip blocks.
- An empty check list is not success.
- When the only remaining gate is an owner-only artifact this session cannot create, record `blocking: unverifiable` once and end the goal (`runtime/owner_gate.py`).

A commit that acts on review N is the input to review N+1. It does not restart finished reviews in parallel. Do not review an unchanged head a third time.

Each reviewer gets a diff-scoped packet (artifact, SHA, acceptance, proof, checklist). A packet that contains a `## Plan` heading or author reasoning fails the packet lint. LGTM alone is not a pass. A timeout counts as the round already used and falls back to self-review with no retry.

The default reviewer is a fresh-context instance of the active host's local CLI or subagent primitive (any AI client). A missing second local CLI fails open and logs `second lens unavailable`. Fail open only if no second CLI is configured. It does not spawn a cloud agent.

Future: when another local CLI subscription exists, hand it the same packet. No Cursor cloud agent and no extra machine without an in-the-moment owner yes.

On the fourth iteration the orchestrator stops and reports. Reviewers run the brief's named test once. A watcher that exits because the branch moved is not a new review. Investigation close: [investigate lessons](investigate-lessons.md).

## Review budget

Set the budget before the first review.

- **MIN.** At least 1. There is no zero-review path. Two reviewers for a public contract, irreversible work, or an outbound action (ShaftHQ/SHAFT_ENGINE#8048 R2, ShaftHQ/SHAFT_ENGINE#8055). This budget does not lower that floor.
- **MAX.** Small reversible work (docs only, or one file): MAX = MIN. Medium: MIN + 1. Large, cross-cutting, or high blast radius: MIN + 2. MAX never exceeds the PDCA cap.
- **At MAX.** A finding blocks only if it is wrong, unsafe, or untruthful. Log every other finding as a follow-up. It does not start another round.
- **Next review.** A blocker fix is a new head and the next sequential review, which counts as a round. A timeout counts as the round already used and falls back to self-review with no retry. If no round is left within MAX, stop and report.
- **Handoff.** Record `review_budget` (min, max, inputs), `review_rounds_used`, and the logged follow-ups (ShaftHQ/SHAFT_ENGINE#8054).
- **Owner override.** An explicit owner instruction may set the budget, but never below MIN. When it also says to fix blockers and then merge without another round, that lifts the new-commit sentence for that item only.

Spec: ShaftHQ/SHAFT_ENGINE#8063.

## Session lift

An explicit owner instruction may lift the iteration cap or the review cap for the active session only when it names the cap. Deliver, finalize, and ship do not name the cap. Review 1 still starts with the self-accept push, and the two reviewers still do not start in one step. Do not review an unchanged head a third time unless that same instruction lifts that sentence too.

## Complex media

Complex video or audio editing follows [design-review-video-checklist.md](design-review-video-checklist.md). For that edit, one accepted Check is not final. A new cut is a new head, so an unchanged head is still not reviewed a third time.

## Git identity

Set `GIT_AUTHOR_NAME`, `GIT_AUTHOR_EMAIL`, `GIT_COMMITTER_NAME`, and `GIT_COMMITTER_EMAIL` on the command that creates the commit. Environment committer variables override `git -c user.*`. `git rebase --onto <base> <base>` is a no-op and does not rewrite the committer. When the intent is the commits after a revision, use `git format-patch <rev>..HEAD`. `git format-patch -N <rev>` writes the N commits that end at that revision, not the N commits after it.

## Closing keywords

GitHub closes an issue when a default-branch commit message or a merge message contains one of these words immediately before an issue number: `close`, `closes`, `closed`, `fix`, `fixes`, `fixed`, `resolve`, `resolves`, or `resolved`. A negation does not protect the issue. The match still fires when the sentence denies the action, because the word still sits immediately before the number.

Name the issue without those words beside the number. The safe example is: issue #160 stays open.

An unsafe example puts one of those words immediately before the number, including inside a denial. Keep that example as this prose. Do not write the word next to the number.
