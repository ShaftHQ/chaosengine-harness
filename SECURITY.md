# Security

## Reporting

Report a vulnerability in private. Use GitHub **Report a vulnerability** (private vulnerability reporting) on ShaftHQ/chaosengine-harness:

https://github.com/ShaftHQ/chaosengine-harness/security/advisories/new

Do not open a public issue, pull request, or discussion for a vulnerability. Code of conduct reports use the same private form with a title that starts "Conduct report:". See [CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md).

## Supported versions

The supported version is the latest `main`. The version string is the contents of `VERSION`. As of 2026-11-14 that string is `0.4.20261114.5`. Older builds are not supported.

## Scope

Scope wording is owned by ShaftHQ/SHAFT_ENGINE#8032 (R4). This section is that wording for ShaftHQ/chaosengine-harness.

In scope:

- Bypassing a ChaosEngine guard (PreToolUse deny, delete-guard, secret or content scan, outbound-send approval)
- Credential disclosure through harness state, logs, spans, or stores
- Installer or update paths that run unpinned code
- Prompt injection that crosses one of those boundaries

Out of scope:

- Model output quality on its own
- Attacks that assume a compromised host, or an attacker who already holds the credential
