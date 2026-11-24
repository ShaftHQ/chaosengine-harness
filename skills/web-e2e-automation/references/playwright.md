# Playwright

`@playwright/test` is the runner. One concern per fixture. The test file holds the scenario and the assertions.

## Runner

- Fixtures build the isolated `BrowserContext`. Tests do not share a context.
- Auth belongs to a setup project that writes `storageState`. Dependent projects consume that file. A test does not log in through the UI unless the scenario is the login.
- Assertions are web-first and auto-retrying (`expect(locator)...`). A bare `assert` on a one-shot `textContent()` is a race.
- `APIRequestContext` drives HTTP setup and teardown. Do not click through the UI to seed data.
- `trace: "on-first-retry"` in the config. A green run does not need a trace archive.
- Shard with the runner's `--shard`. Projects are browsers, brands, or the setup project, not copies of the same test.
- `toHaveScreenshot`: pin OS and browser, disable animations, and mask dynamic nodes (clocks, ads, user names). A screenshot is support. Geometry and the viewport x theme matrix stay in `references/ui-delivery.md`.
- `page.clock` installs a fake clock. Do not `waitForTimeout` for a minute the product would tick. A sleep needs a reason a clock, a locator, or a response cannot express.

## Agents and CLI

ChaosEngine prefers CLI over MCP. Use `playwright-cli` and the upstream Playwright skill: snapshots are files, `snapshot "#main"` accepts `--depth`, and `find` searches the file. That is zero MCP schema on every turn.

`@playwright/mcp` is only for a host with no shell.

Playwright Test Agents:

| Agent | Role |
| --- | --- |
| `planner` | Proposes scenarios. A human or the test author accepts the list. |
| `generator` | Drafts a test from an accepted scenario. |
| `healer` | Repairs a locator or a wait inside the existing contract. |

A healer that skips, deletes, or weakens a test has changed the contract. That change does not auto-merge. Treat it as a test edit and review it.
