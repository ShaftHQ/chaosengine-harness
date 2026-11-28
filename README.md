<p align="center">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="assets/brand/lockup-dark.svg">
    <source media="(prefers-color-scheme: light)" srcset="assets/brand/lockup-light.svg">
    <img alt="ChaosEngine" src="assets/brand/lockup-light.svg" width="720">
  </picture>
</p>

# ChaosEngine

A portable, provider-neutral working contract so coding agents research, plan, implement, verify, review, and learn the same way.

[![CI](https://github.com/ShaftHQ/chaosengine-harness/actions/workflows/ci.yml/badge.svg)](https://github.com/ShaftHQ/chaosengine-harness/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)

Supported hosts: Claude Code, Codex, Gemini CLI, Grok, GitHub Copilot, OpenCode, Cursor, Antigravity, and Grok Bot.

## Documentation

| Guide | Where |
| --- | --- |
| Get started | [Docs home](docs/README.md) |
| Settings reference | [Settings](docs/reference/settings.md) |
| Keywords glossary | [Keywords](docs/reference/keywords.md) |
| For AI agents | [AGENTS.md](AGENTS.md), [llms.txt](llms.txt), [agent reference](docs/agents/reference.md) |

ChaosEngine sends no usage data.

## Quick start

macOS or Linux:

```bash
curl -fsSL "https://raw.githubusercontent.com/ShaftHQ/chaosengine-harness/main/install.sh" | bash -s -- "https://raw.githubusercontent.com/ShaftHQ/chaosengine-harness/main/install.sh"
```

Windows PowerShell:

```powershell
irm "https://raw.githubusercontent.com/ShaftHQ/chaosengine-harness/main/install.ps1" | iex
```

## Pin, verify, uninstall

`--version <40-hex>` pins a commit. A release pin is refused when its `.sha256` does not match. `verify` names drift. `uninstall` keeps edited files. See [INSTALL.md](INSTALL.md).

Optional companion: ICM Architect. Opt out with `--without-icm-architect`.

## Contributing and license

See [CONTRIBUTING.md](CONTRIBUTING.md), [CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md), [SECURITY.md](SECURITY.md), and [LICENSE](LICENSE). MIT licensed.
