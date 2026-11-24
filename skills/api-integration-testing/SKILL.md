---
name: api-integration-testing
description: >-
  Use when testing an HTTP, event, or contract API. Delegate installed pack
  client syntax via route() and keep coverage, schema, and review gates here.
license: MIT
---

# API integration testing

On-demand router. Do not paste this body into the always-loaded card. Load ONE reference per turn.

## Pack routing

Call `route(pack_kind, addon_present, denied)` in [route.py](route.py). `denied` defaults to false.

| Result | Meaning |
| --- | --- |
| `pack` | A project automation pack is installed (`core` or `user`, add-on present, not denied). Delegate framework HTTP client and assertion syntax to that pack's router. |
| `blocked` | Kind is `core` or `user` and the add-on is absent. Stop. Do not invent client syntax. |
| `native` | `denied`, kind `none`, or no pack. Use [tooling](references/tooling.md). |

Keep ChaosEngine's coverage matrix, schema conformance, security checks, and review gates here even when the pack owns client syntax.

## One reference

| Question | Load |
| --- | --- |
| REST, OpenAPI 3.1, GraphQL SDL, gRPC/Protobuf, WebSocket, AsyncAPI, Schemathesis 4.x, Pact | [protocols](references/protocols.md) |
| Status, schema, negotiation, paging, idempotency, ETag, 429, 401, BOLA/BFLA, timeouts | [coverage matrix](references/coverage-matrix.md) |
| Testcontainers, WireMock, rollback, nightly k6 | [environments](references/environments.md) |
| pytest/httpx, REST Assured, Playwright, httptest, Specmatic/Microcks | [tooling](references/tooling.md) |
