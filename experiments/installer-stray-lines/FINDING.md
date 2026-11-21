# Stray `git` / `gh` / `node` lines

Issue #129. The lines are not shell tracing and not the SHAFT_ENGINE forwarding shim.

## Writer

`runtime/prerequisites.py`, function `plan`, the `print(tool, file=sys.stderr, flush=True)` call. On this commit that line is 215.

`plan` prints every required tool name before it looks up a version. A tool that is already installed is `skip`, and `provision` does not print skip rows. The one-liner runs non-interactively (`curl | bash` has no tty on stdin), so `mode()` is `report`. The names still come from `plan`.

Call chain: `install.py` `_attach_prerequisites` (line 10167) calls `prerequisites.run` (line 525), which calls `provision`, which calls `plan`.

For a git checkout whose `.git/config` contains `github.com` and which has no language-pack marker, the names are `git`, then `gh`, then `node`, each on its own stderr line. `node` is always required. A Maven project also prints the pack tool, from the same statement.

`provision` prints the name again, at line 248, only when the action is not `skip`. That second print is not the line a machine with current tools shows.

## Repro

From the repository root, with no install and no network:

```bash
python3 experiments/installer-stray-lines/repro.py
```

The harness one-liner and the SHAFT_ENGINE shim both end in this installer, so both transcripts pick up the same line. The shim's own "ChaosEngine moved to…" sentence is a different writer and is outside this repository.
