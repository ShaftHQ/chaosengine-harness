# Mobile automation patterns

Load after the environment doctor is green for the profile you need. When an installed automation pack owns the project, use that pack's driver and locator syntax. The order below still applies.

## Locator order

1. Accessibility id first. Android `content-desc`. iOS `accessibilityIdentifier`. This is the stable handle.
2. Android `resource-id` or a scoped `UiSelector`.
3. iOS `NSPredicate` or Class Chain when the accessibility id does not expose the property.
4. Scoped relative XPath is strictly the last resort. Anchor it to a parent you already found. A document-wide XPath is a flake.

Name the control in the failure. A raw query copied from a dump is not a locator.

## Page source

Keep full raw XML hierarchies out of LLM context and out of logs you will re-read.

- UiAutomator2: set `appium:ignoreUnimportantViews` so the tree drops layout noise.
- XCUITest: set `snapshotMaxDepth` to the depth of the screen under test.
- Keep the node you assert: role, accessibility id, and text. Drop the rest.

## Deep links

Open the screen you mean to test, then assert a fact that can fail (title, unique control, or resolved URL).

```bash
adb shell am start -a android.intent.action.VIEW -d <uri>
xcrun simctl openurl booted <url>
```

A deep link that only launches is not a test. The assertion is the test.

## Permissions and reset

`appium:autoGrantPermissions` grants ordinary Android runtime permissions. It does not grant role-special ones (notification listener, device admin, default SMS). Grant those with an explicit owner-approved command on a suite-owned emulator.

`appium:autoAcceptAlerts` accepts iOS system alerts. When the alert itself is the subject, leave it for the test to accept or reject.

`noReset` keeps app data and is fast. `fullReset` reinstalls and is slow. Pick one per suite and name it. `adb shell pm clear <pkg>` only on an emulator the suite owns. Leave personal devices and shared farm devices you do not own alone.

## Security

Route mobile security checks through the `security-audit` skill: OWASP MASVS v2.1.0 and MASTG. This note names the standard. It does not turn those controls into attack steps.
