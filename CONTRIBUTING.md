<!-- AI-ASSISTED: developer workflow: setup, make targets, what make check and CI run, pull requests. -->
# Contributing

This page is the developer workflow: the tools, the make targets, what `make check` runs and
what CI runs on a pull request. The rules for every change (branch names, PR size, tests,
AI-LOG entries) are in [AGENTS.md](AGENTS.md).

## Set up

You need Python 3.14 with uv, Node 24 with pnpm 11, and Docker (for the integration tests,
the link check and the images).

```bash
uv sync --project api                      # the server dependencies
pnpm -C web install                        # the client dependencies
uv run --project api pre-commit install    # run the hooks on staged files at each commit
```

| Part | Tools |
|---|---|
| Server | Python 3.14, uv, FastAPI, uvicorn, Pydantic v2, redis-py, structlog, prometheus-client |
| Store | Redis 8 (sorted sets, Lua scripts, pub/sub) |
| Server tests and quality | pytest, pytest-asyncio, pytest-cov, Hypothesis, httpx, ruff, mypy, import-linter |
| Client | Node 24, pnpm 11, Vue 3, Vite, TypeScript, Pinia, Vue Router, Tailwind CSS, shadcn-vue, VueUse, lucide |
| Client tests and quality | Vitest (v8 coverage), @vue/test-utils, happy-dom, ESLint, vue-tsc |
| Infra | Docker Compose, nginx |

## Make targets

`make help` lists them.

| Target | What it does |
|---|---|
| `make dev-api` | One API node on `127.0.0.1:8001` (memory store) that allows the client dev server's origins; `DEV_API_PORT` and `DEV_ORIGINS` change them. `pnpm -C web dev` serves the client on :5173 and proxies `/api/*` (prefix dropped) and `/ws` to it, or to `QUIZ_API_URL` |
| `make up`, `make down` | Start and stop the development Redis on `127.0.0.1:6381` (`make down` keeps its data) |
| `make smoke-full` | Smoke-test the running full stack through nginx: health checks on each node, one answer, then stop the node that holds the socket and check the player comes back on the other node (`load/smoke_full.py`) |
| `make test` | The server unit, property and contract tests and the client tests, without Redis |
| `make test-integration` | The tests that need Redis: a Redis container per run, or `REDIS_URL` when it is set |
| `make acceptance` | The acceptance tests; `ACCEPTANCE_STORE=redis` runs them on a Redis of their own |
| `make check` | Every check a change must pass; it stops at the first failing step |
| `make contracts` | Regenerate the JSON Schema and the client's TypeScript types from the server's models |
| `make build` | Build the images `elsaquiz-api` and `elsaquiz-web` (tag `IMAGE_TAG`, default `dev`) |
| `make review-budget` | Count the branch's review input (the diff plus the full changed files) in tokens, against `BASE_SHA` or `origin/main` |
| `make audit` | The dependency audits (`pip-audit`, `pnpm audit`) and the gitleaks scan of the whole history; needs the network, a full clone and gitleaks 8.25 or later |

## What `make check` runs

In order, stopping at the first failing step:

1. The client install from the lock file (`pnpm install --frozen-lockfile`).
2. Every pre-commit hook on every file: ruff lint and format, ESLint, typos, and lychee (in
   Docker) on the relative links and anchors of the tracked Markdown.
3. mypy (strict) and import-linter.
4. deptry: every import in `api/src` is a declared dependency and every runtime dependency is
   used; `api/tests`, `scripts/` and `load/` import only declared packages.
5. pytest without the `integration` and `acceptance` markers, with a unit branch-coverage floor
   (`UNIT_COVERAGE_FLOOR` in the `Makefile`).
6. The contract drift check: the generated schema and types match the server's models.
7. vue-tsc, then Vitest with coverage thresholds (`web/vitest.config.ts`).
8. The client build (`pnpm -C web build`).

## Continuous integration

Every pull request and every push to `main` runs these GitHub Actions workflows:

- `ci.yml`: `make check` and the Redis integration tests. Its `coverage` job combines the
  coverage data of the test jobs and fails below the combined floor (`fail_under` in
  `api/pyproject.toml`) and, on a pull request, when less than 90% of the changed lines are
  covered (diff-cover). Each run keeps the JUnit reports (`reports-*`) and the coverage data
  (`coverage-*`) as artifacts for 7 days. On a pull request it also runs
  `scripts/check_pr.py` (the size limit, the frozen acceptance tests, the commit trailer and
  the AI-LOG entry; the labels `size-exception` and `acceptance-change` waive the first two)
  and the review budget (`make review-budget`), which fails a PR whose diff plus changed files
  reach the `limit` in `api/pyproject.toml`. Neither counts the paths that `.gitattributes`
  marks `linguist-generated` (lock files, generated contracts, shadcn-vue components).
- `containers.yml`: the container and infrastructure files. hadolint (`.hadolint.yaml`),
  shellcheck, `docker compose config`, `scripts/check_nginx.sh` (`nginx -t` on the web image's
  site and on any `nginx.conf` under `infra/`), Trivy on the configuration (fails on any
  finding) and on both images (fails on a CRITICAL or HIGH finding that has a fix), and
  `scripts/smoke_images.sh`. The smoke test runs each image as a non-root user on a read-only
  root filesystem until its healthcheck passes, then checks that the web image sends every
  header of `web/security-headers.conf` on `/` and on a hashed asset. Locally:
  `make build && scripts/smoke_images.sh`.
- `codeql.yml` and `security.yml`: CodeQL, the gitleaks scan, dependency review and the
  dependency audits ([SECURITY.md](SECURITY.md) has the details). Both also run weekly.
- `links.yml` runs weekly and also checks the external links.

The CI, security and container workflows each end in one gate job (`ci-required`,
`security-required`, `containers-required`) that fails when a job it needs fails or is
cancelled.

## Pull requests

Rebase on `main`, run `make check`, and fill in the pull request template. Each PR adds its
AI-LOG entry `docs/ai-log/PR-<n>.md`, written from [the template](docs/ai-log/TEMPLATE.md);
[docs/ai-log/README.md](docs/ai-log/README.md) explains the entries.
