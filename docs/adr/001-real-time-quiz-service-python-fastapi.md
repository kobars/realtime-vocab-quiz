# ADR-001 — Build the real-time quiz service, with a Python and FastAPI server; mock identity, questions and admin

[All decisions](../DECISIONS.md)

<!-- AI-ASSISTED-BEGIN: ADR-001 drafted with Claude Code from the requirements and api/pyproject.toml, checked by hand against the ports in api/src/quiz/ports/ and the mock adapters. -->

- **Status:** accepted
- **Date:** 2026-10-01

## Context

The product needs one real-time quiz service built for real; identity, questions and admin sit behind ports and are mocked. A real-time quiz needs a client, a server that holds the sockets and scores answers, a store, an identity provider, a source of questions and some way to create and end quizzes. The part that carries the hard requirements is the path from an answer to a leaderboard on every screen: atomic scoring (AC-4), many joins at once (AC-2) and prompt updates across nodes (AC-6). The server must hold thousands of mostly idle sockets per node, validate every inbound frame strictly, and share its message definitions with a TypeScript client.

## Decision

- **Built for real:** the real-time quiz service end to end: the Vue client, the WebSocket gateway, the use cases, the Redis scoring scripts, the coalescing tick and the pub/sub fan-out across two API nodes behind nginx.
- **Mocked, behind ports:** identity and tickets (`TicketStore`: anonymous sessions and single-use tickets kept in Redis) and the question bank (`QuestionBank`: seed quizzes from JSON files). Quiz admin is a token-gated mock admin API (`POST /admin/quizzes`, only with `ADMIN_MOCK=1`) and one host action ("end now"). Each mock module says `MOCK:` in its docstring.
- **Server stack:** Python 3.14 with FastAPI on uvicorn, Pydantic v2 for the wire models and settings, redis-py with hiredis, managed with uv. The wire messages are defined once, as Pydantic models in `api/src/quiz/contracts/`; the JSON Schema and the client's TypeScript types are generated from them (ADR-009).

## Alternatives considered

- **Build the leaderboard only, over a mocked scoring feed:** smaller, but it skips the part where consistency is won or lost (two nodes scoring the same player at once), and the AC-4 claims could not be tested. Rejected.
- **Build a real identity flow (OIDC):** large effort on a part every company already has; the single-use ticket before the upgrade is the only piece the real-time path needs, and it is built for real. Rejected.
- **Node.js (Fastify with `ws`):** one language with the client and a mature WebSocket library, but message validation and schema generation need a second tool (zod or TypeBox) and the property tests a second framework. Python gives Pydantic for both validation and schema generation, and Hypothesis. Rejected by a small margin.
- **Go:** more sockets per core and real parallelism in one process, but no shared models with the client without a code generator, and more code for strict JSON validation. Its strength, raw socket density, matters less here than correctness of the scoring path, which lives in Redis scripts whatever the server language. Rejected for this build.

## Consequences

- The mocks sit behind ports, so a real identity provider or content service replaces one adapter without touching the domain or the use cases; import-linter enforces the layers in `make check`.
- A Python process runs one event loop on one core: JSON encoding and send work per frame cost CPU, so a node holds fewer sockets than a Go server would. The design scales by adding processes behind nginx, and the coalescing tick bounds sends per connection (ADR-004); the load runs measure the limit (DESIGN §9).
- One source of truth for the protocol: a contract change regenerates the schema and the client types, and `make check` fails on drift.

<!-- AI-ASSISTED-END -->
