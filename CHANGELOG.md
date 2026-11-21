# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [Unreleased]

### Removed

- Removed the deja transcript store ([#64](https://github.com/ShaftHQ/chaosengine-harness/issues/64)). Token cost alone is enough. Upgrade strips an MCP entry a previous install wrote, then the strip list drops that store. `--with-deja` is not a flag.

### Added

- Installer contract workflow `.github/workflows/installer-contract.yml`: 16 jobs (OS, fresh or upgrade, and context), including an existing non-Maven project and a Maven project that is not SHAFT, each as fresh and as upgrade. The fast Windows pytest job stays in `install-windows.yml`.
- Issue #45 three-arm measurement is published in `experiments/harness-ab/REPORT.md`. Frozen mean totals: generic AGENTS.md 52.9, bare 50.2, ChaosEngine 20.2. Arm C's quality used the 120000-character bundle, which did not include its test sources.
- Per-file install sync with a verified cache, kept edits, pinned release checks, and version-pinned SHAFT skills for a project that depends on SHAFT_ENGINE.
- Windows installer job `.github/workflows/install-windows.yml`.

### Changed

- The installer draws the Quantum Mandate symbol scanned from `assets/brand/symbol-primary.svg`. At 84 columns or more the four-row mark sits beside the header. From 60 to 83 columns the three-row mark is stacked above it. Narrower terminals, ASCII mode, and `TERM=dumb` print one line, `[ChaosEngine <version>] <repo>@<ref> (<sha>)`. The core is `#FF3B4D` on a truecolor terminal and ANSI red on a 16-color terminal. The rest of the mark uses the terminal foreground ([#135](https://github.com/ShaftHQ/chaosengine-harness/issues/135)).
- Installer options resolve from one catalog (`runtime/install_options.py`) in the order flag, environment, `.chaos-engine.local.toml`, `.chaos-engine.toml`, user config, then default. `install.py config show --json` names each source. `config validate` exits 1 with `CE_CONFIG_INVALID` on a bad file. `instructions.mode = "replace"` in a file is refused. See [docs/configuration.md](docs/configuration.md) ([#114](https://github.com/ShaftHQ/chaosengine-harness/issues/114)).
- `--scope user` writes the user layer under the home directory and nothing in the target folder. `--scope both` installs the project, then the user layer. A user-layer `PreToolUse` defers when the project session already ran, and it blocks `git reset --hard` when no project install is active. `uninstall --scope user` restores the pre-image bytes ([#115](https://github.com/ShaftHQ/chaosengine-harness/issues/115)).
- `--mode merge` is the default. The instruction block sits first, after a BOM or YAML front matter, and a second merge writes nothing. `--mode replace` backs up under `.chaos-engine-state/backups/` and deletes only after the copy hashes match. Without a TTY it exits 2 with `CE_MODE_REPLACE_NEEDS_YES` unless `--yes` is set. `install.py restore --backup <stamp>` puts the prior bytes back ([#116](https://github.com/ShaftHQ/chaosengine-harness/issues/116)).
- A failed install shows the failing step, one cause line, and two options: a redacted pre-filled report (OSC 8 "Open pre-filled GitHub issue", or the short template URL plus `.chaos-engine-state/failure-report.txt`) and the agent prompt between horizontal rules. The same prompt is `.chaos-engine-state/agent-prompt.md`. `heal-handoff.md` lists both. The issue URL cap is 5578. Clipboard copy is opt-in (`--copy-prompt` / `CHAOS_ENGINE_COPY_PROMPT=1`); OSC 52 only when that variable is `osc52`. A non-healthy doctor after the steps uses this panel. `CE-INSTALL-CANCELLED` stays the short resume text ([#134](https://github.com/ShaftHQ/chaosengine-harness/issues/134)).
- The post-install summary is at most 18 lines. A TTY shows a receipt link instead of the four `Receipt` lines. Those four lines still print in log mode for one release; `.chaos-engine-state/install-receipt.json` and the `--json` key `installReceipt` (`commit`, `doctorStatus`, `doctorHealthy`, `doctorTotal`, `clients`, `trace`) replace them. `--verbose` keeps the first-session brief, landed/untracked lines, and host cards. An unhealthy doctor no longer says "Installed with warnings" ([#133](https://github.com/ShaftHQ/chaosengine-harness/issues/133)).
- Installer text uses the terminal foreground. Labels and captions are dim. Done, warning, failure, and the running step use the terminal's green, yellow, red, and cyan. Fixed RGB remains only on the mark's core, and only when `COLORTERM` is `truecolor` or `24bit`. `NO_COLOR` keeps dim on a TTY and still drops colour ([#132](https://github.com/ShaftHQ/chaosengine-harness/issues/132)).
- The installer redraws a TTY checklist in place even when `NO_COLOR` is set, keeps colour and cursor separate, and collapses the live block on success to one header plus the checklist and summary. Stage-0 prints `Installing ChaosEngine` and `Download:` only with `--verbose` or a Stage-0 failure. Tool probes no longer write bare names on stderr. Next is: open a host and invoke `/chaos-engine`, then doctor anytime. New flags: `--color=auto|always|never`, `--ascii`, `--no-hyperlinks`, and `CHAOS_ENGINE_JSON=1` ([#131](https://github.com/ShaftHQ/chaosengine-harness/issues/131)).
- Installer failure artifacts, the heal prompt, and the prefilled issue URL go through one redactor. Home paths, hostnames, `user:pass@` URLs, bearer credentials, known token prefixes, secret env values, and client-name denylist markers are removed. If redaction fails, the artifact says `redaction failed; artifact withheld`. The heal prompt asks before opening or updating an upstream issue or PR, or pushing ([#130](https://github.com/ShaftHQ/chaosengine-harness/issues/130)).
- Upstream pins follow the latest stable release the installer can run: uv 0.13.9, Node.js 26.13.1, Maven 3.10.1 (sha256 measured after the published sha512 matched), Temurin 25.0.5.1+2, MemPalace 3.12.0, Graphify 0.9.113, and Maven Tools 3.3.1. `ci.yml` and `roadmap.yml` use Python 3.14. `install-windows.yml` and `installer-contract.yml` stay on Python 3.11, the hook-launch floor. Product Python stays at maximumSeries 3.14 ([#90](https://github.com/ShaftHQ/chaosengine-harness/issues/90)).
- Adversarial review 1 starts with the push of the self-accepted head, beside CI. The two reviewers do not start in one step. A CI-only repair on the final watch does not open a third reviewer ([#89](https://github.com/ShaftHQ/chaosengine-harness/issues/89)).
- The installer records the absolute path of each tool it accepted. Later probes and store launches use that file, so an older `java` or `python` on `PATH` does not fail a hook after the installer passed. A missing recorded file falls through to `PATH`. Windows `.cmd` and `.bat` launchers go through `cmd /c`.
- Identity adds a step-back principle: name the real goal before work, and after two failed attempts on one approach stop patching, widen the search, and push back with the better option ([identity-step-back](references/identity-step-back.md)).
- A session that exceeds one hour writes one retrospective at SessionEnd. SessionStart creates one scratch folder for that session and its subagents. The report files enhancement notes as GitHub issues. A live Stop demands that retrospective in the reply once background work has exited. A Stop while a shell, monitor, or subagent is still in flight does not demand it ([#74](https://github.com/ShaftHQ/chaosengine-harness/issues/74)).
- Every SessionEnd report asks what can we learn from what happened so far for our harness or memory modules to avoid such failures in the future? A session at or under one hour writes that question and does not file issues. Enhancement filing stays after one hour, and a prevention note uses that same filing path. The next SessionStart sees an unanswered prevention line or its tracked GitHub URLs.

### Fixed

- A session past one hour shows the learning retrospective on a live Stop. Grok does not show a SessionEnd `systemMessage`, and the Stop hook had stopped asking, so the note never appeared in the chat. The demand waits until in-flight shells, monitors, and subagents have exited, and a `channel_closed` or `shutdown` Stop does not ask ([#74](https://github.com/ShaftHQ/chaosengine-harness/issues/74)).
- Temurin `25.0.5.1+2` stays one version in the stable-channel match, the `java` probe, and the Adoptium archive URL. A pytest-xdist worker does not write `user.properties` unless `CHAOS_ENGINE_USER_PATHS=1`.
- A `CERTIFICATE_VERIFY_FAILED` download retries that one request with the operating-system trust store and still checks the hostname. The filed installer issue contains the redacted trace, console log, doctor JSON, exception chain, and, for that TLS failure, the OpenSSL trust paths. The form does not ask the reporter to attach those files ([#99](https://github.com/ShaftHQ/chaosengine-harness/issues/99)).
- Install and upgrade print one `needs-repair` line and exit non-zero when doctor would require recovery for hosts, policy-overlay, Graphify, or MemPalace. Upgrade rebinds host and policy receipts before that check. Overlay VERSION is compared with the source pin; the manifest commit stays 40 hex. Graphify and MemPalace share one freshness revision stamped after the write. A broken managed `npm.cmd` names that path. Extract, index, and account commands close stdin and can take a wall-clock bound.
- An escalating contract row (invalid, migration-required), not only the string recovery-required, fails install closed.
- A blocked HTTP error names the status and the request URL path, with query, fragment, and tokens left out. A 403 with Retry-After, or a 429, retries that single request once instead of failing the whole install. MemPalace sqlite handles are checkpointed and closed so a later delete is not blocked by an open database.
- Grok activation follows `grok inspect --json`. A trusted project whose loaded hooks call `launch.py` is activated. `/hooks-trust` is the next step only when the project is not trusted or inspect did not return trust. A trusted project with a missing event names that event. Codex `.codex/hooks.json` is reported as configured, not running, until the operator trusts that hook definition in `/hooks`. `[features] hooks = false` is reported as disabled. Harness defects are filed on `ShaftHQ/chaosengine-harness` and SHAFT_ENGINE product defects on `ShaftHQ/SHAFT_ENGINE` ([#98](https://github.com/ShaftHQ/chaosengine-harness/issues/98), [ShaftHQ/SHAFT_ENGINE#8102](https://github.com/ShaftHQ/SHAFT_ENGINE/issues/8102), [ShaftHQ/SHAFT_ENGINE#8103](https://github.com/ShaftHQ/SHAFT_ENGINE/issues/8103)).
- SessionStart injects the identity Truth and Principles body on Claude, Codex, Gemini, and Copilot (ShaftHQ/chaosengine-harness). Claude reads it from `hookSpecificOutput.additionalContext`, including after compaction via SessionStart `source=compact`. A missing file, or a body that would exceed the SessionStart byte budget, still sends the path locator. PreCompact and PostCompact stay without a Claude context channel.
- Experiment evidence under `experiments/` stays in git and out of the portable adopter payload, including the bootstrap download and the README python-libraries scan. A measurement transcript that names the host no longer fails the distribution token scan. Files over the 2 MiB source cap are not published.
- A doctor store probe does not append a retrieve-usage row, so a second `install.py doctor --json` keeps the same `retrieveUsage.records` count. The README python-libraries inventory includes `packs/java/maven_tools.py` as an `importlib` source.
- Lean Grok config keeps a comment above a foreign table, merges into an existing `[skills]` or `[compat.*]` table, treats `[ui] # comment` as a header, and retries Windows locks with backoff. A Grok sync failure still records project identity. Test sandboxes no longer share one Grok home, and a real config.toml byte change fails the session.
- The Grok companions card a publisher writes into an install overlay points at `.chaos-engine/skills`, `.chaos-engine/references`, and `.chaos-engine/companions`. The retired `chaos-engine/` tree is not a read target.

## [0.4.20261115.5] - 2026-11-15

### Added

- Offline host-doc conformance now checks Claude Code, Codex, Gemini CLI, Cursor, and Grok layouts against the pinned fixture, warns or fails when a published tool-page example disagrees with its pin, and scores a Grok golden-task ledger where an unmeasured check is unknown or skipped, never a pass.
- Five-minute starts for a frontend developer and a backend developer.

### Changed

- INSTALL.md no longer tells a visitor to install from a ShaftHQ/SHAFT_ENGINE checkout. The overview no longer says the redirect is still open.
- The open-PR advisory recognizes `gh -R <repo> pr create|ready|reopen`, counts past the first page, and treats a non-UTF-8 config as a loud exit instead of an uncaught decode error. With no config file the cap stays review WIP times one stream, as the kanban skill states.
- A linked-worktree hook adopt now copies `session_token_usage.py` next to the hooks. Without it, every session-scoped tool call crashed and the lifecycle protocol reported that crash as invalid JSON.
- The pre-push secret scan reads every blob the push newly publishes and skips blobs already on a remote. A secret that is not on a remote still blocks when a later commit removes it from the tip. A plain Markdown file under `.cursor/rules` fails only the Cursor layout. A tool-page config key the pin does not list warns for every tool, including Claude and Cursor. A golden check passes only when it both ran and was measured. A worktree adopt refuses a symlinked `session_token_usage.py`.

## [0.4.20261115.4] - 2026-11-15

### Added

- Crash-safe, resumable long tasks (ShaftHQ/SHAFT_ENGINE#8065), on top of `tool.py checkpoint` / `resume`:
  - `checkpoint --start --workdir PATH` declares the work root. `/tmp` and `/dev/shm` are refused (exit 5, `--allow-volatile` to override); `$TMPDIR` and tmpfs roots warn. A ledger on volatile storage warns too.
  - Each step records the work root's git HEAD (or `--head`) and `--prereq` checks (`swap`, `disk:GiB`, `mem:GiB`) that `resume` re-runs.
  - `checkpoint TASK --verify` exits 7 when the pushed HEAD has no checkpoint.
  - `tool.py entry` and the SessionStart card list unfinished tasks for the project, newest first, with `Resume at:`; ones older than `CHAOS_ENGINE_RESUME_STALE_DAYS` (default 7) are marked stale. Done tasks are not listed.
  - A budget stop (exit 3) records a planned-stop row and prints "planned stop at step X; next Y".
  - `resume` names why the last session ended: box restart (boot after the last checkpoint), planned stop, or likely host cap.
- `tests/scripts/test_task_ledger_crash_safe_8065.py`: offline fixtures for each requirement.

## [0.4.20261115.3] - 2026-11-15

### Added

- `ROADMAP.md`, generated from epic ShaftHQ/SHAFT_ENGINE#8056 and its sub-issues in the epic's order by `.github/scripts/roadmap.py` (ShaftHQ/SHAFT_ENGINE#8061 R6). `--check` fails when the file no longer matches the epic; a weekly workflow runs it. The roadmap is a view, not a second tracker. It stays out of the adopter payload.

### Changed

- CONTRIBUTING describes the in-repo test suite and the roadmap. SECURITY points at `VERSION` instead of a dated version string.

## [0.4.20261115.2] - 2026-11-15

### Fixed

- `mcp_policy.py` host-config rewrites (GitHub MCP strip in `repair_user_github_mcp`, and the retired transcript-store strip) now go through the same locked, atomic, parse-checked writer as the Grok lean config (ShaftHQ/SHAFT_ENGINE#8070). This covers `~/.grok/config.toml`, `~/.codex/config.toml`, `~/.claude.json` and the other host MCP files. Files with nothing to strip are not locked or written. The test tripwire now also catches these writes.

### Added

- `update_config_file(..., validate=...)` takes a parse check, so JSON host configs are checked as JSON.
- `tests/scripts/test_mcp_policy_safe_writer_8070.py`: crash before rename, symlinked config, tripwire, no lock file when nothing changes, JSON output.

## [0.4.20261115.1] - 2026-11-15

### Fixed

- Grok user config (`~/.grok/config.toml`) edits are now safe (ShaftHQ/SHAFT_ENGINE#8070). Every write takes a lock, writes a temp file in the same folder, fsyncs and renames it into place. The file is re-read after the temp file is durable and replaced only if no other writer changed it; otherwise the edit is redone. It is refused if the result is not valid TOML or another writer keeps changing the file. A symlinked config is edited at its target. An interrupted or concurrent ChaosEngine write can no longer leave a torn file.
- Removing a ChaosEngine marker span now drops only the lines ChaosEngine owns. Tables another tool wrote between the markers (for example the Grok CLI's `[marketplace]` and `[[marketplace.sources]]`) are kept. For ordinary LF files, install then uninstall returns the user's file byte for byte (extra trailing blank lines, CRLF and a missing final newline may be normalized), and repeated installs no longer add blank lines.
- `[[array]]` tables now end the `[ui]` table and the outside `[compat.*]` tables the installer replaces, so UI pins are no longer added to a preceding array element and following array tables (for example `[[marketplace.sources]]`) are no longer deleted.

### Added

- `tests/conftest.py` points `GROK_HOME` at a throwaway folder for the whole run. A tripwire refuses and logs any `grok_lean_config` write under the real Grok home, and the session fails if it fired.
- `tests/scripts/test_grok_config_safety_8070.py`: torn writes, parallel writers, a foreign writer mid-edit and after the temp fsync, invalid TOML, symlinked configs, array tables next to `[ui]`/`[compat.*]`, and preserving unrelated sections.

## [0.4.20261114.7] - 2026-11-14

### Changed

- The one-liners default to `ShaftHQ/chaosengine-harness` `main`; receipts still pin the resolved 40-hex commit. An explicit install URL, `CHAOS_ENGINE_REPOSITORY`, `--source` and `--commit` still win (ShaftHQ/SHAFT_ENGINE#8057 R1, R3).
- The bootstrap accepts the source at the repository root (`skills/chaos-engine/SKILL.md`) or in the legacy nested `chaos-engine/` folder, and fails closed otherwise.
- `.github/`, `CONTRIBUTING.md`, `CODE_OF_CONDUCT.md`, `SECURITY.md` and `CHANGELOG.md` stay out of the adopter payload.

### Added

- `tests/test_bootstrap_source_layout.py`: root-tree and nested fixtures, tarball fallback, fail-closed cases, wrapper defaults. CI runs `tests/`.

## [0.4.20261114.6] - 2026-11-14

### Added

- Review budget in `references/delivery-cycle.md`: plan-time MIN and MAX review rounds from task risk. At MAX, only wrong, unsafe or untruthful findings block; the rest are logged follow-ups. The handoff records the budget and the rounds used (ShaftHQ/SHAFT_ENGINE#8063).

## [0.4.20261114.5] - 2026-11-14

### Changed

- Repository extracted from ShaftHQ/SHAFT_ENGINE with history; community files added.
