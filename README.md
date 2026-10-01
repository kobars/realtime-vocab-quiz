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
make check                   # verify both lock files and that the package imports
```

`make help` lists every target; a target whose work has not landed yet prints
`not yet`.

## Documents

- [DESIGN.md](DESIGN.md) — the system design
- [docs/DECISIONS.md](docs/DECISIONS.md) — architecture decision records
- [docs/TRACEABILITY.md](docs/TRACEABILITY.md) — requirements and their evidence
- [AGENTS.md](AGENTS.md) — rules for contributors and coding agents
