# AI-ASSISTED: build, run, test and check targets.
.DEFAULT_GOAL := help
SHELL := /bin/bash

# Runs one named step of a recipe; on failure it names the step and stops make.
step = @printf '==> %s\n' '$(1)'; $(2) || { printf 'make: step "%s" failed\n' '$(1)' >&2; exit 1; }
PYTEST = cd api && uv run --locked pytest
# The tests that need neither Redis nor a running stack.
UNIT_MARKERS = not integration and not acceptance and not system
# The system and browser tests read the full stack's ADMIN_TOKEN from .env and reach its nginx at
# STACK_URL, by default on the port that compose publishes (QUIZ_PORT).
STACK_ENV = set -a; [ ! -f .env ] || . ./.env; STACK_URL='$(STACK_URL)'; : "$${STACK_URL:=http://localhost:$${QUIZ_PORT:-8080}}"; set +a
VITEST = pnpm -C web exec vitest run
# With REPORTS set to a folder (CI sets it), each test step also writes a JUnit report there.
pytest_junit = $(if $(REPORTS),--junitxml=$(abspath $(REPORTS))/$(1).xml)
vitest_junit = $(if $(REPORTS),--reporter=default --reporter=junit --outputFile.junit=$(abspath $(REPORTS))/vitest.xml)
# The acceptance tests run on the memory store or on Redis. Their Redis harness flushes its database
# before each test, so REDIS_URL is unset and the run starts a Redis container of its own. A skipped
# test passes pytest, so each run writes a JUnit report (into REPORTS, else reports/) and fails on a
# skip the store does not expect: on Redis, the two exact-time checks, which need the memory store's
# injected clock.
export ACCEPTANCE_STORE ?= memory
ACCEPTANCE_SKIPS_memory = 0
ACCEPTANCE_SKIPS_redis = 2
ACCEPTANCE_REPORT = $(abspath $(or $(REPORTS),reports))/acceptance-$(ACCEPTANCE_STORE).xml
define acceptance_steps
$(call step,pytest acceptance,unset REDIS_URL; $(PYTEST) tests/acceptance --junitxml=$(ACCEPTANCE_REPORT))
$(call step,acceptance skips,uv run --project api --locked python scripts/check_junit_skips.py $(ACCEPTANCE_REPORT) --expect $(ACCEPTANCE_SKIPS_$(ACCEPTANCE_STORE)) --reason 'exact-time check')
endef
# make check's floor for the unit run alone; CI gates the combined coverage of its test jobs on
# pyproject's fail_under.
UNIT_COVERAGE_FLOOR = 84
# Tests and dev tools import dev-group packages and use few of the service's runtime ones, so
# only their missing (DEP001) and transitive (DEP003) imports are checked. --exclude replaces
# deptry's default, which skips every folder named tests. pydantic pins pydantic-core to one
# exact version, so scripts/gen_contracts.py may import it directly.
DEPTRY_TOOLS = cd api && uv run --locked deptry tests ../scripts ../load --exclude '\.venv' --ignore DEP002,DEP004 --per-rule-ignores DEP003=pydantic_core
# Workflow security lint; .github/zizmor.yml requires every action to be pinned to a commit SHA.
# Offline: the audits that call the GitHub API need a token.
ZIZMOR = uv run --project api --locked zizmor --offline --config .github/zizmor.yml --min-severity medium .github
# The image tag; both images build from the repository root, so the root .dockerignore applies.
IMAGE_TAG ?= dev
# The API node that the Vite dev server proxies to (web/vite.config.ts) and that server's origins.
DEV_API_PORT ?= 8001
DEV_ORIGINS ?= http://localhost:5173,http://127.0.0.1:5173
# compose reads the whole file in every command, so the full stack's required secrets must be set
# even to start the development Redis or to stop anything. Placeholders: never start the stack with it.
COMPOSE_NO_SECRETS = ADMIN_TOKEN="$${ADMIN_TOKEN:-unused}" REDIS_PASSWORD="$${REDIS_PASSWORD:-unused}" docker compose

.PHONY: help build up down smoke-full dev-api test test-integration test-system test-browser check acceptance load contracts audit audit-python audit-web audit-secrets review-budget

help: ## List the targets
	@grep -E '^[a-z-]+:.*## ' $(MAKEFILE_LIST) | awk -F':.*## ' '{printf "  %-18s %s\n", $$1, $$2}'

build: ## Build the API and web images
	$(call step,api image,docker build -f api/Dockerfile -t elsaquiz-api:$(IMAGE_TAG) .)
	$(call step,web image,docker build -f web/Dockerfile -t elsaquiz-web:$(IMAGE_TAG) .)
	@docker image ls --format '{{.Repository}}:{{.Tag}}  {{.Size}}' --filter reference='elsaquiz-*:$(IMAGE_TAG)'
up: ## Start the development Redis
	$(COMPOSE_NO_SECRETS) up -d --wait redis
down: ## Stop the development Redis and the full stack
	$(COMPOSE_NO_SECRETS) --profile '*' down
smoke-full: ## Smoke-test the running full stack through nginx, stopping one API node
	uv run --project api --locked python load/smoke_full.py
dev-api: ## Run one API node on :8001 for the Vite dev server (pnpm -C web dev)
	cd api && ALLOWED_ORIGINS='$(DEV_ORIGINS)' uv run --locked python -m quiz --host 127.0.0.1 --port $(DEV_API_PORT)
test: ## Run unit, property and contract tests (no Redis)
	$(call step,pytest,$(PYTEST) -m "$(UNIT_MARKERS)")
	$(call step,vitest,$(VITEST))
test-integration: export ACCEPTANCE_STORE = redis
test-integration: ## Run the tests that need Redis, the acceptance tests included (REDIS_URL or a container per run)
	$(call step,pytest integration,$(PYTEST) tests/integration tests/contract -m integration $(call pytest_junit,integration))
	$(acceptance_steps)
test-system: ## Run the system tests against a running full stack at STACK_URL
	$(call step,pytest system,$(STACK_ENV); $(PYTEST) tests/system -m system)
test-browser: ## Run the browser specs in Chromium against a running full stack at STACK_URL
	$(call step,playwright,$(STACK_ENV); pnpm -C web exec playwright test)
check: export ACCEPTANCE_STORE = memory
check: ## Run every check a change must pass
	$(call step,web install,pnpm -C web install --frozen-lockfile)
	$(call step,pre-commit hooks,uv run --project api --locked pre-commit run --all-files)
	$(call step,actionlint,uv run --project api --locked actionlint)
	$(call step,zizmor,$(ZIZMOR))
	$(call step,mypy,cd api && uv run --locked mypy)
	$(call step,import layers,cd api && uv run --locked lint-imports)
	$(call step,dependencies,cd api && uv run --locked deptry src)
	$(call step,tool dependencies,$(DEPTRY_TOOLS))
	$(call step,pytest,$(PYTEST) -m "$(UNIT_MARKERS)" --cov --cov-fail-under=$(UNIT_COVERAGE_FLOOR) $(call pytest_junit,unit))
	$(acceptance_steps)
	$(call step,contracts drift,uv run --project api --locked python scripts/gen_contracts.py --check)
	$(call step,test citations,uv run --project api --locked python scripts/check_citations.py)
	$(call step,vue-tsc,pnpm -C web exec vue-tsc --noEmit)
	$(call step,vitest,$(VITEST) --coverage $(vitest_junit))
	$(call step,web build,pnpm -C web build)
audit: audit-python audit-web audit-secrets ## Run the dependency audits and the secret scan (needs the network)
audit-python: ## Audit the locked Python dependencies with pip-audit
	$(call step,python audit,set -o pipefail; uv export --project api --locked --all-groups --no-emit-project | uvx pip-audit@2.10.1 -r /dev/stdin --disable-pip --strict)
audit-web: ## Audit the production web dependencies (high severity and above)
	$(call step,web audit,pnpm -C web audit --prod --audit-level high)
audit-secrets: ## Scan the git history of HEAD for secrets with gitleaks 8.25 or later (.gitleaks.toml)
	$(call step,full history,[ "$$(git rev-parse --is-shallow-repository 2>/dev/null)" = false ] || { echo 'not a full git clone: the secret scan needs the whole history' >&2; false; })
	$(call step,secret scan,gitleaks git --redact --verbose --no-banner --log-opts='--full-history HEAD' .)
review-budget: ## Count the branch's review input in tokens, against BASE_SHA or origin/main
	uv run --project api --locked python scripts/review_budget.py
acceptance: ## Run the acceptance tests alone (ACCEPTANCE_STORE=redis: on Redis)
	$(acceptance_steps)
load: ## Run the bot swarm against the running full stack; options in LOAD_ARGS (load/README.md)
	docker compose --profile load run --rm --build --user "$$(id -u):$$(id -g)" load $(LOAD_ARGS)
contracts: ## Regenerate the JSON Schema and TypeScript types
	$(call step,web install,pnpm -C web install --frozen-lockfile)
	$(call step,contracts,uv run --project api --locked python scripts/gen_contracts.py)
