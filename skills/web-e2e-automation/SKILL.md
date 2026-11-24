---
name: web-e2e-automation
description: >-
  On-demand router for web end-to-end tests: locators, network faults, Playwright, and Selenium BiDi. Load one reference per turn.
license: MIT
---

# Web E2E automation

Load exactly one L2 reference per turn. Leave the other three unloaded.

| Turn is about | Load |
| --- | --- |
| Shadow DOM, frames, virtual lists, canvas, locator hierarchy, ARIA snapshots | [locators-dom.md](references/locators-dom.md) |
| Route mocking, fault injection, HAR, GraphQL, BiDi intercept completion, console/network failure bundles | [network-console.md](references/network-console.md) |
| Playwright Test fixtures, `storageState`, traces, clock, `playwright-cli` vs MCP, Test Agents healer gate | [playwright.md](references/playwright.md) |
| Selenium 4.54 WebDriver BiDi modules, CDP retirement boundary, browser matrix | [selenium-bidi.md](references/selenium-bidi.md) |

## Deferred

Visual viewport x theme matrix, geometry checks, and red-then-green UI proof stay in [ui-delivery.md](../../references/ui-delivery.md). Do not copy that contract here.

A project with an installed automation pack uses that pack's router. Do not embed pack product tokens in this skill.
