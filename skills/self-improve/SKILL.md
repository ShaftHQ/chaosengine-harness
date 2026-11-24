---
name: self-improve
description: "Use after final delivery for a Learning Session. Harness lessons are GitHub issues; product lessons may queue."
---

# self-improve — ChaosEngine learning & adapting

Lean CE-native skill informed by Task Observer methodology
(Eoghan Henn / rebelytics, **CC BY 4.0** — see [LICENSE](LICENSE) and
[UPSTREAM.md](UPSTREAM.md)).

Session procedure: [references/session-procedure.md](references/session-procedure.md).

## When

- **Primary:** Learning Session after every final delivery (owner approval, publish done, final PR merged), automatic: lessons diff against the skills, one spec issue, ONE PR (`skip-release-notes`, MERGE method) babysat to merged. Never arm `gh pr merge --auto`.
- **Secondary:** explicit operator request mid-session.
- **Not:** every casual turn, and never the Learning Session PR's own merge.
- A lesson already shipped in the delivery pull request is not a new issue. Finalize with nothing durable.

## Dual track

1. **Harness** — skills, hooks, MemPalace, Graphify, installer/doctor. GitHub issue only. Never a local queue and never chat.
2. **Product** — enhancements for the product under development (queued issues).

Details: [references/observation-taxonomy.md](references/observation-taxonomy.md).
Product track: [references/product-track.md](references/product-track.md).
Activation: [references/activation.md](references/activation.md).
Adopt/reject: [references/research-adopt-reject.md](references/research-adopt-reject.md).
Roadmap: [../../references/self-improve-master-plan.md](../../references/self-improve-master-plan.md).
Research/explore isolation: [../../references/context-firewall.md](../../references/context-firewall.md).

## How (wraps learning.py)

File a harness lesson as a GitHub issue. Queue only a product lesson through `learning.py --track product`. Never auto-install skill patches. Fields, commands, and the smoke check are in the session procedure.

Do not write unverified model output into trusted memory, heuristics, or skills.
A lesson that cannot name an outcome does not become a skill.

`meta_optimize.py review` is the offline cadence. `draft_skill_pr.py` is opt-in only (default OFF, never auto-merge). See [meta-optimize](../../references/meta-optimize.md) and [draft-skill-pr](../../references/draft-skill-pr.md).

## Retrospective close

Write the learning retrospective only after the merge SHA exists and after subagents and monitors have exited. A non-required check must not start the note and must not be the only reason the note waits.

The note names what happened, why, continue, stop, start, and next action: one change, or nothing actionable.

An actionable line is filed with `gh` on the configured upstream (`scripts/ci/chaos-engine-upstream.txt` external-example or `CHAOS_ENGINE_UPSTREAM_REPO`) when it is a ChaosEngine change, or on the project that uses ChaosEngine when it is private. `nothing actionable` is the only close with no URL.
