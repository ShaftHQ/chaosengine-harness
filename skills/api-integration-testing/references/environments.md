# Environments

Run integration checks against an isolated local dependency. Do not point a suite at a shared production host.

## Ephemeral containers

Start dependencies with Testcontainers and destroy them at the end of the test. Use one container for each of database, Redis, Kafka, and LocalStack when the code under test needs that service. Wire the app to the container's published address. A failed start fails the test. Do not fall back to a developer machine's long-lived broker.

## WireMock

Stub outbound HTTP in-process with WireMock. Faults and delays are stub mappings: a timeout, a 500, and a slow response inside the test process. Assert the client timeout, retry, and breaker against those stubs. Do not depend on a shared remote mock unless the owner names one.

## Rollback versus isolated state

Prefer a fresh container when tests mutate data. When the suite shares one database, roll the transaction back or truncate the tables the test wrote. A later test that sees a previous row is a failure. Do not use a production snapshot that contains personal data.

## Nightly k6 latency smoke

A nightly k6 smoke checks latency, not capacity. Compare the sample with the project's latency budget. A missing budget means record the sample and do not invent a threshold. Keep the run short and off the request path of any deployed environment the owner has not named.
