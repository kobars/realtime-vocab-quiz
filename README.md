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
```

`make check` runs, in order: the internal-content guard
(`scripts/check_internal.py`), ruff (lint and format), mypy (strict), pytest
(without the `integration` and `acceptance` markers), ESLint, vue-tsc and
Vitest. Every pull request runs the same gate in GitHub Actions
(`.github/workflows/ci.yml`), plus the Redis integration tests and the guard on
the commit messages and the PR text.

`make help` lists every target; a target whose work has not landed yet prints
`not yet`.

## Documents

- [DESIGN.md](DESIGN.md) — the system design
- [docs/DECISIONS.md](docs/DECISIONS.md) — architecture decision records
- [docs/TRACEABILITY.md](docs/TRACEABILITY.md) — requirements and their evidence
- [AGENTS.md](AGENTS.md) — rules for contributors and coding agents
