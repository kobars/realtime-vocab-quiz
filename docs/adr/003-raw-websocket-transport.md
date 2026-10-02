# ADR-003 — Transport: raw WebSocket on FastAPI and uvicorn

[All decisions](../DECISIONS.md)

<!-- AI-ASSISTED-BEGIN: ADR-003 drafted with Claude Code from the reviewed design drafts, checked by hand against docs/spec/. -->

- **Status:** accepted
- **Date:** 2026-10-01

## Context

Players send requests (`join`, `next`, `answer`) and receive a shared leaderboard that changes several times a second while a quiz runs: scores update in real time, and the leaderboard updates promptly. The target is p99 below 500 ms from an accepted answer to the delivered leaderboard, for thousands of connections per node, on two API nodes behind nginx. The server is Python (FastAPI, uvicorn) and the client is a Vue single-page app.

## Decision

One raw WebSocket per tab on FastAPI and uvicorn (`GET /ws`, subprotocol `quiz.v1`), carrying versioned JSON text frames (`docs/spec/protocol.md`). `permessage-deflate` is off: frames are small, and compressing one frame per connection costs CPU on every broadcast. Authentication is a single-use ticket in the query string, checked before the upgrade, because browsers cannot set headers on a WebSocket open.

## Alternatives considered

- **Server-Sent Events plus HTTP POST:** simple and proxy-friendly, but requests and updates travel on two channels, so ordering between an `answer_result` and the next frame is lost, and each answer pays a full HTTP request. Rejected.
- **Socket.IO (python-socketio):** rooms, acknowledgements and reconnects are built in, but it adds its own framing and handshake on top of WebSocket, a client library that must match the server version, and, with the polling fallback, sticky sessions at nginx. Its reconnect does not know our `seq`, so resync would still be ours. Rejected.
- **Polling or long polling:** latency is bounded by the poll interval, and thousands of clients polling cost a request each per interval even when nothing changed. Rejected.

## Consequences

- The service implements its own heartbeat (a server ping and an app-level `ping`/`pong`), reconnect with full-jitter backoff, and resync from `seq`; the protocol spec defines all three.
- nginx needs the upgrade headers and read timeouts longer than the 25 s heartbeat.
- A socket is bound to one node; a node that stops drops its sockets, and clients reconnect to the other node and resync (no drain step).

<!-- AI-ASSISTED-END -->
