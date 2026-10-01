# System design: real-time vocabulary quiz

<!-- AI-ASSISTED-BEGIN: sections 1-4 drafted with Claude Code from docs/spec/ and docs/DECISIONS.md, checked by hand against the code layout and the import-linter contracts; the Mermaid diagrams were rendered with the Mermaid CLI. -->

## 1. Summary

**The problem.** Players join a vocabulary quiz with a quiz ID, answer timed questions, and
watch one shared leaderboard that changes as anyone scores. Scores must be accurate and
consistent (AC-4) even when many players answer at once through several server nodes.

**The solution.** The quiz is **self-paced**: every player gets the same questions in the same
order, one at a time, at their own pace, and all players share one live leaderboard (ADR-002).
A Vue 3 client keeps one WebSocket open to a FastAPI server. Two API nodes run behind nginx;
**Redis is the primary database** (AOF `everysec`). Every write with more than one step is one
Lua script that reads the time from Redis `TIME`, so any node can score any answer atomically
and a (player, question) scores at most once. Score changes only mark the quiz dirty; a 200 ms
coalescing tick publishes one full leaderboard frame per quiz over Redis pub/sub, numbered by a
per-quiz `seq`, and a client that sees a gap asks for a snapshot. Identity and the question bank
are mocks behind ports, and quiz admin is a mock host action (§14).

**Headline numbers.** The load runs and §9 fill in the measured column.

| Measure | Target (ours) | Measured |
|---|---|---|
| Concurrent sockets, two API nodes | thousands | TODO: from the load runs (§9) |
| Answer accepted → leaderboard delivered, p99 (C5) | below 500 ms | TODO: from the load runs (§9) |
| Leaderboard frames per quiz | at most 5 per second | by design: one per 200 ms tick, only after a change |
| Scoring rule | wrong or late 0; correct `100 + (50 * (T - e)) // T` | exact integers; one formula in Lua and Python |

## 2. Assumptions and non-goals

**How we read the README.** The README asks for joining by quiz ID, scores that update in real
time and a leaderboard that updates promptly. It does not say who opens and closes questions.
We read "real-time" as live scores and one shared live board, and let each player set their own
pace. A host-led quiz would need one owner per quiz to open and close questions on time, with a
failover story; the self-paced model needs no owner, because no rule depends on a timer
(ADR-002, ADR-006). Host-led stays future work.

**Assumptions.**

| Topic | Assumption |
|---|---|
| Players | Anonymous: a mock session gives a user ID; the player types a display name (1–32 characters). One open tab per player and quiz; a second tab replaces the first |
| Quiz shape | 10 questions, 4 choices each, `T` = 20 s per question; the quiz is open for a window from its creation (default 10 min, at most 60 min) or until a mock host ends it |
| Time | The server decides time on one clock (Redis `TIME`); the client countdown is display only |
| Clients | Current browsers with WebSocket support; phones and desktops |
| Store | One Redis 8 (Valkey 8 also works) with AOF `everysec`; a crash can lose about 1 s of answers (§11) |
| Load (our target, not a README requirement) | Thousands of concurrent sockets over **two API nodes** behind nginx, with a cap of 10,000 sockets per process |
| Latency (our target, not a README requirement) | C5: p99 below 500 ms from "answer accepted" to "leaderboard delivered", measured by the load bots |

The README asks the system to "perform well even under heavy load" (F-2) without a number. Our
measurable reading of F-2 is the load and latency rows above, run on one and on two nodes and
reported in §9. Two nodes are our choice: they make the scale-out claims of §10 real.

**Why the design meets each README acceptance criterion.**

| ID | Criterion | How the design meets it |
|---|---|---|
| AC-1 | Join a quiz session with a unique quiz ID | `join {quizId}` on the socket; the `join` script registers the player once per quiz; IDs match `^[A-Z0-9-]{3,16}$` |
| AC-2 | Many users join the same session at the same time | Joins only set `dirty`, so 5,000 joins cost one frame per tick, not one per join; any node accepts any join |
| AC-3 | Scores update in real time | The scoring script returns `answer_result` with the new total at once; the next tick carries it to everyone |
| AC-4 | Scoring is accurate and consistent | One integer formula; two idempotency layers and the deadline check in one atomic script on one clock (C1–C6, §7) |
| AC-5 | A leaderboard shows all participants | Every frame carries every player up to 200; above that the top 50, each other player's own rank, and `get_leaderboard` pages |
| AC-6 | The leaderboard updates promptly | A 200 ms coalescing tick with `seq` and resync; target p99 below 500 ms (C5) |

**Non-goals.** Real accounts or an identity provider; an admin UI or question authoring; a
host-led mode; a per-player question order; results that outlive the 24 h key TTL or a durable
answer log beyond AOF; a graceful drain when a node stops (clients reconnect and resync);
metrics or dashboard containers (the API serves `/metrics` only, §13); native apps;
translations.

## 3. Architecture (D-1)

**Context.** The quiz service is the one component built for real. The identity provider and the
content service are mocks behind ports, so a real one can replace each without touching the
core; the quiz host is a mock admin action. All three are dashed.

```mermaid
flowchart LR
    player(["Player<br/>(browser)"])
    host(["Quiz host<br/>(make new-quiz, end now)"])
    subgraph built["Built for real"]
        quiz["Real-time quiz service<br/>Vue client + API nodes + Redis"]
    end
    idp["Identity provider<br/>(mock: sessions and tickets)"]
    content["Content service<br/>(mock: question bank)"]
    player -- "HTTPS + WebSocket" --> quiz
    host -. "mock admin" .-> quiz
    quiz -. "who is this user?" .-> idp
    quiz -. "quiz questions" .-> content
    classDef mock stroke-dasharray: 5 5
    class idp,content,host mock
```

**Containers.**

```mermaid
flowchart LR
    browser["Browser<br/>Vue 3 SPA<br/>one WebSocket per tab"]
    nginx["nginx :8080<br/>static client, /api and /ws proxy"]
    subgraph nodes["API nodes (FastAPI on uvicorn)"]
        api1["api-1<br/>gateway, use cases, fan-out<br/>/metrics"]
        api2["api-2<br/>gateway, use cases, fan-out<br/>/metrics"]
    end
    redis[("Redis 8<br/>primary database, AOF everysec<br/>Lua scripts, sorted sets, pub/sub")]
    ids["Mock identity<br/>sessions and tickets<br/>(keys in Redis)"]
    bank["Mock question bank<br/>(JSON files in the image)"]
    browser -- "POST /api/sessions, /api/tickets<br/>GET /ws (quiz.v1)" --> nginx
    nginx --> api1
    nginx --> api2
    api1 -- "scripts, subscribe" --> redis
    api2 -- "scripts, subscribe" --> redis
    api1 -.-> ids
    api2 -.-> ids
    api1 -.-> bank
    api2 -.-> bank
    classDef mock stroke-dasharray: 5 5
    class ids,bank mock
```

**Walk-through.** The client gets a mock session once (`POST /sessions`) and a single-use,
30 s ticket before every connect (`POST /tickets`); the `/api` prefix is dropped before the
API. It opens
`GET /ws?ticket=…` with the subprotocol `quiz.v1`; nginx sends the socket to either node, and
the node checks the origin, the ticket and the connection caps before the upgrade. Every
request (`join`, `next`, `answer`, `resync`) becomes one Lua script in Redis, which checks the
deadline and the idempotency keys on Redis `TIME` and writes atomically; the reply goes back on
the same socket. A scoring answer sets the quiz's `dirty` flag. Every node that serves the quiz
calls the tick script about every 200 ms; the one that wins the tick token increments `seq` and
publishes one `leaderboard` frame on `quiz:{<quizId>}:events`, and every node relays it to its
own sockets. Redis is the only database: the mock identity keeps its sessions and tickets
there, so a ticket made on one node works on the other. The mock question bank is read from
JSON files when a node starts.

## 4. Components (D-2)

The server is one Python package, `quiz` (`api/src/quiz/`), split into layers that
import-linter enforces in `make check`: the domain imports nothing else, the use cases see only
the domain, the ports and the wire contracts, the adapters never import each other, and only
the composition root (`quiz/main.py`) wires them.

| Component | Role | Owns | Talks to |
|---|---|---|---|
| Web client (`web/src/`) | The player's UI: join, question, feedback, finished and live leaderboard | The protocol client (backoff, `seq` tracking, resync), the Pinia quiz store, the views and the UI kit | nginx: HTTP for session and ticket, one WebSocket |
| nginx (`infra/`) | The single public entry | The static client, the `/api` and `/ws` routes, WebSocket upgrade headers, `X-Forwarded-For` | Browser; both API nodes |
| API node (`quiz/main.py`) | One FastAPI process; two run side by side | `create_app()`: settings, the chosen adapters, start and stop hooks | nginx; Redis |
| Domain (`quiz/domain/`) | The quiz rules with no I/O | Scoring, standings order and ranks, the player's session states, domain errors | Nothing |
| Contracts (`quiz/contracts/`) | The wire protocol, defined once | Pydantic models of every message and the codec; the source of the generated JSON Schema and TypeScript types | Used by the use cases, the gateway and the client (generated types) |
| App (`quiz/app/`) | The use cases | `QuizService`: join, next, answer, ping, resync, leaderboard pages; turns store results into replies and errors | The ports (`Store`, `QuestionBank`, `Clock`) |
| Ports (`quiz/ports/`) | The interfaces the core depends on | `Store`, `Clock`, `QuestionBank`, `TicketStore` | Implemented by the adapters |
| Store (`quiz/adapters/redis/`, `quiz/adapters/memory/`) | Atomic quiz state | The Redis adapter: key names, script loading and the Lua scripts (join, serve, score, tick, end); the memory twin for unit tests, with an injected clock | Redis (scripts, `TIME`) |
| Gateway (`quiz/adapters/ws/`, `quiz/adapters/http/`) | The edge of a node | The `/ws` endpoint, the upgrade checks (origin, ticket, caps), limits before parsing, heartbeat and send buffers; `POST /sessions`, `POST /tickets`, `/readyz`, `/metrics` | Clients through nginx; the use cases; the ticket store |
| Fan-out (`quiz/fanout/`) | Leaderboard delivery across nodes | The 200 ms tick loop per served quiz, the pub/sub subscription, relay to local sockets, snapshots after a resubscribe | Redis (tick script, pub/sub); the gateway's sockets |
| Mock identity (`quiz/adapters/mock_auth/`) | Stands in for an identity provider | Sessions and single-use tickets (Redis, or memory in tests), display-name rules | Redis |
| Mock question bank (`quiz/adapters/mock_questions/`) | Stands in for a content service | Seed quizzes in `data/*.json`, validated at start | Local files |
| Observability (`quiz/obs/`) | Logs and metrics | JSON logs (structlog) and Prometheus counters and histograms | `/metrics` |
| Redis | Primary database and backplane | All quiz keys `quiz:{<quizId>}:*`, the scripts' atomicity, the clock, the events and control channels | All API nodes |

<!-- AI-ASSISTED-END -->

## 5. Data flow (D-3)
TODO: the flow from joining a quiz to a leaderboard update.

## 6. Technologies and justification (D-4)

<!-- AI-ASSISTED-BEGIN: drafted with Claude Code from docs/DECISIONS.md, api/pyproject.toml and web/package.json; the versions were read from api/uv.lock and web/pnpm-lock.yaml. -->

Each choice is set against the alternative it beat and the cost we accept for it. The ADR
column points to the full reasoning in [docs/DECISIONS.md](docs/DECISIONS.md).

| Component | Choice | Alternative | Reason | Cost we accept | ADR |
|---|---|---|---|---|---|
| Server language and framework | Python 3.14, FastAPI on uvicorn (uvloop, httptools), Pydantic v2 | Node.js (Fastify and `ws`); Go | The wire messages are defined once as Pydantic models, which validate every inbound frame and generate the JSON Schema and the client's TypeScript types; asyncio fits a server that mostly waits on sockets and Redis; FastAPI serves the HTTP endpoints and the WebSocket in one app; Hypothesis tests the scoring and standings rules | One event loop per process uses one CPU core, and JSON encoding per send costs CPU, so a node holds fewer sockets than a Go server would; we scale by adding processes (two nodes) | 001 |
| Transport | One raw WebSocket per tab (`GET /ws`, subprotocol `quiz.v1`), JSON text frames, `permessage-deflate` off | Server-Sent Events plus HTTP POST; Socket.IO | One ordered, two-way channel per player, so an `answer_result` and the next frame keep their order; no extra framing or version-matched client library | We own the heartbeat, the reconnect with backoff and the resync from `seq` | 003 |
| State and scoring | Redis 8: one sorted set per quiz and one Lua script per multi-step write, every time read from Redis `TIME`; AOF `everysec` | `WATCH`/`MULTI` transactions; PostgreSQL with row locks | Every check and its write run in one atomic script on one clock, so a (player, question) scores at most once on any node; ranks read with `ZRANGE` in O(log N + M) | A Redis crash can lose about 1 s of answers (§11); scripts block Redis while they run, so each stays small; one quiz is bounded by one shard | 005, 008 |
| Cross-node fan-out | Redis pub/sub on `quiz:{<quizId>}:events`, a per-quiz `seq` and resync | Redis Streams; a broker (NATS, Kafka) | The tick script increments `seq` and publishes in one atomic step on the Redis we already run; frames are full standings, so a lost one is healed by one snapshot | Delivery is at most once: a missed frame costs the client a snapshot; no history survives a node restart | 004, 006, 007 |
| Client | Vue 3, Vite and TypeScript; Pinia; Vue Router; Tailwind CSS 4 with shadcn-vue on reka-ui | React with Next.js; Svelte | A small single-page app with no server rendering; single-file components, a Pinia store and the protocol client test with Vitest in happy-dom; the generated message types keep client and server in step | The protocol client (backoff, `seq`, resync) is our code; shadcn-vue components are copied into `web/src/components/ui/`, so we maintain them | 009 |
| Edge | nginx: the static client, the `/api` and `/ws` routes to both API nodes | Traefik or HAProxy; uvicorn exposed directly | One origin for the page, the API and the socket, so the origin check stays strict; WebSocket upgrade headers and `X-Forwarded-For` for the per-IP cap; a plain, well-known config | Hand-written config whose read timeouts must exceed the 25 s heartbeat; one nginx is a single point of failure in this stack | 003 |
| Metrics and logs | The Prometheus client (`prometheus-client`) serves `/metrics` on each API node; structlog writes JSON logs. No Prometheus server or Grafana container | OpenTelemetry SDK with a collector; a Prometheus and Grafana stack in Compose | One library and the text format any scraper reads; the stack stays small and the counters and histograms are there for any existing Prometheus to scrape (§13) | No stored history or dashboards in this build: you read `/metrics` directly, and the load runs report their own latency numbers | — |
| Packaging and running | Docker Compose: Redis, two API nodes, nginx and the built client | Kubernetes (kind or minikube); processes started by hand | One command brings the whole stack up the same way on any machine with Docker; the tests start their own Redis container on a free port | One host: no autoscaling, rolling deploy or node spread; production would need an orchestrator | — |
| Build and test tooling | uv and pnpm with committed lock files; pytest, pytest-asyncio and Hypothesis; Vitest | pip or Poetry; npm; unittest | Fast, reproducible installs from the lock files in CI and locally; property tests for the rules that must hold for every input | Two toolchains (Python and Node) to install; the lock files are regenerated, never merged by hand | — |

**Resolved versions.** Read from the lock files (`api/uv.lock`, `web/pnpm-lock.yaml`) and the
version pins next to them; a lock-file change updates this table.

| Package | Version | Source |
|---|---|---|
| Python | 3.14 | `.python-version` |
| FastAPI / Starlette | 0.142.2 / 1.7.0 | `api/uv.lock` |
| uvicorn (uvloop, httptools, websockets) | 0.54.0 (0.23.0, 0.8.0, 17.1) | `api/uv.lock` |
| Pydantic / pydantic-settings | 2.13.5 / 2.15.0 | `api/uv.lock` |
| redis-py (hiredis) | 8.1.0 (3.4.2) | `api/uv.lock` |
| prometheus-client | 0.26.0 | `api/uv.lock` |
| structlog | 26.1.0 | `api/uv.lock` |
| pytest / Hypothesis | 9.1.1 / 6.168.3 | `api/uv.lock` |
| Redis server | `redis:8-alpine` | `compose.yaml` |
| Node / pnpm | 24 / 11.20.0 | `.nvmrc`, `web/package.json` |
| Vue / Vue Router / Pinia | 3.5.43 / 5.3.1 / 4.0.3 | `web/pnpm-lock.yaml` |
| Vite / TypeScript | 8.3.1 / 6.0.3 | `web/pnpm-lock.yaml` |
| Tailwind CSS / reka-ui | 4.3.3 / 2.10.5 | `web/pnpm-lock.yaml` |
| Vitest | 5.0.2 | `web/pnpm-lock.yaml` |

<!-- AI-ASSISTED-END -->

## 7. Consistency contract (AC-4)
TODO: the scoring and ordering guarantees, their mechanisms and the tests that prove them.

## 8. Non-functional requirements
TODO: latency, throughput, availability and durability targets.

## 9. Capacity estimate (F-1, F-2)
TODO: assumptions, per-connection memory, connections per node, messages per question, measured numbers.

## 10. Scalability and trade-offs (F-1)
TODO: how the system scales out and what each choice costs.

## 11. Reliability and failure modes (F-3)
TODO: the failure table (failure, detection, system behavior, user-visible effect, mitigation, proving test).

## 12. Security
TODO: authentication, input limits, origin checks and abuse limits.

## 13. Observability (F-5)
TODO: logs, metrics and how to diagnose a slow or stuck quiz.

## 14. Implemented and mocked (I-1)

<!-- AI-ASSISTED-BEGIN: drafted with Claude Code from the ADR index and the mock adapters' docstrings, checked by hand against the code. -->

**Built for real: the real-time quiz service** (ADR-001), end to end: the Vue client, the
WebSocket gateway, the use cases, the Redis scoring scripts, the coalescing tick and the
pub/sub fan-out across two API nodes behind nginx, plus the tests and the load bots that check
it.

| Part | Implemented in this build |
|---|---|
| Quiz rules and scoring | `quiz/domain/`, mirrored by the Lua scripts; `points.lua` is checked against Python for every elapsed value |
| Atomic state and the clock | The Redis adapter and its Lua scripts; the in-memory twin for unit tests |
| Wire protocol | Pydantic contracts with generated JSON Schema and TypeScript types |
| Gateway and fan-out | The `/ws` endpoint, limits, heartbeat, send buffers; the tick, pub/sub relay, `seq` and resync |
| Client | The Vue 3 app: protocol client with backoff and resync, Pinia store, screens |
| Scale-out | Two API nodes, nginx, one Redis, a two-node integration test and load runs |

**Mocked.** The identity and question-bank mocks sit behind ports (`TicketStore`,
`QuestionBank`) and say `MOCK:` in their module docstrings; quiz admin is a set of make targets
and one host action.

| Mock | What this build does | What production would use instead |
|---|---|---|
| Identity and tickets (`quiz/adapters/mock_auth/`) | `POST /sessions` makes an anonymous user ID and a session token; `POST /tickets` makes a single-use 30 s ticket; both kept in Redis | The company's identity provider (OIDC) for users and sessions; the single-use ticket mechanism stays as built |
| Question bank (`quiz/adapters/mock_questions/`) | Seed quizzes read from JSON files at start-up | A content service or database, edited in an authoring tool |
| Quiz admin | `make new-quiz` and `make demo` create a quiz; a mock host action "end now" ends it | An authenticated admin API and UI with roles, scheduling and quiz settings |

<!-- AI-ASSISTED-END -->

## 15. AI Collaboration in Design (D-5, S-6)
TODO: how AI tools were used in the design, what they got wrong, and how the output was verified.

## 16. GenAI roadmap (V-11)
TODO: where generative AI could improve the product next.

## 17. ADR index

<!-- AI-ASSISTED-BEGIN: one-line summaries drafted with Claude Code from docs/DECISIONS.md. -->

Every decision is recorded in full (context, decision, alternatives considered, consequences) in
[docs/DECISIONS.md](docs/DECISIONS.md). ADRs are never renumbered; a later ADR supersedes an earlier one.

| ADR | Decision |
|---|---|
| [ADR-001](docs/DECISIONS.md#adr-001--build-the-real-time-quiz-service-with-a-python-and-fastapi-server-mock-identity-questions-and-admin) | Build the real-time quiz service for real (Python and FastAPI server, Vue client); mock identity and tickets, the question bank and quiz admin behind ports. |
| [ADR-002](docs/DECISIONS.md#adr-002--self-paced-quiz-model-and-the-integer-scoring-rule) | Self-paced quiz: each player sets their own pace on one shared live board; integer scoring `100 + (50 * (T - e)) // T`, wrong or late 0. |
| [ADR-003](docs/DECISIONS.md#adr-003--transport-raw-websocket-on-fastapi-and-uvicorn) | One raw WebSocket per tab on FastAPI and uvicorn, subprotocol `quiz.v1`, a single-use ticket checked before the upgrade. |
| [ADR-004](docs/DECISIONS.md#adr-004--wire-protocol-standings-policy-and-the-200-ms-coalescing-tick) | Versioned JSON messages with a per-quiz `seq` and resync; full standings up to 200 players, else the top 50 plus `rank_update`; one frame per 200 ms tick. |
| [ADR-005](docs/DECISIONS.md#adr-005--redis-sorted-set-and-lua-scripts-for-scoring-aof-everysec) | Redis sorted set with a composite score and one Lua script per multi-step write, on Redis `TIME`; AOF `everysec`. |
| [ADR-006](docs/DECISIONS.md#adr-006--no-owner-per-quiz-the-dirty-gate-and-a-tick-token) | No owner per quiz: any node runs the tick; a `dirty` gate and a 200 ms tick token decide who publishes. |
| [ADR-007](docs/DECISIONS.md#adr-007--backplane-redis-pubsub-seq-and-resync-streams-as-the-next-step) | Redis pub/sub carries frames and session replacement between nodes; a gap in `seq` triggers a snapshot; Streams are the next step. |
| [ADR-008](docs/DECISIONS.md#adr-008--one-redis-schema-for-scoring-and-fan-out) | One Redis schema: every key of a quiz under the hash tag `quiz:{<quizId>}:*`, one 24 h TTL, ready for a Cluster. |
| [ADR-009](docs/DECISIONS.md#adr-009--repository-layout-and-the-vue-client-api-web-generated-contracts) | One repository with `api/`, `web/` and generated `contracts/`; a Vue 3, Vite, Pinia and Tailwind client using types generated from the Pydantic models. |

<!-- AI-ASSISTED-END -->
