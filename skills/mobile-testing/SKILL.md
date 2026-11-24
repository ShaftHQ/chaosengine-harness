---
name: mobile-testing
description: "Use when authoring or running Android or iOS UI tests: probe the host, then apply locator, deep-link, permission, and reset patterns."
license: MIT
---

# Mobile testing

On demand. Load this file only for a mobile UI run.

## 1. Environment

Run `python3 scripts/ci/test_env_doctor.py` before the run. When a required check is `absent` or `unready`, route to the `test-env-setup` skill. Installs and boots go through that skill after the owner says yes.

## 2. Safety cards

Obey these cards. Leave their rules where they are:

- [Mobile client automation](../../references/mobile-client-automation.md)
- [Mobile retro harness](../../references/mobile-retro-harness.md)
- [Appium driver npm recover](../../references/appium-driver-npm-recover.md)

## 3. Patterns

Load [mobile automation patterns](references/mobile-automation-patterns.md) for locator order, page-source limits, deep links, permissions, and state reset.

When the project uses an installed automation pack, defer driver and locator syntax to that pack's router.
