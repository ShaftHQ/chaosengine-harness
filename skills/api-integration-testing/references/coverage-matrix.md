# Coverage matrix

Assert the oracle and the expected status. Do not ship payloads, wordlists, or bypass recipes. One row is enough for a turn.

| Concern | Oracle |
| --- | --- |
| Status codes | Every documented success and error status appears, and no undocumented 2xx or 5xx does. |
| Schema conformance | Response body matches the schema for that status, including required fields and enum values. |
| Content negotiation | A supported `Accept` returns that representation. An unsupported `Accept` expects 406. A mismatched `Content-Type` expects 415. |
| Pagination, sorting, filtering | Page or cursor bounds are stable. Sort order matches the requested key. A filter removes rows that do not match. An out-of-range page expects the documented empty set or 400. |
| Idempotency keys | The same key and same body replay the first result. The same key and a different body expect 409 or the documented conflict. |
| Optimistic locking | A write with the current `ETag` via `If-Match` succeeds. A stale `ETag` expects 409. A missing `If-Match` on a versioned write expects the documented rejection. |
| Rate limits | Traffic inside the documented budget succeeds. Over the budget expects 429 and a `Retry-After` the client honors. |
| Authentication | A missing, expired, or invalid credential expects 401. |
| Authorization | Another caller's object (BOLA), another role's function (BFLA), or a privileged field on an ordinary write (mass assignment) expects 403 or 404, and the stored record does not change. |
| Timeouts and circuit breakers | A dependency past the budget expects the documented timeout status, commonly 504. An open breaker expects the documented fallback, commonly 503. The client must not hang. |
| Bounded async polling | Poll until the documented terminal state or the attempt cap, then fail. Do not poll without a cap. |

Pair this matrix with the protocol file for the contract and with the environment file for where the call runs.
