# Lessons from the 2026-11-27 learn run

Source: host learn run `20261127-190351`, 28 kept sessions since the completed run on 2026-11-21 (`20261121-121105`). Seen 1703. Dropped: older_than_window 443, subagent 1025, headless 187, excluded_cwd 11, no_human_turns 9. Human turns read: 44. Mappers read 28 of 28. Map notes lost: 0. Reduce notes lost: 0. Verifier sections that failed: none. `actions.json` was an empty list. `disuse_evidence.sufficient` was false because the sessions span 6.2 days.

Tracked by https://github.com/ShaftHQ/chaosengine-harness/issues/284 and https://github.com/ShaftHQ/chaosengine-harness/pull/285. The 2026-11-21 record remains https://github.com/ShaftHQ/chaosengine-harness/issues/146.

## What happened

The owner ran host `/learn --since-last`. The report proposed no new skill, no skill edit, and no delete. While that report was ready, the owner said every learned lesson, including how the learn command itself runs, must be tracked on GitHub and added to this repository.

The host report lived under the host learn-run directory. [learn-traces](../../learn-traces.md) already described collect, map, reduce, verify, and report, and [harness-learn](../../harness-learn.md) already forbade a home-directory skill as the learning. Neither file said the launching session waits until `report.md` and `actions.json` exist, nor that the full run record lands under `references/details/`.

## Why

Ending the launching session before those two files exist drops the run at the next phase boundary. A chat summary is not a record the next session can open. The 2026-11-21 home-directory skills were already retired; this window repeated the same phrases because the host still injects some of them, not because the overlay lacks a second copy.

## How the learn command runs

1. Price the window before collect. This run: 28 sessions, 8 agents, about 19–54 minutes. Headless sessions stay out unless the owner includes them.
2. Collect sessions where a human sat. Drop subagent runs, headless runs, temp checkouts, and one-word smokes. Redact credentials. Write the manifest, sessions, surfaces, usage, and phrases.
3. Map in batches, reduce until one synthesis remains, then three skeptics (phrases, stale lines, deletes). They keep or drop. They add nothing.
4. The launching session stays until `report.md` and `actions.json` exist. A partial map is not a report. Apply nothing before both files exist.
5. Present the overview, the tables, and the coverage line.
6. File each kept gap as a git issue and land this retrospective in one lessons pull request. A host home skill directory is not the write.

A first run is step/curate, never an automatic delete. A window under 7 days, under 20 kept sessions, or limited to one working directory retires nothing. Zero proposed actions is a valid report.

The portable command remains `python3 .chaos-engine/runtime/learn_traces.py learn --out <run-dir>`. This note does not vendor a host workflow file.

## Continue

- Join the contract that already owns the phrase. Do not add a second skill for work-item, kanban, consult, execution workflows, or self-improve.
- Leave zero-use bundled skills and protected plugins installed when the window is too narrow, and when the owner already refused those deletes (2026-11-21).
- Keep OpenBot teammate wording on the host. It names host tools. The 2026-11-21 record already refused that port.

## Stop

- Do not treat a host learn report, or the chat summary of it, as the ChaosEngine record.
- Do not recreate `openbot-developer-instructions` or `issue-orchestrator`. The 2026-11-21 run retired those home copies. The slash injection is still a host injection.
- Do not use a clean installation to drop an edited owned file, a directory, a live memory file, or a knowledge store. Uninstall copies edited owned files to `.chaos-engine-state/kept-edits/` and then removes the receipt-owned overlay. Byte-match unlink of a retired receipt path is the upgrade path, not uninstall.

## Start

- After `report.md` and `actions.json` exist, file the git record before the session ends. Owned by [harness-learn](../../harness-learn.md) and [learn-traces](../../learn-traces.md). Issue: https://github.com/ShaftHQ/chaosengine-harness/issues/284.
- The words "clean installation" mean uninstall, then the install one-liner. An upgrade unlinks a receipt path this install no longer ships only when the bytes still match (`remove_retired_receipt_files`). Owned by [INSTALL.md](../../../INSTALL.md).

## Outcome changed

A later session that finishes a learn run and would have stopped at the host report, or that would have written a home-directory skill, now waits for the two report files and files the retrospective in this repository. An operator who says "clean installation" can read the definition instead of an unrecognized phrase.

## Evidence

| Phrase | Sessions | Portable owner |
| --- | --- | --- |
| Plain-words answer and the host tool bridge | `01a21e61-4c36-7a71-a72e-fb65341eacb5`, `01a21bbc-1a9b-7340-b291-adef90f3a0cb`, `01a21bb6-1b4f-7292-b86d-1aa2a9655987`, `01a2184a-7328-78e2-9735-3e24470b8a89` | Host slash injection. Not ported. |
| Act as orchestrator and delegate in parallel | `01a207bc-fb39-7883-befa-e367c7f4d366`, `01a207d5-023d-7d42-babe-a692ee7ccce0`, `01a20715-9a0a-7e51-8b9f-642b4902ef90`, `01a2049b-13a1-7442-bc4d-c5f298e91efd`, `01a203de-b345-7481-8535-ea5088ba87fb`, `01a2004c-e3ff-75a0-a53b-4578d4b98830` | [execution-workflows](../../execution-workflows.md). Home `issue-orchestrator` stays retired. |
| Merge it / merge after reviews | `01a208ea-f0b8-7893-b2d3-3b176b61c993`, `01a207bc-fb39-7883-befa-e367c7f4d366`, `01a2049b-13a1-7442-bc4d-c5f298e91efd` | chaos-engine: work is not done until the pull request is merged. |
| PR and merge only when the user says so | `01a20357-9230-7482-9c5c-cd1d347492bd`, `01a207ef-0d4b-79c3-9a3f-6b3fe23652d8` | hrsd-git in the other repository. Not a ChaosEngine skill. |
| Run a learning retrospective | `01a21dd3-2a23-73c2-afa1-fc5ee439404e`, `01a20715-9a0a-7e51-8b9f-642b4902ef90`, `01a2004c-e3ff-75a0-a53b-4578d4b98830`, `01a1fd5f-3eff-7e81-8ba8-20539c2563bb`, `01a1fe05-35ac-7cc1-8c41-1b1257746dc2` | [self-improve](../../../skills/self-improve/SKILL.md) |
| Clean installation; upgrade must remove old files | `01a2049b-13a1-7442-bc4d-c5f298e91efd`, `01a203a1-88ec-7fa0-8be9-8a96c0cc6d59` | INSTALL.md, this record |
| Pick up five named Antigravity conversations | `01a207d5-023d-7d42-babe-a692ee7ccce0` only | Delivered in https://github.com/ShaftHQ/chaosengine-harness/pull/271. Not a new skill. |

## Dropped by the verifiers

- "Deliver all the work in one mega PR" was not a denial of the kanban supersede sentence. The cited turns tell the session to supersede open pull requests into one.
- The hrsd-git line "Upload only when the bytes differ" stayed. The locked workbook was another person's file, not a contradiction of that sentence.
- Previously refused deletes stay refused: build-with-ai, code-review, create-skill, create-workflow, design, execute-plan, implement, pr-babysit, skill-design-principles, statusline, threejs-frame-conventions, the Figma skills and plugin, enabled-but-not-installed plugin ids, and the bundled `deep-research` and `learn-traces` workflows.

## Next action

Merge https://github.com/ShaftHQ/chaosengine-harness/pull/285 after the required check is green and the two reviews have passed.

## Enhancements

- tracked: the wait-then-file rule, the clean-installation definition, and this retrospective, https://github.com/ShaftHQ/chaosengine-harness/issues/284 and https://github.com/ShaftHQ/chaosengine-harness/pull/285
- tracked: https://github.com/ShaftHQ/chaosengine-harness/pull/271 already delivered the named Antigravity conversations
- rejected: a new skill for the host plain-words block, because it names host-only tools and the 2026-11-21 record already refused the port
- rejected: recreating `issue-orchestrator`, because execution-workflows already owns parallel delegation
- rejected: retiring the zero-hit skills in this window, because the sessions span 6.2 days
- rejected: deleting edited receipt files during upgrade, because `remove_retired_receipt_files` keeps bytes that differ from the receipt
- rejected: a skill for the host `schedule` slash, because no kept phrase says what it should do
- rejected: a ChaosEngine edit for workbook force-unlock, because that instruction belongs to hrsd-git and the verifier dropped the proposed edit
