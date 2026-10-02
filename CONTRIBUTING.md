<!-- AI-ASSISTED: developer workflow: setup, running the stack, development, tests, make targets, what make check and CI run, layout, troubleshooting, pull requests. -->
# Contributing

This page is the developer workflow: the tools, running the stack and developing without
Docker, the tests and make targets, what `make check` and CI run, the layout and
troubleshooting. The rules for every change (branch names, PR size, tests,
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
| Client tests and quality | Vitest (v8 coverage), @vue/test-utils, happy-dom, Playwright, axe-core, ESLint, vue-tsc |
| Infra | Docker Compose, nginx, Caddy (HTTPS on a public host) |

## Run the full stack

`make demo` does all of this in one command (see the [README](README.md#quick-start)). Step by
step, the same stack is two API nodes on one Redis behind nginx; you need Docker with Compose v2,
`make`, `curl` and `openssl`.

1. Write the two secrets the stack needs into `.env`: the mock admin token and the stack Redis
   password ([`.env.example`](.env.example) lists the other settings):

   ```bash
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

4. `make new-quiz` starts a fresh 60-minute quiz under a new ID and prints its player URL. Open
   it in two browser windows and join with another name in each: each tab is its own player.
5. `make down` stops the stack and keeps the Redis data; `docker compose --profile full down -v`
   also deletes it.

## Develop without Docker

One API node with an in-memory store, and the client's dev server, which reloads the page when
a client file changes. The API does not reload: restart it after a server change, and the quizzes
in its memory store are lost with it.

1. Install the dependencies (see [Set up](#set-up)).
2. Start the API on `127.0.0.1:8001`, with the mock admin API turned on so you can create a quiz
   (pick any token):

   ```bash
   ADMIN_MOCK=1 ADMIN_TOKEN=dev-token make dev-api
   ```

3. In a second terminal, start the client on port 5173: `pnpm -C web dev`.
4. In a third terminal, create a quiz with the same token. `VOCAB-42` is one of the seeded
   quizzes (`BIZ-20` and `ACAD-10` are the others); it stays open for 10 minutes:

   ```bash
   ADMIN_TOKEN=dev-token
   curl -X POST http://127.0.0.1:8001/admin/quizzes \
     -H "X-Admin-Token: $ADMIN_TOKEN" -H 'Content-Type: application/json' \
     -d '{"quizId": "VOCAB-42"}'
   ```

5. Open <http://localhost:5173/q/VOCAB-42> in two browser windows and play. Press Ctrl+C in
   the API and client terminals to stop.

To run the development API on Redis instead: `make up`, then
`STORE=redis ADMIN_MOCK=1 ADMIN_TOKEN=dev-token make dev-api`, and `make down` afterwards.

### Work on the design system

The client's look lives in the Clay design system, the workspace package `web/packages/clay`
(`@quiz/clay`): its tokens, Tailwind theme, font and components. `make clay` serves its component
gallery on <http://localhost:5180>, which shows every token and every component variant and state
in the light and the dark theme side by side, and reloads on every change; it needs no API. App code
imports the package only from `@quiz/clay` (ESLint enforces it). The package's
[README](web/packages/clay/README.md) explains how to add a token or a component, and
`pnpm -C web exec vitest run --project clay` runs its tests alone.

## Run the tests

The [Make targets](#make-targets) table says what each test target runs. `make test` and
`make acceptance` on the memory store need only the [Set up](#set-up) tools; `make check` runs
before every pull request and needs Docker (see [below](#what-make-check-runs)). The other
layers need more:

- `make test-integration`: the integration tests use `REDIS_URL` when it is set, else a Redis
  container of their own; the acceptance tests on Redis always start their own (Docker).
- `make ui-check`: the visual and accessibility specs (`web/e2e/visual.spec.ts`,
  `web/e2e/a11y.spec.ts`, and `web/e2e/gallery.visual.spec.ts` for the design system's gallery) on
  the production build, with no backend: `web/e2e/fixtures/` mocks the
  HTTP calls and the quiz socket and pauses the page clock. Eleven screens, from the join form to
  the final results, run at 320, 768 and 1280 px wide in light and dark with reduced motion (the
  Leaderboard tab only below 1024 px; wider, the leaderboard sits beside every play screen). Each
  must match its screenshot baseline in `web/e2e/__screenshots__/` (at most 50 pixels differ) and
  pass axe for WCAG 2.2 A and AA, with no sideways scroll (also at 640 px, a 1280 px window at
  200% zoom), controls of at least 44 × 44 px and a visible focus ring at every Tab stop. The
  gallery has one baseline per colour scheme at 1280 px, and passes axe with no sideways scroll at
  every width. It all runs in the Playwright image pinned in the `Makefile`, always as
  `linux/amd64`, so every machine renders like CI; it needs Docker, and `make check` needs no browser. `make ui-baselines`
  regenerates the baselines that changed, in the same image; `UI_ARGS` passes Playwright arguments
  to both, for example `make ui-check UI_ARGS="--project=320-light -g 'join-error'"`. The CI job
  `ui` runs it and keeps the report and the screenshot diffs when it fails.
- The tests below need the running Docker stack, and they create the seeded quizzes themselves:
  the system tests `BIZ-20`, the browser specs `VOCAB-42` and `ACAD-10`. A quiz ID can be
  created only once on the same stack data, so an earlier run of them, or a seeded quiz you
  created by hand, makes them fail with HTTP 409 (the IDs of `make demo` and `make new-quiz`
  never collide). The `make demo` stack does not suit them either: it raises the connection
  cap that the system tests check. Start from fresh stack data first:

  ```bash
  make demo-stop    # removes the demo's bots, which the next command leaves running
  docker compose --profile full down -v
  docker compose --profile full up -d --wait
  ```

  Then run the system tests, the browser specs and `make smoke-full`, in that order.
  `make smoke-full` reuses the browser specs' `VOCAB-42` while it is open (10 minutes); after
  that, start from fresh stack data again.
  - `make test-system`: system tests through nginx (`api/tests/system/`): a score on one node
    reaches a socket on the other, the origin check, the connection cap, the security headers.
  - `make test-browser`: browser specs in Chromium with an accessibility scan (`web/e2e/`,
    Playwright); once before the first run: `pnpm -C web exec playwright install chromium`.
  - `make smoke-full`: checks `/healthz` and `/readyz` on each node, plays one question through
    nginx, stops the API node that holds the socket, and checks that the player is back on the
    other node within 10 s with its score (`load/smoke_full.py`).
  - The bot swarm (`load/bots.py`) plays quizzes and reports the answer → leaderboard latency,
    for example 10 bots for 30 seconds:
    `uv run --project api python load/bots.py --admin-token "$(sed -n 's/^ADMIN_TOKEN=//p' .env)" --bots 10 --duration 30`.
    Without `--admin-token` it plays quizzes that already exist. `make load` runs it as a
    container on the stack network, with its options in `LOAD_ARGS`;
    [load/README.md](load/README.md) explains them and holds the measured load runs.
- `docker compose --profile test run --rm test`: `make test` and the acceptance tests on the
  memory store in a container, with no uv or pnpm on the host. It needs `.env` (step 1 of
  [Run the full stack](#run-the-full-stack), or `make demo` writes it), as every Compose command
  does.

## Make targets

`make help` lists them with one line each.

| Target | What it does |
|---|---|
| `make dev-api` | One API node on `127.0.0.1:8001` (memory store) that allows the client dev server's origins; `DEV_API_PORT` and `DEV_ORIGINS` change them. `pnpm -C web dev` serves the client on :5173 and proxies `/api/*` (prefix dropped) and `/ws` to it, or to `QUIZ_API_URL` |
| `make up`, `make down` | `make up` starts the development Redis on `127.0.0.1:6381`; `make down` stops it and the full stack, and keeps their data |
| `make demo`, `make demo-stop` | `make demo` builds the images, starts the full stack, a fresh 60-minute quiz and `BOTS` bots (default 20) on it, and prints the quiz ID, the player URL and the command that ends the quiz; it writes `.env` with new secrets when there is none, and can run again on the same stack. `make demo-stop` removes the bots |
| `make new-quiz` | Start a fresh 60-minute quiz on the running stack and print its ID, its player URL and the command that ends it. Each run gets a new ID (`VOCAB-42-7K3Q`) that plays the seed quiz `VOCAB-42` (`bankQuizId` of `POST /admin/quizzes`), so it never collides with an earlier run or with the seed quiz IDs that the system tests and browser specs create |
| `make demo-end ID=<id>` | End that quiz now as the mock host (`POST /admin/quizzes/{id}/end`): every player sees the final results |
| `make smoke-full` | Smoke-test the running full stack through nginx: health checks on each node, one answer, then stop the node that holds the socket and check the player comes back on the other node (`load/smoke_full.py`) |
| `make prod-up`, `make prod-down`, `make prod-logs`, `make prod-demo` | The full stack on a public host behind Caddy's HTTPS (`compose.yaml` with `compose.prod.yaml`, settings from `.env.prod.example`): pull the published images of `IMAGE_TAG` (or build them when it is empty) and start, stop, follow the logs, and start a fresh 60-minute quiz with its HTTPS player URL ([docs/operations.md](docs/operations.md)) |
| `make prod-update`, `make prod-backup`, `make prod-restore FILE=…` | On the public host: pull and restart with a rollback when it does not get ready, and back up or restore the quiz data, the certificates and `.env` (`scripts/deploy/ops.sh`) |
| `make do-deploy DOMAIN=…`, `make do-destroy` | From a laptop with a signed-in `doctl`: create the public host as a DigitalOcean Droplet with its firewall and DNS record, or delete them (`scripts/deploy/droplet.sh`; `DRY_RUN=1` prints the commands) |
| `make fly-launch FLY_APP=…`, `make fly-deploy`, `make fly-demo`, `make fly-status`, `make fly-destroy` | From a laptop with a logged-in `flyctl`: create the Fly.io apps, volume, secrets (kept in `.env.fly`) and addresses, deploy Redis, the API and the web edge, start a quiz, show the Machines, or delete it all (`scripts/deploy/fly.sh`; `DRY_RUN=1` prints the commands) |
| `make load` | The bot swarm as a container on the stack network against the running full stack, with its options in `LOAD_ARGS` ([load/README.md](load/README.md) explains them and holds the measured runs) |
| `make test` | The server unit, property and contract tests and the client tests, without Redis |
| `make test-integration` | The tests that need Redis (a Redis container per run, or `REDIS_URL` when it is set), then the acceptance tests on Redis |
| `make acceptance` | The acceptance tests alone; `ACCEPTANCE_STORE=redis` runs them on Redis |
| `make test-system` | The system tests (`api/tests/system/`) against a running full stack at `STACK_URL` (default `http://localhost:$QUIZ_PORT`), with the `ADMIN_TOKEN` from `.env` |
| `make test-browser` | The Playwright browser specs (`web/e2e/`, with an axe accessibility scan) in Chromium against the same stack |
| `make ui-check`, `make ui-baselines` | The visual and accessibility specs in the pinned Playwright image (Docker), and the regeneration of their screenshot baselines ([Run the tests](#run-the-tests)) |
| `make clay` | Serve the Clay design system's component gallery on :5180 ([Work on the design system](#work-on-the-design-system)) |
| `make check` | Every check a change must pass; it stops at the first failing step |
| `make contracts` | Regenerate the JSON Schema and the client's TypeScript types from the server's models |
| `make build` | Build the images `elsaquiz-api` and `elsaquiz-web` (tag `IMAGE_TAG`, default `dev`) |
| `make review-budget` | Count the branch's review input (the diff plus the full changed files) in tokens, against `BASE_SHA` or `origin/main` |
| `make audit` | The dependency audits (`pip-audit`, `pnpm audit`) and the gitleaks scan of the whole history (also alone: `make audit-python`, `make audit-web`, `make audit-secrets`); needs the network, a full clone and gitleaks 8.25 or later |

## What `make check` runs

In order, stopping at the first failing step:

1. The client install from the lock file (`pnpm install --frozen-lockfile`).
2. Every pre-commit hook on every file: ruff lint and format, ESLint, typos, and lychee (in
   Docker) on the relative links and anchors of the tracked Markdown.
3. The test citations: each test that the tracked Markdown cites as a file path, `::` and a
   test name, outside the AI-LOG entries, exists (`scripts/check_citations.py`).
4. actionlint and zizmor on the workflows: zizmor fails on a finding of medium severity or
   higher, and `.github/zizmor.yml` requires every action to be pinned to a full commit SHA.
5. mypy (strict) and import-linter.
6. deptry: every import in `api/src` is a declared dependency and every runtime dependency is
   used; `api/tests`, `scripts/` and `load/` import only declared packages.
7. pytest without the `integration`, `acceptance` and `system` markers, with a unit
   branch-coverage floor (`UNIT_COVERAGE_FLOOR` in the `Makefile`), then the acceptance tests on
   the memory store.
8. The contract drift check: the generated schema and types match the server's models.
9. vue-tsc over the app and the workspace packages, then Vitest with coverage thresholds: the
   app's project and each package's own (`web/vitest.config.ts`).
10. The client build (`pnpm -C web build`).

Each acceptance run writes a JUnit report (into `REPORTS`, else `reports/`), and
`scripts/check_junit_skips.py` fails the run when a test skips that should run: none on the
memory store, only the two exact-time checks on Redis, which need the memory store's injected
clock. The acceptance tests on Redis flush their database before each test, so the make targets
unset `REDIS_URL` for them and they always start a Redis container of their own.

## Continuous integration

Every pull request and every push to `main` runs these GitHub Actions workflows:

- `ci.yml`: `make check`, the Redis integration tests and the acceptance tests on Redis. Its `coverage` job combines the
  coverage data of the test jobs and fails below the combined floor (`fail_under` in
  `api/pyproject.toml`) and, on a pull request, when less than 90% of the changed lines are
  covered (diff-cover). Each run keeps the JUnit reports (`reports-*`) and the coverage data
  (`coverage-*`) as artifacts for 7 days. On a pull request it also runs
  `scripts/check_pr.py` (the size limit, the frozen acceptance tests, the commit trailer and
  the AI-LOG entry; the labels `size-exception` and `acceptance-change` waive the first two,
  and Dependabot's own commits skip the last two)
  and the review budget (`make review-budget`), which fails a PR whose diff plus changed files
  reach the `limit` in `api/pyproject.toml`. Neither counts the paths that `.gitattributes`
  marks `linguist-generated` (lock files, generated contracts, shadcn-vue components).
- `containers.yml`: the container and infrastructure files. hadolint (`.hadolint.yaml`),
  shellcheck, `docker compose config` (alone and with `compose.prod.yaml`), `scripts/check_nginx.sh` (`nginx -t` on the web image's
  site and on any `nginx.conf` under `infra/`, also with the real-ip template of `compose.prod.yaml` rendered), Trivy on the configuration (fails on any
  finding) and on both images (fails on a CRITICAL or HIGH finding that has a fix), and
  `scripts/smoke_images.sh`. The smoke test runs each image as a non-root user on a read-only
  root filesystem until its healthcheck passes, then checks that the web image sends every
  header of `web/security-headers.conf` on `/` and on a hashed asset. Locally:
  `make build && scripts/smoke_images.sh`.
- `codeql.yml` and `security.yml`: CodeQL, the gitleaks scan, dependency review and the
  dependency audits ([SECURITY.md](SECURITY.md) has the details). Both also run weekly.
- `stack.yml`: builds the images, starts the full stack and runs `make test-system` and
  `make test-browser` on every pull request that changes `api/`, `web/`, `infra/`, a compose
  file, a Dockerfile, the `Makefile`, `.nvmrc` or `.python-version`, on pushes to `main` and
  nightly; it uploads the Playwright report, and the stack's logs when a suite fails. Its
  `prod` job starts the stack with `compose.prod.yaml` on top, Caddy using a certificate from
  its local CA (`TLS_ISSUER=internal`), and runs `make test-system` over HTTPS and wss.
- `links.yml` runs weekly and also checks the external links.

The CI, security and container workflows also run weekly on `main`, where the CI run tries ten
times as many Hypothesis examples. A failed scheduled run of any workflow opens, or comments on,
the one open issue labelled `ci-scheduled` (`.github/workflows/scheduled-failure.yml`).

The CI, security, container and stack workflows each end in one gate job (`ci-required`,
`security-required`, `containers-required`, `stack-required`) that fails when a job it needs fails or is
cancelled.

## Dependency updates

Dependabot (`.github/dependabot.yml`) opens weekly pull requests for the GitHub Actions, the
Python and web lock files and the Docker images, with the minor and patch updates of each
ecosystem grouped into one pull request, and only for releases at least 7 days old. The same
wait applies by hand: pnpm resolves only versions that are 7 days old (`minimumReleaseAge` in
`web/pnpm-workspace.yaml`), and the Python lock is upgraded with

```bash
uv lock --project api --upgrade --exclude-newer "7 days"  # newest versions at least 7 days old
uv lock --project api                                     # keeps those versions, drops the cut-off from uv.lock
```

The second command matters: `uv.lock` records the cut-off, and `uv run --locked` without the
same option then reports the lock as out of date.

## Project layout

```text
api/        the server: FastAPI app, Lua scripts, tests (unit, property, contract, integration, acceptance, system)
web/        the Vue 3 client and its tests; web/packages/clay is its design system (@quiz/clay)
contracts/  the JSON Schema of the wire protocol, generated from the server's models
infra/      the nginx and Caddy configuration of the full stack
load/       the bot swarm, the smoke test and the measured load runs
scripts/    the demo and seed scripts, repository checks and generators
docs/       specs, decisions, operations and the AI log
```

## Troubleshooting

- **Port already in use** (`bind: address already in use`): another program holds 8080, 8001,
  5173 or 6381. Stop it, or set `QUIZ_PORT` in `.env` (the stack). To move the development
  API, start it with `DEV_API_PORT` and point the client dev server at it, for example
  `DEV_API_PORT=8002 ADMIN_MOCK=1 ADMIN_TOKEN=dev-token make dev-api` and
  `QUIZ_API_URL=http://127.0.0.1:8002 pnpm -C web dev`.
- **Docker is not running** (`Cannot connect to the Docker daemon`): start Docker Desktop or
  the Docker service; `make demo`, `make build`, the stack, `make test-integration` and
  `make check` need it.
- **`set ADMIN_TOKEN in .env`**: Compose refuses to start the stack until `.env` holds both
  secrets (`make demo` writes them, or step 1 of [Run the full stack](#run-the-full-stack)).
- **The quiz has ended**: a quiz closes when its window ends, and its ID stays taken (HTTP 409)
  while its data lives (24 hours). On the stack, `make new-quiz` starts a fresh 60-minute quiz
  under a new ID. On the development API, create a quiz under a new ID that plays the same
  seeded quiz, optionally with a longer window (`"windowMs": 3600000`, the 60-minute maximum),
  for example `-d '{"quizId": "VOCAB-42-B", "bankQuizId": "VOCAB-42", "windowMs": 3600000}'` in
  the curl of [Develop without Docker](#develop-without-docker), and open `/q/VOCAB-42-B`; or
  restart `make dev-api` to start with empty data.

## Pull requests

Rebase on `main`, run `make check`, and fill in the pull request template. Each PR adds its
AI-LOG entry `docs/ai-log/PR-<n>.md`, written from [the template](docs/ai-log/TEMPLATE.md)
(a PR made only of Dependabot's commits needs none);
[docs/ai-log/README.md](docs/ai-log/README.md) explains the entries.
