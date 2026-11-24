# Network and console

Stub at the boundary you own. A test that needs the real third party is an integration test, and it says so.

## Playwright `page.route`

Register the route before the action that fires the request.

- Stub JSON with `route.fulfill({ status, contentType: "application/json", body })`.
- Force `4xx` and `5xx` the same way. Assert the UI state, not only the status.
- `route.abort("timedout")` for a hang. `context.setOffline(true)` for a dead network.
- Assert the outbound payload inside the route (`request.postDataJSON()`), then fulfill.
- `page.waitForResponse` (or `waitForRequest`) is registered before the click. After the click is a race.
- GraphQL: branch on `operationName` in the JSON body. One route can stub several operations. Do not key only on the URL.
- `routeFromHAR` replays a recorded session. Update the HAR when the contract changes. Do not hand-edit one entry and leave the rest stale.
- `serviceWorkers: "block"` on the context so a worker cannot answer around the route.
- WebSockets: `page.routeWebSocket` (or the driver's socket mock). An HTTP route does not see the socket.

## Selenium BiDi `network`

Turn on BiDi (`webSocketUrl: true`). Subscribe, then intercept.

Events: `beforeRequestSent`, `responseStarted`, `responseCompleted`, `authRequired`, `fetchError`. Add the intercept with `addIntercept` before navigation.

Every branch, including exceptions, ends in exactly one terminal action: `continueRequest`, `provideResponse`, `failRequest`, or `continueWithAuth`. A branch that returns without one hangs the navigation. Use `try` / `finally` so the terminal action still runs.

Classic WebDriver still does the click and the navigation. BiDi observes and fulfills. Do not mix a second CDP network listener into the same request.

## Failure bundle

On failure, write one JSON artifact. Do not print the raw console or the raw bodies to stdout.

Include:

- `console.error`
- `pageerror` / BiDi `webError`
- first-party `4xx` and `5xx` (method, URL, status)
- CSP violations and hydration errors

Cap the file at 50 entries. Truncate each body (500 characters is enough to identify the payload). Record the artifact path in the test output. Drop third-party noise unless the test is about that third party.
