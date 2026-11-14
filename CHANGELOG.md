# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [Unreleased]

## [0.4.20261115.1] - 2026-11-15

### Fixed

- Grok user config (`~/.grok/config.toml`) edits are now safe (ShaftHQ/SHAFT_ENGINE#8070). Every write takes a lock, writes a temp file in the same folder, fsyncs and renames it into place. It is refused if the result is not valid TOML or another writer keeps changing the file. An interrupted or concurrent write can no longer leave a torn file.
- Removing a ChaosEngine marker span now drops only the lines ChaosEngine owns. Tables another tool wrote between the markers (for example the Grok CLI's `[marketplace]` and `[[marketplace.sources]]`) are kept. Install then uninstall returns the user's file byte for byte, and repeated installs no longer add blank lines.

### Added

- `tests/conftest.py` points `GROK_HOME` at a throwaway folder for the whole run. A tripwire refuses and logs any write under the real Grok home, and the session fails if it fired.
- `tests/scripts/test_grok_config_safety_8070.py`: torn writes, parallel writers, a foreign writer mid-edit, invalid TOML, and preserving unrelated sections.

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
