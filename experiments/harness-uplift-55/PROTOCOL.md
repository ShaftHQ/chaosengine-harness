# Pre-registered harness uplift protocol

Successor to the published #45 measurement. That rubric, prompt, and result set stay untouched.
No arm has been run. A paid run stays blocked until the owner approves the spend.

## Decision before any run

Install trees do not consume the 120_000 character source cap. `bundle.py` skips `.chaos-engine`, `.chaos-engine-state`, `.grok`, `.git`, `target`, `.agents`, and `.memory`. `pom.xml` and `src/` are ordered before other files so the test project is not crowded out by install trees. This is the #55 fix. It is not a rescore of #45.

## Frozen inputs

- Rubric and prompt: the published files under `experiments/harness-ab/` (`rubric.md`, `PROMPT.txt`). They are read, not edited.
- Arms: bare, generic `AGENTS.md`, ChaosEngine.
- Runs: at least 5 per arm, interleaved `A1 B1 C1 ...`.
- Same model, reasoning setting, client version, and machine on every arm.
- Hosts: the #45 host, plus one second host (Claude Code or Codex) using the same task.
- Report uplift as ChaosEngine minus `AGENTS.md` and minus bare, with median and range, whether it is a win, a tie, or a loss.

## Not done

No model was called. No cost was measured. `cost_usd` for this protocol is null, not zero.
