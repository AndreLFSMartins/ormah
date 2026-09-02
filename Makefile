.PHONY: help dev server ui-dev ui-build install test lint restart clean logs smoke release eval .venv-guard

# Every gate runs through THIS tree's venv, never the ambient `python`. In a
# Sibling Worktree the ambient interpreter either dies with ModuleNotFoundError
# or, worse, imports the Main Checkout's `ormah` and reports a green that says
# nothing about the code you just changed.
VENV_BIN := .venv/bin

.venv-guard:
	@test -x $(VENV_BIN)/python || { \
	  echo "No .venv in $$(pwd)."; \
	  echo "Provision it here — do not reach for another tree's interpreter:"; \
	  echo "    env -u VIRTUAL_ENV -u PYTHONPATH uv sync"; \
	  exit 1; }

help: ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-15s\033[0m %s\n", $$1, $$2}'

install: ## Install Python package in dev mode + UI deps
	pip install -e ".[dev]"
	cd ui && npm install

server: .venv-guard ## Start the backend server (auto-reloads on Python changes)
	$(VENV_BIN)/python -m ormah.main

ui-dev: ## Start the Vite dev server (hot-reload for UI work)
	cd ui && npm run dev

ui-build: ## Build the UI into ui/dist/ for production
	cd ui && npx vite build

dev: .venv-guard ## Start backend + UI dev server together (requires ctrl-c to stop both)
	@trap 'kill 0' EXIT; \
	$(VENV_BIN)/python -m ormah.main & \
	cd ui && npm run dev

restart: .venv-guard ## Rebuild UI and restart backend (kills existing ormah.main process)
	@echo "==> Building UI..."
	cd ui && npx vite build
	@echo "==> Stopping existing server..."
	-pkill -f "ormah.main" 2>/dev/null || true
	@sleep 1
	@echo "==> Starting server..."
	$(VENV_BIN)/python -m ormah.main &
	@echo "==> Server restarted. Open http://localhost:8787"

test: .venv-guard ## Run the test suite
	$(VENV_BIN)/python -m pytest tests/ -v

lint: .venv-guard ## Run ruff linter
	$(VENV_BIN)/ruff check src/ tests/

# Local eval gate. Bars are set just under the honest baseline measured
# 2026-07-06 with production-faithful floors (whisper: f1 0.69, suppression
# 0.95 @ 100 prompts; recall: recall@8 0.99, f1 0.57, fp_rate 0.64 @ 25
# cases) so real regressions fail while run-to-run jitter passes.
# Corpora are local-only (gitignored).
eval: ## Run whisper + recall evals with fail-below bars
	uv run python -m ormah.cli eval whisper run --fail-below f1=0.65,suppression=0.90
	uv run python -m ormah.cli eval recall run --fail-below recall@8=0.90,f1=0.50,fp_rate=0.75

clean: ## Remove build artifacts
	rm -rf src/ormah/ui_dist ui/node_modules/.vite
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	rm -rf .pytest_cache

logs: ## Tail the server logs (if running in background)
	@echo "Server runs with stdout logging. Use 'make server' in foreground to see logs."

release: ## Local fallback: build and publish the wheel to PyPI (fresh UI build, no sdist upload)
	rm -rf dist/
	cd ui && npm ci && npm run build
	uv build --wheel --out-dir dist
	uv publish dist/*.whl

smoke: ## Run fresh-install smoke test in Docker
	docker build -f tests/smoke/Dockerfile -t ormah-smoke .
	docker run --rm \
		-v ormah-model-cache:/tmp/fastembed_cache \
		ormah-smoke
