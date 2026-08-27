# Coding Agent Makefile
# 使用方式: make <target>

PYTHON ?= python3
VENV ?= .venv
BIN := $(VENV)/bin

.PHONY: help setup dev test eval eval-all-l1 tui clean lint format check-secrets install-deps

help: ## 显示帮助
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "\033[36m%-20s\033[0m %s\n", $$1, $$2}'

# === 环境 ===
setup: ## 初始化开发环境（创建 venv，安装依赖）
	bash scripts/setup_dev.sh

install-deps: ## 安装依赖
	uv venv $(VENV)
	uv pip install -e ".[dev]"

# === 运行 ===
dev: ## 开发模式运行（CLI help）
	$(BIN)/python -m coding_agent --help

tui: ## 启动 Textual TUI
	$(BIN)/python -m coding_agent --tui

# === 测试 ===
test: ## 跑单元测试
	$(BIN)/pytest tests/ -v

test-cov: ## 跑测试并生成覆盖率
	$(BIN)/pytest tests/ --cov=coding_agent --cov-report=html --cov-report=term

# === 评测 ===
eval: ## 跑单个 L1 任务（如 make eval TASK=A_safe_divide）
	$(BIN)/python -m eval.run_task --task eval/tasks/$(TASK) --model deepseek-chat

eval-all-l1: ## 跑全部 5 个 L1 任务
	@for task in A_safe_divide B_cache_clear C_config_friendly D_chunked_robust E_todo_cli; do \
		echo "=================================================="; \
		echo "Running $$task..."; \
		$(BIN)/python -m eval.run_task --task eval/tasks/$$task --model deepseek-chat --quiet || true; \
	done

eval-real: ## 跑真实 Issue（如 make eval-real TASK=django_make_toast）
	$(BIN)/python -m eval.run_task --task eval/real/$(TASK) --model deepseek-chat

# === 工具 ===
lint: ## Ruff lint
	$(BIN)/ruff check src/ tests/

format: ## Ruff format
	$(BIN)/ruff format src/ tests/

check-secrets: ## 检查仓库里有没有 API key
	bash scripts/check_secrets.sh

# === 清理 ===
clean: ## 清理临时文件
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name .pytest_cache -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name .ruff_cache -exec rm -rf {} + 2>/dev/null || true
	rm -rf runs/* logs/ htmlcov/ .coverage 2>/dev/null || true