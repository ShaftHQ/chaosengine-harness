# Protocols and contracts

Load this file when the question is the contract shape. One protocol per task. Oracles are status codes, schema validity, and the documented error body. Do not add an exploit catalog beside the contract.

## REST and OpenAPI 3.1

The OpenAPI 3.1 document is the contract. 3.1 uses JSON Schema 2020-12, not Draft-7. Validate requests and responses against it: required fields, types, formats, and `additionalProperties`. A documented error status passes when the body matches its schema. An undocumented status fails.

## GraphQL SDL

The SDL is the contract. Cover one allowed query, one mutation, and one field the caller must not read. A forbidden field expects a GraphQL error or an auth failure. An allowed field expects a schema-valid `data` payload. Assert the `errors` array. HTTP 200 alone is not a pass.

## gRPC and Protobuf

The `.proto` service is the contract. Assert the status (`OK`, `UNAUTHENTICATED`, `PERMISSION_DENIED`, `INVALID_ARGUMENT`, `NOT_FOUND`, `DEADLINE_EXCEEDED`) and that the response decodes as the declared message. Set a deadline on every call.

## WebSocket

Cover the handshake, one accepted message, one rejected message, and a close. Expect the documented close code. Assert the message against its schema. A failed handshake expects the documented HTTP status: 401 or 403 when authentication is required.

## AsyncAPI and event queues

The AsyncAPI document names channels and message schemas. Publish and consume the documented message. Assert the payload schema and the channel or routing key. A competing consumer must not apply the same message twice. A schema-invalid message expects the documented dead-letter or rejection path. A silent drop fails unless the contract says drop.

## Schemathesis 4.x

Generate cases from the OpenAPI document with Schemathesis 4.x, including 3.1. Prefer it when another checker only understands JSON Schema Draft-7. Run it from pytest and keep the built-in conformance checks for status, schema, and content type. Negative cases come from the schema.

## Pact

Consumer-driven: the consumer publishes the pact and the provider verifies it. Bidirectional: compare the consumer pact with the provider OpenAPI or schema, and fail when the provider does not implement a request or the consumer does not allow a response. Pin the pact in the suite. A missing interaction is a failure, not a skip.
