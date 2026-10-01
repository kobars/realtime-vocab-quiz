# Real-time vocabulary quiz

A real-time quiz service: players join a quiz session by its ID, answer timed
vocabulary questions, and watch a shared leaderboard update live as scores
change. The server is Python (FastAPI over WebSockets, Redis for scores and
fan-out); the client is a Vue 3 single-page app.

**Status: work in progress.** The repository layout, the locked dependencies
and the document skeletons exist; the service itself is being built.

## Stack

| Part | Tools |
|---|---|
| Server | Python 3.14, uv, FastAPI, uvicorn, Pydantic v2, redis-py, structlog, prometheus-client |
| Store | Redis 8 (sorted sets, Lua scripts, pub/sub) |
| Server tests and quality | pytest, pytest-asyncio, pytest-cov, Hypothesis, httpx, ruff, mypy, import-linter |
| Client | Node 24, pnpm 11, Vue 3, Vite, TypeScript, Pinia, Vue Router, Tailwind CSS, shadcn-vue, VueUse, lucide |
| Client tests and quality | Vitest (v8 coverage), @vue/test-utils, happy-dom, ESLint, vue-tsc |
| Infra | Docker Compose, nginx |

## Working today

```bash
uv sync --project api        # install the server dependencies
pnpm -C web install          # install the client dependencies
make help                    # list every make target
uv run --project api pre-commit install  # run the hooks on staged files at each commit
make check                   # every check a change must pass; stops at the first failing step
make test                    # the server and client unit tests
make test-integration        # the tests that need Redis (set REDIS_URL to use your own)
make audit                   # the dependency audits and the secret scan (needs the network and gitleaks 8.25+)
make acceptance              # the acceptance tests; ACCEPTANCE_STORE=redis runs them on a Redis of their own
make build                   # the API and web images, elsaquiz-api and elsaquiz-web (IMAGE_TAG=dev)
make dev-api                 # one API node on 127.0.0.1:8001 (memory store) that allows the :5173 origins
pnpm -C web dev              # client on :5173; /api/* (prefix dropped) and /ws go to 127.0.0.1:8001 or QUIZ_API_URL
```

The API refuses a WebSocket upgrade from an origin it does not allow (HTTP 403).
`ALLOWED_ORIGINS` (comma-separated) lists them; when it is empty, the API allows
`http://localhost` and `http://127.0.0.1` on `QUIZ_PORT` (8080, the nginx entry).
`make dev-api` sets it to the Vite dev server's origins; `DEV_API_PORT` and
`DEV_ORIGINS` change the port and the list.

`make check` runs, in order: the client install from the lock file
(`pnpm install --frozen-lockfile`); every pre-commit hook on every file (the
internal-content guard `scripts/check_internal.py`, ruff lint and format, ESLint,
typos, and lychee in Docker on the relative links and anchors of the tracked
Markdown); mypy (strict); import-linter; pytest (without the `integration` and
`acceptance` markers) with a branch-coverage floor (`api/pyproject.toml`);
the contract drift check; vue-tsc; Vitest with coverage thresholds
(`web/vitest.config.ts`); and the client build (`pnpm -C web build`). Every pull
request runs the same gate in GitHub Actions (`.github/workflows/ci.yml`), plus the
Redis integration tests and the guard on the commit messages and the PR text (run
again when the PR text is edited). A weekly job (`.github/workflows/links.yml`)
also checks the external links.
Another workflow (`.github/workflows/containers.yml`) checks the container and
infrastructure files: hadolint (settings in `.hadolint.yaml`), shellcheck,
`docker compose config`, `scripts/check_nginx.sh` (`nginx -t` on the web image's site
and on any `nginx.conf` under `infra/`), Trivy on the configuration (fails on any
finding) and on both images (fails on a CRITICAL or HIGH finding that has a fix), and
`scripts/smoke_images.sh`, which runs each image as a non-root user on a read-only
root filesystem until its healthcheck passes, then checks that the web image sends every
security header of `web/security-headers.conf` (CSP, `nosniff`, `Referrer-Policy`,
`Permissions-Policy`) on `/` and on a hashed asset (locally:
`make build && scripts/smoke_images.sh`).

`make help` lists every target; a target whose work has not landed yet prints
`not yet`.

## Running the full stack

The `full` Compose profile runs two API nodes (`api-1`, `api-2`) on one Redis behind
nginx (`infra/nginx/nginx.conf`), which sends `/` to the web app, `/api/` (prefix
dropped) and `/ws` to the nodes, round-robin. Only nginx publishes a port:
`127.0.0.1:${QUIZ_PORT}`, 8080 by default.

```bash
cp .env.example .env                        # then set ADMIN_TOKEN and REDIS_PASSWORD
make build                                  # the images the stack runs
docker compose --profile full up -d --wait  # returns once every service is healthy
make smoke-full                             # the smoke run below
make down                                   # stops the stack and the development Redis
```

`make smoke-full` (`load/smoke_full.py`) checks `/healthz` and `/readyz` on each node,
joins through nginx, answers one question, then stops the node that holds its socket:
within 10 s it must be back on the other node through nginx, resynced, with its score.
The stopped node then starts again. It starts the quiz `VOCAB-42` unless it is running;
that quiz stays open for about three minutes, so a later run needs another quiz
(`uv run --project api python load/smoke_full.py --quiz-ids BIZ-20`) or a fresh stack
Redis (`docker compose --profile full down -v`).

The nodes publish no port, so check `/healthz` and `/readyz` on one from inside its
container:

```bash
docker compose exec api-1 python -c "import urllib.request as u; print(u.urlopen('http://127.0.0.1:8000/readyz').read().decode())"
```

## Documents

- [DESIGN.md](DESIGN.md) — the system design
- [docs/DECISIONS.md](docs/DECISIONS.md) — architecture decision records
- [AGENTS.md](AGENTS.md) — rules for contributors and coding agents
- [SECURITY.md](SECURITY.md) — how to report a vulnerability, and the security scans
