# Selenium WebDriver BiDi

Spec pin: W3C WebDriver BiDi, WD 2026-11-13. Binding: Selenium 4.54.

## Session

Enable BiDi when the session starts.

- Capability `webSocketUrl: true`.
- Python `enable_bidi`. Java and the other bindings `enableBiDi()`.

Clicks and navigation stay on classic WebDriver. BiDi is the event and intercept channel. Do not reimplement click on top of a BiDi script.

## Modules

| Module | Use |
| --- | --- |
| `browsingContext` | Context lifecycle, navigation events, capture when a screenshot is actually required |
| `network` | Intercept and the terminal continue / fulfill / fail / auth actions. See [network-console.md](network-console.md) |
| `log` | Console and runtime entries for the failure bundle |
| `script` | Evaluate inside a realm when no classic command can observe it |
| `storage` | Cookie and storage setup the classic API cannot express |
| `emulation` | Geolocation, timezone, viewport, and locale overrides |

Subscribe only to the events the test reads. An idle subscription still buffers.

## CDP retirement

Do not add a Chrome DevTools Protocol call. If a BiDi command does not exist yet, the legacy CDP call stays and carries a comment of the form `missing BiDi command: <name>`. When that command lands, delete the CDP call. A new test that starts on CDP is past the retirement boundary.

## Browser matrix

| Browser | BiDi | Fallback |
| --- | --- | --- |
| Chrome | First class | None |
| Edge | First class | None |
| Firefox | First class | None |
| Safari | Experimental gap | Classic WebDriver for the journey, or Playwright WebKit when the scenario needs a WebKit engine |

Do not mark Safari green on a BiDi-only intercept. Either the intercept has a classic equivalent, or the suite records the Safari gap and runs that scenario on a first-class browser.
