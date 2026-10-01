# AI-ASSISTED: target list created at bootstrap; each target's recipe is filled in by the change that implements it.
.DEFAULT_GOAL := help
SHELL := /bin/bash

# Runs one named step of a recipe; on failure it names the step and stops make.
step = @printf '==> %s\n' '$(1)'; $(2) || { printf 'make: step "%s" failed\n' '$(1)' >&2; exit 1; }
PYTEST = cd api && uv run --locked pytest
VITEST = pnpm -C web exec vitest run
# The image tag; both images build from the repository root, so the root .dockerignore applies.
IMAGE_TAG ?= dev
# The API node that the Vite dev server proxies to (web/vite.config.ts) and that server's origins.
DEV_API_PORT ?= 8001
DEV_ORIGINS ?= http://localhost:5173,http://127.0.0.1:5173

.PHONY: help build up down dev-api demo demo-stop test test-integration check acceptance load contracts new-quiz ai-log audit audit-python audit-web audit-secrets

help: ## List the targets
	@grep -E '^[a-z-]+:.*## ' $(MAKEFILE_LIST) | awk -F':.*## ' '{printf "  %-18s %s\n", $$1, $$2}'

build: ## Build the API and web images
	$(call step,api image,docker build -f api/Dockerfile -t elsaquiz-api:$(IMAGE_TAG) .)
	$(call step,web image,docker build -f web/Dockerfile -t elsaquiz-web:$(IMAGE_TAG) .)
	@docker image ls --format '{{.Repository}}:{{.Tag}}  {{.Size}}' --filter reference='elsaquiz-*:$(IMAGE_TAG)'
up: ## Start the development Redis
	docker compose up -d --wait redis
down: ## Stop the development Redis
	docker compose down
dev-api: ## Run one API node on :8001 for the Vite dev server (pnpm -C web dev)
	cd api && ALLOWED_ORIGINS='$(DEV_ORIGINS)' uv run --locked python -m quiz --host 127.0.0.1 --port $(DEV_API_PORT)
demo: ## Run the full stack with seed data and bots
	@echo "not yet"
demo-stop: ## Stop the demo stack
	@echo "not yet"
test: ## Run unit, property and contract tests (no Redis)
	$(call step,pytest,$(PYTEST) -m "not integration and not acceptance")
	$(call step,vitest,$(VITEST))
test-integration: ## Run the tests that need Redis (REDIS_URL or a container per run)
	$(call step,pytest integration,$(PYTEST) tests/integration tests/contract -m integration; rc=$$?; [ $$rc -eq 0 ] || [ $$rc -eq 5 ])
check: ## Run every check a change must pass
	$(call step,internal content,uv run --project api --locked python scripts/check_internal.py)
	$(call step,ruff lint,cd api && uv run --locked ruff check . ../scripts ../load)
	$(call step,ruff format,cd api && uv run --locked ruff format --check . ../scripts ../load)
	$(call step,mypy,cd api && uv run --locked mypy)
	$(call step,import layers,cd api && uv run --locked lint-imports)
	$(call step,pytest,$(PYTEST) -m "not integration and not acceptance" --cov)
	$(call step,web install,pnpm -C web install --frozen-lockfile)
	$(call step,contracts drift,uv run --project api --locked python scripts/gen_contracts.py --check)
	$(call step,eslint,pnpm -C web exec eslint --max-warnings 0 .)
	$(call step,vue-tsc,pnpm -C web exec vue-tsc --noEmit)
	$(call step,vitest,$(VITEST) --coverage)
	$(call step,web build,pnpm -C web build)
audit: audit-python audit-web audit-secrets ## Run the dependency audits and the secret scan (needs the network)
audit-python: ## Audit the locked Python dependencies with pip-audit
	$(call step,python audit,set -o pipefail; uv export --project api --locked --all-groups --no-emit-project | uvx pip-audit@2.10.1 -r /dev/stdin --disable-pip --strict)
audit-web: ## Audit the production web dependencies (high severity and above)
	$(call step,web audit,pnpm -C web audit --prod --audit-level high)
audit-secrets: ## Scan the whole git history for secrets with gitleaks 8.25 or later (.gitleaks.toml)
	$(call step,full history,[ "$$(git rev-parse --is-shallow-repository 2>/dev/null)" = false ] || { echo 'not a full git clone: the secret scan needs the whole history' >&2; false; })
	$(call step,secret scan,gitleaks git --redact --verbose --no-banner .)
acceptance: ## Run the acceptance tests
	@echo "not yet"
load: ## Run the load scenarios with the bot swarm
	@echo "not yet"
contracts: ## Regenerate the JSON Schema and TypeScript types
	$(call step,web install,pnpm -C web install --frozen-lockfile)
	$(call step,contracts,uv run --project api --locked python scripts/gen_contracts.py)
new-quiz: ## Create a fresh 60-minute quiz and print its ID and URL
	@echo "not yet"
ai-log: ## Build AI-LOG.md from the entries in docs/ai-log
	@echo "not yet"
