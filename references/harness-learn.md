---
name: harness-learn
description: Use when repeated session traces show the git-tracked overlay should change; tune the harness in the repo, never under a user-home skill directory (`~/.grok/skills` is one host example).
---

# Harness learn

Portable contract for tuning a git-tracked ChaosEngine overlay from repeated
session traces. Host-native collectors, TUI workflows, and `GROK_HOME` scripts
stay on that host. Do not install duplicates under `~/.grok/skills`. The same ban covers every user-home skill directory (`~/.claude/skills`, `~/.codex/skills`, `~/.agents/skills`, and the equivalent on any other host). Do not
edit bundled or plugin skills in place.

`<python>` is `py -3` on Windows and `python3` on Linux/macOS. Commands below spell `python3`; substitute `py -3` on Windows.

## Use when

The owner asks to learn from traces, retire unused harness surfaces, or turn
repeated instructions into git-tracked policy.

## Durable rules

- One repeated phrase is one action. Join the skill or reference that already
  owns the job; never recreate `learn`, `create-skill`, `self-improve`,
  `work-item`, or `pr-babysit`.
- Git-tracked targets land as a pull request. User-home skill copies are not
  a valid learning.
- Zero hits is evidence, not proof. The only copy of a job is an ask, not a
  delete. A skill other loaded skills reference is not a free delete.
- Protected bundled, plugin, and origin-tracked files are never patched in
  place. Propose a portable overlay change instead.
- Consent is per group. Unpicked options are deferred, not rejected.
- Secrets stay out of reports: names and paths only.
- The launching session waits until `report.md` and `actions.json` exist. A stop before those files leaves nothing to apply and nothing to file.
- After the report, file every kept gap on the git host, one issue per actionable problem, and land the full run record at `references/details/ce-lessons-<date>/learn-retrospective.md` in one lessons pull request. The host report and the chat summary are not the record.
- A window the report marks too narrow (fewer than 20 kept sessions, under 7 days, or a single working directory) retires nothing. Zero proposed actions is a valid report.
- Do not recreate a host skill that a previous run already retired. A slash injection that names host-only tools stays on that host.

Curation still uses [self-improve](../skills/self-improve/SKILL.md) after
delivery. Trace collection and map-reduce live in
[learn-traces](learn-traces.md).

Portable invocation (installed `.chaos-engine` only):

`python3 .chaos-engine/runtime/learn_traces.py learn --out <run-dir>`

That writes `report.md` + `actions.json` aimed at git-tracked overlay PRs, not
a user-home skill directory. `~/.grok/skills` is one host example, beside `~/.claude/skills`, `~/.codex/skills`, and `~/.agents/skills`. Host slash `/learn` adapters are thin pointers to the same
command; they must not vendor a TUI workflow into the overlay.
