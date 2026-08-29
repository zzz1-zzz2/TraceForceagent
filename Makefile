# TraceForce Makefile
# These targets are the single source of truth for entry points.
# They MUST stay in sync with the Typer commands in src/coding_agent/cli.py.
# Real CLI surface today: run | tui | check | config show | config path
# Helpers (no auth needed): make help, make test, make lint

PYTHON ?= python3
VENV ?= .venv
BIN := $(VENV)/bin

.PHONY: help setup dev install-deps run tui check config-show config-path test test-cov lint format check-secrets clean

help: ## Show this help.
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "\033[36m%-20s\033[0m %s\n", $$1, $$2}'

# === Environment ===
setup: ## Bootstrap a development venv with dev extras.
	bash scripts/setup_dev.sh

install-deps: ## Recreate venv and install the package + dev extras.
	uv venv $(VENV)
	uv pip install -e ".[dev]"

# === Pre-flight ===
check: ## Run provider/workspace/runtime preflight (no model call).
	$(BIN)/coding-agent check

config-show: ## Show resolved, redacted configuration.
	$(BIN)/coding-agent config show

config-path: ## Print the user-level TOML config path.
	$(BIN)/coding-agent config path

# === Run ===
run: ## Non-interactive single shot. Args: TASK="…" WORKSPACE=path
	$(BIN)/coding-agent run --task "$(TASK)" --workspace "$(WORKSPACE)"

tui: ## Launch the Textual TUI. Args: WORKSPACE=path [ENV_FILE=path]
	@if [ -n "$(ENV_FILE)" ]; then \
		$(BIN)/coding-agent --env-file "$(ENV_FILE)" tui --workspace "$(WORKSPACE)"; \
	else \
		$(BIN)/coding-agent tui --workspace "$(WORKSPACE)"; \
	fi

# === Tests / Lint ===
test: ## Run the unit + integration test suite (credential-free).
	$(BIN)/pytest tests/ -v

test-cov: ## Run tests with coverage report.
	$(BIN)/pytest tests/ --cov=coding_agent --cov-report=html --cov-report=term

lint: ## Ruff lint on src/ and tests/.
	$(BIN)/ruff check src/ tests/

format: ## Ruff format src/ and tests/.
	$(BIN)/ruff format src/ tests/

check-secrets: ## Scan the repo for accidentally committed credentials.
	bash scripts/check_secrets.sh

# === Cleanup ===
clean: ## Remove local caches and build artefacts.
	rm -rf .pytest_cache .mypy_cache .ruff_cache htmlcov .coverage
	find . -type d -name __pycache__ -prune -exec rm -rf {} +