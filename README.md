<!-- AI-ASSISTED: project overview: what it does, how to try it, run the tests, how it works, configuration and layout. -->
# Real-time vocabulary quiz

Players join a quiz by its ID, answer timed vocabulary questions, and see a shared
leaderboard that updates live as anyone scores. The server is Python (FastAPI over
WebSockets, with Redis for scores and fan-out); the client is a Vue 3 single-page app.

## Try it

You need Python 3.14 with [uv](https://docs.astral.sh/uv/) 0.10 or later, and Node 24
with pnpm 11. This runs one API node with an in-memory store and the client's dev server.

1. Install the dependencies:

   ```bash
   git clone https://github.com/kobars/realtime-vocab-quiz.git
   cd realtime-vocab-quiz
   uv sync --project api
   pnpm -C web install
   ```

2. Start the API on `127.0.0.1:8001`, with the mock admin API turned on so you can create
   a quiz (pick any token):

   ```bash
   ADMIN_MOCK=1 ADMIN_TOKEN=dev-token make dev-api
   ```

3. In a second terminal, start the client on port 5173:

   ```bash
   pnpm -C web dev
   ```

4. In a third terminal, create a quiz. `VOCAB-42` is one of the seeded quizzes
   (`api/src/quiz/adapters/mock_questions/data/` holds the others); it stays open for 10
   minutes, with 20 seconds per question. Use the token you gave the API:

   ```bash
   ADMIN_TOKEN=dev-token
   curl -X POST http://127.0.0.1:8001/admin/quizzes \
     -H "X-Admin-Token: $ADMIN_TOKEN" -H 'Content-Type: application/json' \
     -d '{"quizId": "VOCAB-42"}'
   ```

5. Open <http://localhost:5173>, enter the quiz ID `VOCAB-42` and a name, and choose
   **Join**. The link <http://localhost:5173/q/VOCAB-42> fills in the ID for you.
6. Open the same link in a second browser tab or window and join with another name. Each
   tab is its own player. Choose **Start** in one of them and answer a question: the
   leaderboard in the other tab moves within a fraction of a second.
7. To stop, press Ctrl+C in the API and client terminals.

## Run the tests

- `make test`: the server unit, property and contract tests, and the client tests (no
  Redis needed).
- `make test-integration`: the tests that need Redis. Each run starts its own Redis
  container (Docker), or uses `REDIS_URL` when it is set.
- `make acceptance`: the black-box acceptance tests over HTTP and the WebSocket;
  `ACCEPTANCE_STORE=redis` runs them on Redis.
- `make check`: every check a change must pass (lint, types, tests with coverage, the
  client build, the link check). Run it before you open a pull request; it needs Docker.

## How it works

- The Vue client gets a mock session, then a single-use ticket, and opens one WebSocket per
  tab (`/ws`, subprotocol `quiz.v1`).
- Each API node (FastAPI on uvicorn) checks the origin, the ticket and the connection limits,
  then turns every `join`, `next` and `answer` into one Lua script in Redis.
- The scripts read the clock from Redis `TIME`, score the answer once, and keep the
  standings in a sorted set, so every node sees the same order.
- A scoring answer marks the quiz dirty. About every 200 ms one node wins a tick token and
  publishes one `leaderboard` frame on Redis pub/sub; every node relays it to its own sockets.
- In the full deployment, nginx serves the built client and spreads `/api` and `/ws` over
  two API nodes.

[DESIGN.md](DESIGN.md) has the architecture, the consistency guarantees, the capacity
estimate and the failure modes.

## What is real and what is mocked

| Part | In this build |
|---|---|
| WebSocket gateway, scoring, standings, fan-out across nodes | Real |
| Redis store (Lua scripts, sorted sets, pub/sub) | Real; an in-memory store with the same contract runs one node without Redis |
| Vue client | Real |
| Identity | Mock: anonymous sessions and single-use tickets, no login |
| Question bank | Mock: seeded quizzes read from JSON files |
| Quiz admin | Mock: `POST /admin/quizzes`, off unless `ADMIN_MOCK=1`, guarded by one shared token |

[DESIGN.md §14](DESIGN.md#14-implemented-and-mocked) says what production would use instead.

## Configuration

The API reads environment variables only (it never loads a `.env` file).
[`api/src/quiz/config.py`](api/src/quiz/config.py) lists every setting with its default, and
[`.env.example`](.env.example) shows the common ones.

| Variable | Default | Meaning |
|---|---|---|
| `STORE` | `memory` | `memory` for one process, `redis` for several nodes |
| `REDIS_URL` | `redis://127.0.0.1:6381/0` | The Redis that `make up` starts (`make down` stops it) |
| `ALLOWED_ORIGINS` | `http://localhost:8080`, `http://127.0.0.1:8080` | Comma-separated origins allowed to open the WebSocket; others get HTTP 403. `make dev-api` sets the client dev server's origins |
| `QUIZ_PORT` | `8080` | The public port; the default allowed origins use it |
| `ADMIN_MOCK`, `ADMIN_TOKEN` | off, none | Turn on the mock admin API; it needs a non-blank token |
| `PER_IP_CONN_CAP` | `50` | WebSocket connections per client address |

`make dev-api` takes `DEV_API_PORT` (8001) and `DEV_ORIGINS`; the client dev server takes
`QUIZ_API_URL` to proxy to another API node.

To run the API on Redis instead of memory:

```bash
make up
STORE=redis ADMIN_MOCK=1 ADMIN_TOKEN=dev-token make dev-api
make down
```

## Project layout

```text
api/        the server: FastAPI app, Lua scripts, tests (unit, property, contract, integration, acceptance)
web/        the Vue 3 client and its tests
contracts/  the JSON Schema of the wire protocol, generated from the server's models
load/       the bot swarm for load runs
scripts/    repository checks and generators
docs/       specs, decisions and the AI log
```

## Documentation

- [DESIGN.md](DESIGN.md): the system design
- [docs/DECISIONS.md](docs/DECISIONS.md): architecture decision records
- [docs/spec/](docs/spec/): the domain, protocol, Redis and UI specs
- [docs/ai-log/](docs/ai-log/README.md): how AI was used in each change, and how it was checked
- [CONTRIBUTING.md](CONTRIBUTING.md): the make targets, the checks and the pull request workflow
- [SECURITY.md](SECURITY.md): how to report a vulnerability

## How AI was used

The design and the code were written with Claude Code. Each pull request gets two AI code
reviews, from Claude Code `/code-review` and Codex; their findings are checked against the code
before anything is fixed. Each change has an entry in
[docs/ai-log/](docs/ai-log/README.md) that says what the AI did, what was wrong in its output,
and which test now checks the fix. [DESIGN.md §15](DESIGN.md#15-ai-collaboration-in-design)
tells the story of the design phase.
