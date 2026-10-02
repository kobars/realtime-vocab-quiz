# Real-time vocabulary quiz

A real-time quiz service: players join a quiz session by its ID, answer timed
vocabulary questions, and watch a shared leaderboard update live as scores
change. The server is Python (FastAPI over WebSockets, Redis for scores and
fan-out); the client is a Vue 3 single-page app.

## Stack

| Part | Tools |
|---|---|
| Server | Python 3.14, uv, FastAPI, uvicorn, Pydantic v2, redis-py, structlog, prometheus-client |
| Store | Redis 8 (sorted sets, Lua scripts, pub/sub) |
| Server tests and quality | pytest, pytest-asyncio, pytest-cov, Hypothesis, httpx, ruff, mypy, import-linter, deptry |
| Client | Node 24, pnpm 11, Vue 3, Vite, TypeScript, Pinia, Vue Router, Tailwind CSS, shadcn-vue, VueUse, lucide |
| Client tests and quality | Vitest (v8 coverage), @vue/test-utils, happy-dom, ESLint, vue-tsc |
| Infra | Docker Compose, nginx |

## Run and test

```bash
uv sync --project api        # install the server dependencies
pnpm -C web install          # install the client dependencies
make help                    # list every make target
uv run --project api pre-commit install  # run the hooks on staged files at each commit
make check                   # every check a change must pass; stops at the first failing step
make test                    # the server and client unit tests
make test-integration        # the tests that need Redis (set REDIS_URL to use your own)
make audit                   # the dependency audits and the secret scan (needs the network and gitleaks 8.25+)
make review-budget           # the branch's review input in tokens (diff plus changed files, against origin/main)
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
(`pnpm install --frozen-lockfile`); every pre-commit hook on every file (ruff
lint and format, ESLint, typos, and lychee in Docker on the relative links and
anchors of the tracked Markdown); mypy (strict); import-linter; deptry (every
import in `api/src` is a declared dependency and every runtime dependency is
used; `api/tests`, `scripts/` and `load/` import only declared packages); pytest
(without the `integration` and `acceptance` markers) with a branch-coverage
floor (`api/pyproject.toml`); the contract drift check; vue-tsc; Vitest with coverage thresholds
(`web/vitest.config.ts`); and the client build (`pnpm -C web build`). Every pull
request and every push to `main` runs the same gate in GitHub Actions
(`.github/workflows/ci.yml`), plus the Redis integration tests. The CI, security and
container workflows each end in one gate job (`ci-required`, `security-required`,
`containers-required`) that fails when a job it needs fails or is cancelled. On pull
requests, CI also runs `scripts/check_pr.py` (the size limit, the frozen acceptance
tests, the commit trailer and the AI-LOG entry of `AGENTS.md`; the labels `size-exception`
and `acceptance-change` waive the first two) and the review budget, which fails a PR whose
review input reaches the `limit` in `api/pyproject.toml`. Neither counts the paths that
`.gitattributes` marks `linguist-generated` (lock files, generated contracts, shadcn-vue
components). A weekly job (`.github/workflows/links.yml`)
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

`make help` lists every target.

## Running the full stack

The `full` Compose profile runs two API nodes (`api-1`, `api-2`) on one Redis behind
nginx (`infra/nginx/nginx.conf`), which sends `/` to the web app, `/api/` (prefix
dropped) and `/ws` to the nodes, round-robin. Only nginx publishes a port:
`127.0.0.1:${QUIZ_PORT}`, 8080 by default.

```bash
cp .env.example .env                        # then set ADMIN_TOKEN and REDIS_PASSWORD
make build                                  # the images the stack runs
docker compose --profile full up -d --wait  # returns once every service is healthy
make down                                   # stops the stack and the development Redis
```

The nodes publish no port, so check `/healthz` and `/readyz` on one from inside its
container:

```bash
docker compose exec api-1 python -c "import urllib.request as u; print(u.urlopen('http://127.0.0.1:8000/readyz').read().decode())"
```

## Documents

- [DESIGN.md](DESIGN.md) — the system design
- [docs/DECISIONS.md](docs/DECISIONS.md) — architecture decision records
- [docs/ai-log/](docs/ai-log/) — how AI was used in each change, and how it was checked
- [AGENTS.md](AGENTS.md) — rules for contributors and coding agents
- [SECURITY.md](SECURITY.md) — how to report a vulnerability, and the security scans
