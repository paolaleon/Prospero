# Prosper Challenge — run everything from the repo root.
# Backend dependencies are managed with uv (https://docs.astral.sh/uv/),
# frontend dependencies with npm.
# (Makefile.original is the starter's version, kept for reference.)

BACKEND  := backend
FRONTEND := frontend

# Node doesn't have to be on PATH: point NODE_BIN at its bin folder if it lives
# somewhere else (e.g. `make dev NODE_BIN=/opt/node/bin`).
NODE_BIN ?= $(HOME)/.local/node/bin
export PATH := $(NODE_BIN):$(PATH)

.PHONY: help install dev backend frontend run test build clean

help: ## Show available targets
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | \
		awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-10s\033[0m %s\n", $$1, $$2}'

install: ## Install backend (uv) and frontend (npm) dependencies from their lock files
	uv sync --directory $(BACKEND)
	cd $(FRONTEND) && npm ci

dev: ## Run backend and editor together (open http://localhost:5173); Ctrl+C stops both
	@$(MAKE) --no-print-directory -j2 backend frontend

backend: ## Run only the backend: voice agent + editor API on http://localhost:7860
	uv run --directory $(BACKEND) python bot.py

frontend: ## Run only the editor on http://localhost:5173 (needs the backend)
	cd $(FRONTEND) && npm run dev

run: backend ## Same as `make backend` (kept from the starter)

test: ## Run backend tests, frontend tests and the frontend type check
	uv run --directory $(BACKEND) pytest -q
	cd $(FRONTEND) && npm test && npm run typecheck

build: ## Build the editor for production into frontend/dist
	cd $(FRONTEND) && npm run build

clean: ## Remove installed dependencies, builds and caches
	rm -rf $(BACKEND)/.venv $(FRONTEND)/node_modules $(FRONTEND)/dist $(FRONTEND)/*.tsbuildinfo
	find $(BACKEND) -type d \( -name __pycache__ -o -name .pytest_cache \) -prune -exec rm -rf {} +
