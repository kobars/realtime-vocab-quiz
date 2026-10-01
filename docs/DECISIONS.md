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
| ADR-001 | The component we build (the real-time quiz service: a Python and FastAPI server and its client) and the mocks (identity and tickets, question bank, quiz admin) | accepted |
| ADR-002 | Quiz model: self-paced; the integer scoring rule | accepted |
| ADR-003 | Transport: raw WebSocket on FastAPI and uvicorn | accepted |
| ADR-004 | Wire protocol, standings policy and the 200 ms coalescing tick | accepted |
| ADR-005 | Redis sorted set and Lua scripts for scoring; AOF `everysec` | accepted |
| ADR-006 | No owner per quiz: the `dirty` gate and a tick token | accepted |
| ADR-007 | Backplane: Redis pub/sub, `seq` and resync (Streams as the next step) | accepted |
| ADR-008 | One Redis schema for scoring and fan-out | accepted |
| ADR-009 | Repository layout and the Vue client: `api/`, `web/`, generated `contracts/` | accepted |

## ADR-001 — Build the real-time quiz service, with a Python and FastAPI server; mock identity, questions and admin

<!-- AI-ASSISTED-BEGIN: ADR-001 drafted with Claude Code from the requirements and api/pyproject.toml, checked by hand against the ports in api/src/quiz/ports/ and the mock adapters. -->

- **Status:** accepted
- **Date:** 2026-10-01

### Context

The product needs one real-time quiz service built for real; identity, questions and admin sit behind ports and are mocked. A real-time quiz needs a client, a server that holds the sockets and scores answers, a store, an identity provider, a source of questions and some way to create and end quizzes. The part that carries the hard requirements is the path from an answer to a leaderboard on every screen: atomic scoring (AC-4), many joins at once (AC-2) and prompt updates across nodes (AC-6). The server must hold thousands of mostly idle sockets per node, validate every inbound frame strictly, and share its message definitions with a TypeScript client.

### Decision

- **Built for real:** the real-time quiz service end to end: the Vue client, the WebSocket gateway, the use cases, the Redis scoring scripts, the coalescing tick and the pub/sub fan-out across two API nodes behind nginx.
- **Mocked, behind ports:** identity and tickets (`TicketStore`: anonymous sessions and single-use tickets kept in Redis) and the question bank (`QuestionBank`: seed quizzes from JSON files). Quiz admin is a set of make targets and one host action ("end now"). Each mock module says `MOCK:` in its docstring.
- **Server stack:** Python 3.14 with FastAPI on uvicorn, Pydantic v2 for the wire models and settings, redis-py with hiredis, managed with uv. The wire messages are defined once, as Pydantic models in `api/src/quiz/contracts/`; the JSON Schema and the client's TypeScript types are generated from them (ADR-009).

### Alternatives considered

- **Build the leaderboard only, over a mocked scoring feed:** smaller, but it skips the part where consistency is won or lost (two nodes scoring the same player at once), and the AC-4 claims could not be tested. Rejected.
- **Build a real identity flow (OIDC):** large effort on a part every company already has; the single-use ticket before the upgrade is the only piece the real-time path needs, and it is built for real. Rejected.
- **Node.js (Fastify with `ws`):** one language with the client and a mature WebSocket library, but message validation and schema generation need a second tool (zod or TypeBox) and the property tests a second framework. Python gives Pydantic for both validation and schema generation, and Hypothesis. Rejected by a small margin.
- **Go:** more sockets per core and real parallelism in one process, but no shared models with the client without a code generator, and more code for strict JSON validation. Its strength, raw socket density, matters less here than correctness of the scoring path, which lives in Redis scripts whatever the server language. Rejected for this build.

### Consequences

- The mocks sit behind ports, so a real identity provider or content service replaces one adapter without touching the domain or the use cases; import-linter enforces the layers in `make check`.
- A Python process runs one event loop on one core: JSON encoding and send work per frame cost CPU, so a node holds fewer sockets than a Go server would. The design scales by adding processes behind nginx, and the coalescing tick bounds sends per connection (ADR-004); the load runs measure the limit (DESIGN §9).
- One source of truth for the protocol: a contract change regenerates the schema and the client types, and `make check` fails on drift.

<!-- AI-ASSISTED-END -->

## ADR-002 — Self-paced quiz model and the integer scoring rule

- **Status:** accepted
- **Date:** 2026-10-01

### Context

The product is a real-time vocabulary quiz: users join with a quiz ID, scores update in real time, and a leaderboard shows everyone's standings; the scoring must be accurate and consistent (AC-4). Nothing says who decides when a question opens and closes. The service runs on two API nodes behind nginx with one Redis, so any rule that needs one node to act at a given moment needs coordination between nodes. The speed bonus depends on elapsed time, and the obvious floating-point formula rounds wrongly for some inputs (for `T = 20,000` it gives 132 instead of 133 at 6,800 ms).

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
- **A 50 ms tick:** four times the frames for little gain against a 500 ms budget. **A 1 s tick:** exceeds the 500 ms budget by itself, since a score could wait a full second before its frame leaves Redis. 200 ms keeps the worst case at one tick plus delivery.
- **Binary encoding (MessagePack, Protocol Buffers):** smaller frames, but harder to read in logs and browser tools; JSON frames of at most 200 rows are small enough. Rejected for v1.

### Consequences

- Fan-out cost per tick is bounded per connection, whatever the number of events in that tick: one `leaderboard` frame and, above 200 players, at most one `rank_update` for a player outside the top 50 (after a tick in which they scored, else at most once per second when their rank shifted). That is at most two messages per connection per tick, 10 per second.
- A score shows on other screens up to 200 ms late, by design; the load runs measure the answer → leaderboard latency against C5.
- Clients must buffer broadcasts while a `resync` is pending and handle `rebase`; the bots and the Vue client share these rules from the protocol spec.
- `pong.seq` is read from Redis for every `ping` (one `GET`; about 400 per second for 10,000 sockets on a node), so a node that relayed nothing yet, or missed a frame on its pub/sub link, still reports the quiz's counter.

## ADR-005 — Redis sorted set and Lua scripts for scoring; AOF `everysec`

- **Status:** accepted
- **Date:** 2026-10-01

### Context

Any of two or more API nodes can receive any player's request. Scoring an answer reads the player's progress and the serve time, checks two idempotency layers and the deadline, and writes the answer, the total and the standing; a join and a serve are multi-step too. If two nodes interleave these steps, a (player, question) can score twice or a total can disagree with the leaderboard (C1, C3). The leaderboard must be read in rank order many times a second.

### Decision

Redis 8 (Valkey 8 also works) holds all quiz state. The standings are one sorted set per quiz with the composite score `(2^30 − total) × 2^22 + reachedRelMs`, read with `ZRANGE` ascending. Every multi-step write is one Lua script (`create_quiz`, `join`, `serve_question`, `score_answer`, `publish_leaderboard`, `leave`, `end_quiz`), and every time inside a script comes from Redis `TIME`. The points formula lives once in `lua/lib/points.lua`, put in front of the scoring script by the loader. Persistence is AOF with `appendfsync everysec`. The contracts are in `docs/spec/redis.md`.

### Alternatives considered

- **`WATCH`/`MULTI` optimistic transactions:** no Lua, but every conflict means a retry round trip, and a hot quiz conflicts on every answer. Rejected.
- **Redis Functions:** a cleaner way to ship shared code than a loader, but they need `FUNCTION LOAD` on deploy and differ in detail between Redis and Valkey. Plain scripts with a loader are enough for seven scripts.
- **PostgreSQL with row locks:** durable and familiar, but a leaderboard query per tick and a lock per answer cost far more than a sorted set. Rejected for v1.
- **State in each node's memory:** fastest, but two nodes would hold two truths. Rejected.
- **AOF `always`:** no loss on a crash, but an fsync per write. **No persistence:** a restart loses every quiz. `everysec` is the middle.

### Consequences

- C1, C3 and C6 hold by construction: every check and its write happen in one atomic script on one clock.
- A crash of Redis can lose about 1 s of writes; DESIGN §11 states it, and clients recover through `seq` and resync.
- Scripts block Redis while they run, so each one stays O(log N) per write, except the tick. The tick reads at most 200 rows, and above 200 players it also runs one `ZRANK` for each scorer since the last frame and one `HGET` for each of those outside the top 50, so its cost is O(S log N) for S scorers among N players and grows with a scoring burst. The load runs should measure the tick script under a synchronized scoring burst.
- The quiz window is capped at 60 min so that `reachedRelMs` fits in 22 bits.

## ADR-006 — No owner per quiz: the `dirty` gate and a tick token

- **Status:** accepted
- **Date:** 2026-10-01

### Context

The leaderboard is coalesced into at most one frame per 200 ms (ADR-004), and players of one quiz are spread over several nodes. Something must decide, every 200 ms, whether a frame goes out and who sends it, without two nodes sending the same frame and without a gap in `seq`.

### Decision

No node owns a quiz. Every node that holds sockets of a quiz calls `publish_leaderboard` about every 200 ms. Inside the script the gate is atomic: if the tick token exists the call returns `busy` with its remaining TTL; if `DEL dirty` returns 0 it returns `clean`; otherwise it sets the token with `SET NX PX 200`, increments `seq` and publishes one frame. A node that got `busy` sleeps until the token expires. Ending a quiz is decided by the deadline check in each write script, and the idempotent `end_quiz` announces it.

### Alternatives considered

- **An owner lease per quiz** (one node holds a renewed lease with a fencing token and runs the tick and the timers): needed for a host-led quiz, where questions must open and close for everyone at a set moment. For a self-paced quiz it adds lease renewal, fencing and a failover delay of up to one lease period, and buys nothing, because no rule depends on a timer.
- **A single tick node:** simple, but a single point of failure that needs its own failover. Rejected.
- **Consistent hashing of quizzes to nodes:** still needs a membership protocol and a handover when a node leaves. Rejected.

### Consequences

- A node can die at any point without a failover step: the script ran entirely or not at all, and another node publishes within about one tick.
- At most one frame per quiz per 200 ms, whatever the number of nodes; the worst-case delay of a score is one token lifetime plus delivery.
- Each node calls the script about 5 times per second per active quiz, even when nothing changed.
- A host-led mode would need an owner lease (ADR-002); this ADR would be superseded for that mode.

## ADR-007 — Backplane: Redis pub/sub, `seq` and resync (Streams as the next step)

- **Status:** accepted
- **Date:** 2026-10-01

### Context

A frame published by one node must reach the clients on every node. Nodes and their Redis connections can drop and come back; a client must be able to tell that it missed a frame and recover without a full reload.

### Decision

The script that publishes a broadcast also increments the quiz's `seq` and publishes the frame on `quiz:{<quizId>}:events` in the same step. Every node subscribes to the channels of the quizzes it serves and relays each frame to its sockets. Delivery is at most once: a client that sees a gap, a lost last frame (`pong.seq`) or a lower `seq` sends `resync` and gets a full `snapshot`; a node that resubscribes sends each of its clients a snapshot.

A second channel per quiz, `quiz:{<quizId>}:control`, carries `session_replaced` from the `join` script to whichever node holds the replaced socket, which closes it with 4001. It has no `seq` and is never relayed to clients. Because pub/sub may drop it, the serve and scoring scripts also check the caller's connection ID against the player's current one and refuse a replaced connection with `SESSION_REPLACED`.

### Alternatives considered

- **Redis Streams** (`XADD` with a cap, read with `XREAD` from the last ID): a node could replay what it missed instead of snapshotting, and the history would survive a node restart. It costs a reader loop per node, trimming, and replay logic on top of resync, which is needed anyway. It is the next step if snapshots after resubscribes become frequent.
- **A message broker (NATS, Kafka):** another service to run and monitor, for one channel per quiz. Rejected for v1.
- **Node-to-node messages:** every node needs the list of the others. Rejected.

### Consequences

- Frames reach each node in `seq` order, because Redis serves one subscription connection in publish order.
- A lost frame costs one snapshot per affected client, never a wrong board: frames are full standings (ADR-004).
- After a Redis data loss `seq` can go back; clients treat a lower `seq` as a restart and resync.
- Each node subscribes to two channels per quiz it serves. Session replacement works across nodes without node-to-node messages, and stays correct when a control message is lost.

## ADR-008 — One Redis schema for scoring and fan-out

- **Status:** accepted
- **Date:** 2026-10-01

### Context

Scoring, the standings, presence, the tick and the broadcast channel all belong to one quiz, and the tick script must read the standings and write `seq` and the channel in one atomic step. The service must be able to grow past one Redis later.

### Decision

One schema in one Redis: every key of a quiz is `quiz:{<quizId>}:<name>`, with the quiz ID as the hash tag, so a quiz lives in one Cluster slot and each script may touch all of its keys. Each script receives all keys of the quiz in one fixed order. The data keys share one TTL (24 h), refreshed by every write script; the tick token keeps its own 200 ms expiry. Lists inside hash fields are JSON arrays. The key table is `docs/spec/redis.md` §2.

### Alternatives considered

- **A separate Redis for pub/sub:** isolates fan-out load, but the tick could no longer increment `seq` and publish atomically. Rejected for v1.
- **Key names without a hash tag:** fine on one Redis, but multi-key scripts fail on a Cluster. Rejected.
- **A database for final results:** results outlive the TTL, but no current feature needs that. Out of scope.

### Consequences

- Scaling out means a Redis Cluster that spreads quizzes over shards; one quiz never spans shards, so the largest quiz is bounded by one shard. On a Cluster, sharded pub/sub (`SPUBLISH`) keeps the channel on the quiz's shard.
- A quiz expires as a whole 24 h after its last write.

## ADR-009 — Repository layout and the Vue client: `api/`, `web/`, generated `contracts/`

<!-- AI-ASSISTED-BEGIN: ADR-009 drafted with Claude Code from the repository layout, api/pyproject.toml and web/package.json, checked by hand against the code. -->

- **Status:** accepted
- **Date:** 2026-10-01

### Context

The service has a Python server and a browser client that must agree on every message. Both are reviewed and tested in one repository with one gate (`make check`), and the client is a small single-page app: a join screen, a question screen with feedback, a finished screen and the live leaderboard, with no server rendering and no search-engine needs.

### Decision

- **Layout:** one repository with `api/` (the Python package `quiz`, managed by uv), `web/` (the client, managed by pnpm) and `contracts/` (the generated JSON Schema). The Pydantic models in `api/src/quiz/contracts/` are the only hand-written definition of the protocol; `make contracts` writes `contracts/schema/protocol.json` and `web/src/protocol/types.generated.ts`, and `make check` fails when a generated file differs from git.
- **Client stack:** Vue 3 with Vite and TypeScript, Pinia for the quiz state, Vue Router for the screens, Tailwind CSS 4 with shadcn-vue components on reka-ui, tested with Vitest in happy-dom. The protocol client (backoff, `seq` tracking, resync) is plain TypeScript in `web/src/protocol/`, independent of Vue, so it is tested without a browser.

### Alternatives considered

- **Two repositories:** independent releases, but every protocol change becomes two PRs that must land together, and the drift check could not run in one gate. Rejected.
- **Hand-written TypeScript types, or a shared JSON Schema edited by hand:** no generator to maintain, but two definitions drift silently. Rejected for one generated source.
- **React (with Vite or Next.js):** the largest ecosystem, but Next.js brings server rendering that a socket-driven single page does not need, and React needs extra libraries for the store and for fine-grained updates of a list that changes five times a second. Vue's reactivity, single-file components and Pinia cover this app with fewer parts. Rejected by a small margin.
- **Svelte:** small bundles and simple stores, but a smaller set of ready accessible components; shadcn-vue on reka-ui gives accessible primitives that are copied in and styled with Tailwind. Rejected.

### Consequences

- A protocol change is one PR: edit the Pydantic model, run `make contracts`, and the client sees the new types at compile time (`vue-tsc` in `make check`).
- Two toolchains to install (uv and pnpm), each with a committed lock file; CI installs both from the locks.
- shadcn-vue components live in `web/src/components/ui/` as our own code, so we maintain them instead of upgrading a package.

<!-- AI-ASSISTED-END -->
