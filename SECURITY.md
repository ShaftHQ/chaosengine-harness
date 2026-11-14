# Security

## Reporting

Report a vulnerability in private. Use GitHub **Report a vulnerability** (private vulnerability reporting) on ShaftHQ/chaosengine-harness:

https://github.com/ShaftHQ/chaosengine-harness/security/advisories/new

Do not open a public issue, pull request, or discussion for a vulnerability. Conduct reports go to [CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md), not to this channel.

## Supported versions

The supported version is the latest `main`. The version string is the contents of `VERSION`. As of 2026-11-14 that string is `0.4.20261114.5`. Older builds are not supported.

## Scope

Scope wording is owned by ShaftHQ/SHAFT_ENGINE#8032 (R4). This section is that wording for ShaftHQ/chaosengine-harness.

In scope:

- Prompt injection that crosses a security boundary
- Credential disclosure through logs or traces
- Sandbox or guard bypass
- Installer, hooks, or stores integrity

Out of scope:

- Merely poor model answers
