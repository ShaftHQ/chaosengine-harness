# Box durability

Grok-box operational checklist. Load on demand. Not part of the always-loaded entry.

1. At entry after a restart, run `free -h`; if swap is `0`, re-add it (`fallocate -l 8G /swapfile`, `mkswap /swapfile`, `swapon /swapfile`, `sysctl vm.swappiness=10`).
2. Only `/workspace` survives Update Bot's Computer / recover / reset. Keep work product there.
3. Update Bot's Computer runs only when no bot is busy. Go idle when asked.
4. A `.git` directory can become a husk after restart (missing `objects/` or `refs/`, or a born HEAD whose objects are gone). `git-husk` is a warn unless the secret guard cannot run. A valid empty repo (`git init`, unborn HEAD, `objects/`+`refs/`) is not a husk. Remote recovery is re-clone or fetch; local-only is `git init` plus explicit paths, never `git add -A`. ChaosEngine install does not create `.git` in non-git dirs.
5. Scripts that mutate state use `set -e`. Stage explicit paths only. Never `git commit -a` or `git add -A`.
6. Freshly generated assets: checkpoint or commit them in the same turn.
7. Disk gate before a new worktree or clone: warn under 15 GiB free, block under 10 GiB or at the linked-worktree cap. Prefer one blobless clone plus worktrees. Keep `graphify-out/` and `.chaos-engine-state/` untracked.
8. Keep tools and drafts outside `/tmp` (a box restore wipes it) and check `git ls-files -d` before each push.
