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
| Server tests and quality | pytest, pytest-asyncio, Hypothesis, httpx, ruff, mypy, import-linter |
| Client | Node 24, pnpm 11, Vue 3, Vite, TypeScript, Pinia, Vue Router, Tailwind CSS, shadcn-vue, VueUse, lucide |
| Client tests and quality | Vitest, @vue/test-utils, happy-dom, ESLint, vue-tsc |
| Infra | Docker Compose, nginx |

## Working today

```bash
uv sync --project api        # install the server dependencies
pnpm -C web install          # install the client dependencies
make help                    # list every make target
uvx pre-commit install       # run the guard, ruff and ESLint on staged files at each commit
make check                   # every check a change must pass; stops at the first failing step
make test                    # the server and client unit tests
make test-integration        # the tests that need Redis (set REDIS_URL to use your own)
make audit                   # the dependency audits and the secret scan (needs the network and gitleaks 8.25+)
make build                   # the API and web images, elsaquiz-api and elsaquiz-web (IMAGE_TAG=dev)
make dev-api                 # one API node on 127.0.0.1:8001 (memory store) that allows the :5173 origins
pnpm -C web dev              # client on :5173; /api/* (prefix dropped) and /ws go to 127.0.0.1:8001 or QUIZ_API_URL
```

The API refuses a WebSocket upgrade from an origin it does not allow (HTTP 403).
`ALLOWED_ORIGINS` (comma-separated) lists them; when it is empty, the API allows
`http://localhost` and `http://127.0.0.1` on `QUIZ_PORT` (8080, the nginx entry).
`make dev-api` sets it to the Vite dev server's origins; `DEV_API_PORT` and
`DEV_ORIGINS` change the port and the list.

`make check` runs, in order: the internal-content guard
(`scripts/check_internal.py`), ruff (lint and format), mypy (strict), pytest
(without the `integration` and `acceptance` markers), the client install from
the lock file (`pnpm install --frozen-lockfile`), ESLint, vue-tsc, Vitest and
the client build (`pnpm -C web build`). Every pull request runs the same gate in GitHub Actions
(`.github/workflows/ci.yml`), plus the Redis integration tests and the guard on
the commit messages and the PR text (run again when the PR text is edited).
A second workflow (`.github/workflows/containers.yml`) checks the container and
infrastructure files: hadolint (settings in `.hadolint.yaml`), shellcheck,
`docker compose config`, `scripts/check_nginx.sh` (`nginx -t` on the web image's site
and on any `nginx.conf` under `infra/`), Trivy on the configuration (fails on any
finding) and on both images (fails on a CRITICAL or HIGH finding that has a fix), and
`scripts/smoke_images.sh`, which runs each image as a non-root user on a read-only
root filesystem until its healthcheck passes (locally: `make build && scripts/smoke_images.sh`).

`make help` lists every target; a target whose work has not landed yet prints
`not yet`.

## Documents

- [DESIGN.md](DESIGN.md) — the system design
- [docs/DECISIONS.md](docs/DECISIONS.md) — architecture decision records
- [docs/TRACEABILITY.md](docs/TRACEABILITY.md) — requirements and their evidence
- [AGENTS.md](AGENTS.md) — rules for contributors and coding agents
- [SECURITY.md](SECURITY.md) — how to report a vulnerability, and the security scans
