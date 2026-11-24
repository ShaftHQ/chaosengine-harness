# Tooling

Pick the client the production code already uses. The coverage matrix and the schema checks stay in this skill. `route()` returns `pack` when an installed project pack owns the client syntax; use that pack's router for the calls below and do not restate them.

| Stack | Client |
| --- | --- |
| Python | `pytest` + `httpx` + `schemathesis` |
| Java | REST Assured + JUnit 5 + Testcontainers, or the installed project-pack client |
| JavaScript or TypeScript | Playwright `APIRequestContext`, Supertest, or Vitest |
| Go | `httptest` for the in-process handler |
| Event brokers | Specmatic or Microcks against the AsyncAPI document |

Rules:

- One stack per suite. Do not wrap a second HTTP client around the one the pack already configures.
- Schema checks use the OpenAPI, SDL, protobuf, or AsyncAPI file. Schemathesis 4.x covers OpenAPI 3.1 when a Draft-7 validator is not enough.
- Pact files are pinned next to the suite and verified in CI.
- Secrets and tokens come from the test environment, never from the skill text.
