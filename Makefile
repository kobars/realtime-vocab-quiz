# AI-ASSISTED: target list created at bootstrap; each target's recipe is filled in by the change that implements it.
.DEFAULT_GOAL := help
SHELL := /bin/bash

.PHONY: help build up down demo demo-stop test test-integration check acceptance load contracts new-quiz ai-log

help: ## List the targets
	@grep -E '^[a-z-]+:.*## ' $(MAKEFILE_LIST) | awk -F':.*## ' '{printf "  %-18s %s\n", $$1, $$2}'

build: ## Build the API and web images
	@echo "not yet"
up: ## Start the development Redis
	@echo "not yet"
down: ## Stop the development Redis
	@echo "not yet"
demo: ## Run the full stack with seed data and bots
	@echo "not yet"
demo-stop: ## Stop the demo stack
	@echo "not yet"
test: ## Run unit, property and contract tests (no Redis)
	@echo "not yet"
test-integration: ## Run the tests that need Redis
	@echo "not yet"
check: ## Run every check a change must pass
	uv run --project api --locked python -c "import quiz"
acceptance: ## Run the acceptance tests
	@echo "not yet"
load: ## Run the load scenarios with the bot swarm
	@echo "not yet"
contracts: ## Regenerate the JSON Schema and TypeScript types
	@echo "not yet"
new-quiz: ## Create a fresh 60-minute quiz and print its ID and URL
	@echo "not yet"
ai-log: ## Build AI-LOG.md from the entries in docs/ai-log
	@echo "not yet"
