# Architecture decision records

Each decision uses the format below. ADRs are never renumbered; a later ADR supersedes an earlier one.

```markdown
## ADR-NNN — <decision>

- **Status:** proposed | accepted | superseded by ADR-NNN
- **Date:** YYYY-MM-DD

### Context
### Decision
### Alternatives considered
### Consequences
```

## Index

| ADR | Topic | Status |
|---|---|---|
| ADR-001 | The component we build (the real-time quiz service: server and client) and the mocks (identity and tickets, question bank, quiz admin) | proposed |
| ADR-002 | Quiz model: self-paced; the integer scoring rule | accepted |
| ADR-003 | Transport: raw WebSocket on FastAPI and uvicorn | accepted |
| ADR-004 | Wire protocol, standings policy and the 200 ms coalescing tick | accepted |
| ADR-005 | Redis sorted set and Lua scripts for scoring; AOF `everysec` | proposed |
| ADR-006 | No owner per quiz: the `dirty` gate and a tick token | proposed |
| ADR-007 | Backplane: Redis pub/sub, `seq` and resync (Streams as the next step) | proposed |
| ADR-008 | One Redis schema for scoring and fan-out | proposed |
| ADR-009 | Repository layout: `api/`, `web/`, generated `contracts/` | proposed |

## ADR-002 — Self-paced quiz model and the integer scoring rule

- **Status:** accepted
- **Date:** 2026-10-01

### Context

The challenge asks for a real-time vocabulary quiz: users join with a quiz ID, scores update in real time, and a leaderboard shows everyone's standings; the scoring must be accurate and consistent (AC-4). It does not say who decides when a question opens and closes. The service runs on two API nodes behind nginx with one Redis, so any rule that needs one node to act at a given moment needs coordination between nodes. The speed bonus depends on elapsed time, and the obvious floating-point formula rounds wrongly for some inputs (for `T = 20,000` it gives 132 instead of 133 at 6,800 ms).

### Decision

The quiz is **self-paced**: real-time means live scores and one shared live board; each player sets their own pace. Each player asks for the next question, the server serves it to that player only and records the serve time on Redis `TIME`, and scores the answer when it arrives. A quiz is open for a window that starts at creation (default 10 min, at most 60 min) or until a mock host ends it. Every write checks the deadline in the same Redis script; no timer decides lateness or the end. A correct, on-time answer scores `100 + (50 * (T - e)) // T` in integer milliseconds; wrong or late scores 0. The full rules are in `docs/spec/domain.md`.

### Alternatives considered

- **Host-led quiz:** one host opens each question for everyone at once, and it closes for everyone at once. It matches a classroom, but needs one owner per quiz on one node (a lease with a fencing token) to open and close questions on time, and a failover story when that node dies. Self-paced needs no owner: any node scores any answer atomically in Redis. Host-led stays future work.
- **Per-player question order:** stops answer sharing, but makes totals harder to compare and to test. Deferred; a per-player choice order is the cheaper fix (see Consequences).
- **Client-measured time:** simple, but a client can lie about its answer time. Rejected: the server decides time.
- **Floating-point bonus `50 * (1 - e / T)`:** wrong for 7 of the 20,001 on-time inputs at `T = 20,000`, in Python, Lua and JavaScript alike. Rejected for the exact integer form.

### Consequences

- No per-player or per-question timers on the server; lateness and the deadline are decided when a request arrives, so a node restart loses no timing state.
- Players finish at different times, so a finished player's rank is provisional until `quiz_ended`.
- The correct choice is revealed only in the answering player's own result. With one question order, players can still share answers with players behind them; a per-player choice order is the future fix.
- The window is capped at 60 min because the sorted-set score packs the reach time into 22 bits (about 69.9 min).
- The scoring formula exists in one integer form; a parity test checks the Lua script against Python for every elapsed value from 0 to `T + 1`.

## ADR-003 — Transport: raw WebSocket on FastAPI and uvicorn

- **Status:** accepted
- **Date:** 2026-10-01

### Context

Players send requests (`join`, `next`, `answer`) and receive a shared leaderboard that changes several times a second while a quiz runs (AC-3, AC-6). The target is p99 below 500 ms from an accepted answer to the delivered leaderboard, for thousands of connections per node, on two API nodes behind nginx. The server is Python (FastAPI, uvicorn) and the client is a Vue single-page app.

### Decision

One raw WebSocket per tab on FastAPI and uvicorn (`GET /ws`, subprotocol `quiz.v1`), carrying versioned JSON text frames (`docs/spec/protocol.md`). `permessage-deflate` is off: frames are small, and compressing one frame per connection costs CPU on every broadcast. Authentication is a single-use ticket in the query string, checked before the upgrade, because browsers cannot set headers on a WebSocket open.

### Alternatives considered

- **Server-Sent Events plus HTTP POST:** simple and proxy-friendly, but requests and updates travel on two channels, so ordering between an `answer_result` and the next frame is lost, and each answer pays a full HTTP request. Rejected.
- **Socket.IO (python-socketio):** rooms, acknowledgements and reconnects are built in, but it adds its own framing and handshake on top of WebSocket, a client library that must match the server version, and, with the polling fallback, sticky sessions at nginx. Its reconnect does not know our `seq`, so resync would still be ours. Rejected.
- **Polling or long polling:** latency is bounded by the poll interval, and thousands of clients polling cost a request each per interval even when nothing changed. Rejected.

### Consequences

- The service implements its own heartbeat (a server ping and an app-level `ping`/`pong`), reconnect with full-jitter backoff, and resync from `seq`; the protocol spec defines all three.
- nginx needs the upgrade headers and read timeouts longer than the 25 s heartbeat.
- A socket is bound to one node; a node that stops drops its sockets, and clients reconnect to the other node and resync (no drain step).

## ADR-004 — Wire protocol, standings policy and the 200 ms coalescing tick

- **Status:** accepted
- **Date:** 2026-10-01

### Context

With a self-paced quiz (ADR-002), questions and results are per player, but the leaderboard is shared. If every answer, join or leave sent the leaderboard to everyone, cost would grow with the square of the players: 5,000 joins alone would mean about 12.5 million sends. Clients on several nodes must still converge on the same standings (C4), and a lost or dropped frame must be detectable.

### Decision

- **Protocol:** JSON messages `{"v": 1, "type": …}` with strict validation. Broadcasts (`leaderboard`, `quiz_ended`) carry a per-quiz `seq` that grows by exactly 1; unicasts carry `atSeq`; `pong` carries the latest `seq`. A client that sees a gap, a lost last frame or a lower `seq` sends `resync` and gets a full `snapshot`. `next` and `answer` carry the question index, and `answer` a client `submissionId`, so every request is safe to repeat.
- **Standings policy:** each frame carries every player up to 200 players, else the top 50; players outside the top 50 get their own `rank_update` (after the next tick when they scored, at most once per second otherwise). The full list is paged with `get_leaderboard` (1–200 rows). Frames always hold full standings, never a diff.
- **Coalescing tick:** joins, leaves and scoring answers only set a `dirty` flag. While it is set, one node per 200 ms (the holder of the tick token) clears it, increments `seq` and publishes one frame. A slow socket keeps only the newest frame, which then carries `rebase: true`.

### Alternatives considered

- **A broadcast per event:** lowest latency at small scale, but quadratic cost under load. Rejected.
- **Diff frames:** smaller, but a dropped or conflated diff breaks the client's state; full frames are self-healing and stay small with the 200-player cap. Rejected for v1.
- **A 50 ms tick:** four times the frames for little gain against a 500 ms budget. **A 1 s tick:** uses most of the budget by itself. 200 ms keeps the worst case at one tick plus delivery.
- **Binary encoding (MessagePack, Protocol Buffers):** smaller frames, but harder to read in logs and browser tools; JSON frames of at most 200 rows are small enough. Rejected for v1.

### Consequences

- Fan-out cost per tick is one frame per connection, whatever the number of events in that tick.
- A score shows on other screens up to 200 ms late, by design; the load runs measure the answer → leaderboard latency against C5.
- Clients must buffer broadcasts while a `resync` is pending and handle `rebase`; the bots and the Vue client share these rules from the protocol spec.
