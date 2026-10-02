<!-- AI-ASSISTED: project overview: what it does, how to try it, run the tests, how it works, configuration and layout. -->
# Real-time vocabulary quiz

Players join a quiz by its ID, answer timed vocabulary questions, and see a shared
leaderboard that updates live as anyone scores. The real-time server is Python (FastAPI over
WebSockets, with Redis for scores and fan-out across nodes); a Vue 3 single-page app is its
demo client.

**Video walkthrough:** placeholder, the link is added here once the video is published.

**How AI was used.** Claude Code wrote the design, the code and the tests. Pull requests are
reviewed by two AI reviewers, Claude Code `/code-review` and Codex, whose findings are checked
against the code before anything is fixed, and every change runs the checks of
[CONTRIBUTING.md](CONTRIBUTING.md). Each pull request has an entry in
[docs/ai-log/](docs/ai-log/README.md) that says what the AI did, what was wrong in its output,
which test now checks the fix and which review ran.
[DESIGN.md §15](DESIGN.md#15-ai-collaboration-in-design) tells the story of the design phase.

## Try it with Docker

This runs the full stack: two API nodes on one Redis behind nginx. You need Docker with
Compose v2, `make`, `curl` and `openssl`.

1. Clone the repository and write the two secrets the stack needs into `.env` (the mock
   admin token and the stack Redis password; [`.env.example`](.env.example) lists the other
   settings):

   ```bash
   git clone https://github.com/kobars/realtime-vocab-quiz.git
   cd realtime-vocab-quiz
   printf 'ADMIN_TOKEN=%s\nREDIS_PASSWORD=%s\n' "$(openssl rand -hex 24)" "$(openssl rand -hex 24)" > .env
   ```

2. Build the images and start the stack. The second command returns once every service is
   healthy:

   ```bash
   make build
   docker compose --profile full up -d --wait
   ```

3. Check that nginx reaches the API nodes. Both print HTTP 200:

   ```bash
   curl -s -w ' %{http_code}\n' http://localhost:8080/api/healthz   # {"status":"ok"} 200
   curl -s -w ' %{http_code}\n' http://localhost:8080/api/readyz    # {"status":"ready"} 200
   ```

4. Create a quiz. `VOCAB-42` is one of the seeded quizzes (`BIZ-20` and `ACAD-10` are the
   others); it stays open for 10 minutes, with 20 seconds per question:

   ```bash
   ADMIN_TOKEN=$(sed -n 's/^ADMIN_TOKEN=//p' .env)
   curl -X POST http://localhost:8080/api/admin/quizzes \
     -H "X-Admin-Token: $ADMIN_TOKEN" -H 'Content-Type: application/json' \
     -d '{"quizId": "VOCAB-42"}'
   ```

5. Open <http://localhost:8080/q/VOCAB-42>, enter a name and choose **Join**. Open the same
   link in a second browser window and join with another name: each tab is its own player.
   Choose **Start** in one of them and answer a question: the leaderboard in the other window
   moves within a fraction of a second.
6. To stop: `make down`. It stops the stack and keeps the Redis data.

## Try it for development

This runs one API node with an in-memory store and the client's dev server, with hot reload.
You need Python 3.14 with [uv](https://docs.astral.sh/uv/) 0.10 or later, and Node 24 with
pnpm 11.

1. Install the dependencies:

   ```bash
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

4. In a third terminal, create a quiz with the same token:

   ```bash
   ADMIN_TOKEN=dev-token
   curl -X POST http://127.0.0.1:8001/admin/quizzes \
     -H "X-Admin-Token: $ADMIN_TOKEN" -H 'Content-Type: application/json' \
     -d '{"quizId": "VOCAB-42"}'
   ```

5. Open <http://localhost:5173/q/VOCAB-42> in two browser windows and play as in the Docker
   steps above.
6. To stop, press Ctrl+C in the API and client terminals.

## Run the tests

- `make test`: the server unit, property and contract tests, and the client tests (no
  Redis needed).
- `make test-integration`: the tests that need Redis. Each run starts its own Redis
  container (Docker), or uses `REDIS_URL` when it is set.
- `make acceptance`: the black-box acceptance tests over HTTP and the WebSocket;
  `ACCEPTANCE_STORE=redis` runs them on Redis.
- `make smoke-full`: against the running Docker stack, checks `/healthz` and `/readyz` on each
  node, plays one question through nginx, stops the API node that holds the socket, and checks
  that the player is back on the other node within 10 s with its score (`load/smoke_full.py`).
- The bot swarm (`load/bots.py`) plays quizzes against the running Docker stack and reports
  the answer → leaderboard latency, for example 10 bots for 30 seconds:
  `uv run --project api python load/bots.py --admin-token "$ADMIN_TOKEN" --bots 10 --duration 30`.
  Without `--admin-token` it plays quizzes that already exist.
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
- nginx serves the built client and spreads `/api` and `/ws` over the two API nodes.

[DESIGN.md](DESIGN.md) has the architecture, the data flow, the consistency guarantees, the
capacity estimate and the failure modes.

## What is real and what is mocked

The real-time quiz server is the one component built for real; the Vue client is its working
demo interface.

| Part | In this build |
|---|---|
| WebSocket gateway, scoring, standings, fan-out across nodes | Real |
| Redis store (Lua scripts, sorted sets, pub/sub) | Real; an in-memory store with the same contract runs one node without Redis |
| Vue client | Real, as the demo interface of the server |
| Identity | Mock: anonymous sessions and single-use tickets, no login |
| Question bank | Mock: seeded quizzes read from JSON files |
| Quiz admin | Mock: `POST /admin/quizzes`, off unless `ADMIN_MOCK=1`, guarded by one shared token |
| Observability | The `/healthz`, `/readyz` and `/metrics` endpoints of each node and JSON logs; no metrics or dashboard containers ([DESIGN.md §13](DESIGN.md#13-observability)) |

[DESIGN.md §14](DESIGN.md#14-implemented-and-mocked) says what production would use instead.

## Ports and endpoints

| What | Where |
|---|---|
| nginx, the stack's only published port | `127.0.0.1:8080` (`QUIZ_PORT`): `/` the client, `/api/*` (prefix dropped) and `/ws` the API nodes |
| API nodes `api-1`, `api-2` | port 8000 inside the Compose network only |
| Stack Redis | port 6379 inside the Compose network only, with a password |
| Development API (`make dev-api`) | `127.0.0.1:8001` |
| Client dev server (`pnpm -C web dev`) | `localhost:5173` |
| Development Redis (`make up`) | `127.0.0.1:6381`, no password |

Each API node serves `/healthz` (liveness: the process answers), `/readyz` (readiness: 503
when Redis is unreachable) and `/metrics` (Prometheus text format). nginx passes the first two
on as `/api/healthz` and `/api/readyz` and answers 404 for `/api/metrics`; read the metrics
from inside a node:

```bash
docker compose exec api-1 python -c "import urllib.request as u; print(u.urlopen('http://127.0.0.1:8000/metrics').read().decode())"
```

## Configuration

The API reads environment variables only (it never loads a `.env` file; Compose reads `.env`
for the stack). [`api/src/quiz/config.py`](api/src/quiz/config.py) lists every setting with
its default, and [`.env.example`](.env.example) shows the common ones.

| Variable | Default | Meaning |
|---|---|---|
| `STORE` | `memory` | `memory` for one process, `redis` for several nodes |
| `REDIS_URL` | `redis://127.0.0.1:6381/0` | The Redis that `make up` starts (`make down` stops it) |
| `ALLOWED_ORIGINS` | `http://localhost:8080`, `http://127.0.0.1:8080` | Comma-separated origins allowed to open the WebSocket; others get HTTP 403. `make dev-api` sets the client dev server's origins |
| `QUIZ_PORT` | `8080` | The public port; the default allowed origins use it |
| `ADMIN_MOCK`, `ADMIN_TOKEN` | off, none | Turn on the mock admin API; it needs a non-blank token |
| `REDIS_PASSWORD` | none | The stack Redis password (Docker stack only) |
| `PER_IP_CONN_CAP` | `50` | WebSocket connections per client address |

`make dev-api` takes `DEV_API_PORT` (8001) and `DEV_ORIGINS`; the client dev server takes
`QUIZ_API_URL` to proxy to another API node.

To run the development API on Redis instead of memory:

```bash
make up
STORE=redis ADMIN_MOCK=1 ADMIN_TOKEN=dev-token make dev-api
make down
```

## Troubleshooting

- **Port already in use** (`bind: address already in use`): another program holds 8080, 8001,
  5173 or 6381. Stop it, or set `QUIZ_PORT` in `.env` (the stack) or `DEV_API_PORT` (the
  development API).
- **Docker is not running** (`Cannot connect to the Docker daemon`): start Docker Desktop or
  the Docker service; `make build`, the stack, `make test-integration` and `make check` need it.
- **`set ADMIN_TOKEN in .env`**: Compose refuses to start the stack until `.env` holds both
  secrets (step 1 of the Docker path).
- **The quiz has ended**: a quiz closes when its window ends, and its ID stays taken (HTTP 409)
  while its data lives (24 hours). Create another seeded quiz (`BIZ-20` or `ACAD-10`), pass a
  longer window (`"windowMs": 3600000`, the 60-minute maximum), or start with empty data:
  restart `make dev-api` (memory store), or run `docker compose --profile full down -v` (stack).

## Project layout

```text
api/        the server: FastAPI app, Lua scripts, tests (unit, property, contract, integration, acceptance)
web/        the Vue 3 client and its tests
contracts/  the JSON Schema of the wire protocol, generated from the server's models
infra/      the nginx configuration of the full stack
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
