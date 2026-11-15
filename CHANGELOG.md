# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [Unreleased]

## [0.4.20261115.2] - 2026-11-15

### Fixed

- `mcp_policy.py` host-config rewrites (GitHub MCP strip in `repair_user_github_mcp`, deja strip in `_strip_deja_file`) now go through the same locked, atomic, parse-checked writer as the Grok lean config (ShaftHQ/SHAFT_ENGINE#8070). This covers `~/.grok/config.toml`, `~/.codex/config.toml`, `~/.claude.json` and the other host MCP files. Files with nothing to strip are not locked or written. The test tripwire now also catches these writes.

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
