# AI-ASSISTED: target list created at bootstrap; each target's recipe is filled in by the change that implements it.
.DEFAULT_GOAL := help
SHELL := /bin/bash

# Runs one named step of a recipe; on failure it names the step and stops make.
step = @printf '==> %s\n' '$(1)'; $(2) || { printf 'make: step "%s" failed\n' '$(1)' >&2; exit 1; }
PYTEST = cd api && uv run --locked pytest
VITEST = pnpm -C web exec vitest run

.PHONY: help build up down demo demo-stop test test-integration check acceptance load contracts new-quiz ai-log

help: ## List the targets
	@grep -E '^[a-z-]+:.*## ' $(MAKEFILE_LIST) | awk -F':.*## ' '{printf "  %-18s %s\n", $$1, $$2}'

build: ## Build the API and web images
	@echo "not yet"
up: ## Start the development Redis
	docker compose up -d --wait redis
down: ## Stop the development Redis
	docker compose down
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
	$(call step,ruff lint,cd api && uv run --locked ruff check . ../scripts)
	$(call step,ruff format,cd api && uv run --locked ruff format --check . ../scripts)
	$(call step,mypy,cd api && uv run --locked mypy)
	$(call step,pytest,$(PYTEST) -m "not integration and not acceptance")
	$(call step,web install,pnpm -C web install --frozen-lockfile)
	$(call step,contracts drift,uv run --project api --locked python scripts/gen_contracts.py --check)
	$(call step,eslint,pnpm -C web exec eslint --max-warnings 0 .)
	$(call step,vue-tsc,pnpm -C web exec vue-tsc --noEmit)
	$(call step,vitest,$(VITEST))
	$(call step,web build,pnpm -C web build)
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
