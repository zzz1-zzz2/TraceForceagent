#!/usr/bin/env bash
# Coding Agent 一键环境初始化（Ubuntu 22.04+ / WSL2）
# 用法： bash scripts/bootstrap.sh

set -euo pipefail

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

log() { echo -e "${GREEN}[+]${NC} $*"; }
warn() { echo -e "${YELLOW}[!]${NC} $*"; }
err() { echo -e "${RED}[x]${NC} $*" >&2; }

# ---------- 1. 系统依赖 ----------
log "1/5 安装系统依赖"

if command -v apt-get >/dev/null 2>&1; then
    sudo apt-get update -qq
    sudo apt-get install -y \
        python3.11 python3.11-venv python3-pip \
        ripgrep git curl build-essential \
        ca-certificates gnupg
else
    err "未检测到 apt-get。本脚本仅支持 Ubuntu / Debian 系列。"
    exit 1
fi

# ---------- 2. Python 版本检查 ----------
log "2/5 检查 Python 版本"

PYTHON_BIN=""
for cand in python3.11 python3.12 python3; do
    if command -v "$cand" >/dev/null 2>&1; then
        version=$("$cand" -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')")
        major=$(echo "$version" | cut -d. -f1)
        minor=$(echo "$version" | cut -d. -f2)
        if [ "$major" -ge 3 ] && [ "$minor" -ge 11 ]; then
            PYTHON_BIN="$cand"
            log "使用 $cand ($version)"
            break
        fi
    fi
done

if [ -z "$PYTHON_BIN" ]; then
    err "需要 Python 3.11+，当前没有可用版本"
    exit 1
fi

# ---------- 3. 安装 uv ----------
log "3/5 安装 uv（包管理）"

if ! command -v uv >/dev/null 2>&1; then
    curl -LsSf https://astral.sh/uv/install.sh | sh
    export PATH="$HOME/.local/bin:$PATH"
    # shellcheck disable=SC1091
    source "$HOME/.local/bin/env" 2>/dev/null || true
fi

# ---------- 4. 创建虚拟环境 ----------
log "4/5 创建虚拟环境并安装依赖"

if [ ! -d .venv ]; then
    uv venv --python "$PYTHON_BIN" .venv
fi

# shellcheck disable=SC1091
source .venv/bin/activate

uv pip install --upgrade pip
uv pip install -e ".[dev]"

# ---------- 5. git 配置 ----------
log "5/5 配置 git"

if [ -z "$(git config --global user.name 2>/dev/null || true)" ]; then
    warn "未配置 git user.name，请手动设置："
    warn "  git config --global user.name 'Your Name'"
    warn "  git config --global user.email 'your@email.com'"
fi

if [ ! -f .env ]; then
    cp .env.example .env
    warn "已创建 .env 文件，请编辑填入 API key："
    warn "  vim .env"
fi

# ---------- 验证 ----------
log "环境初始化完成！"

cat <<EOF

${GREEN}下一步${NC}：
  1. 编辑 .env 填入 DEEPSEEK_API_KEY
     ${YELLOW}vim .env${NC}

  2. 激活虚拟环境
     ${YELLOW}source .venv/bin/activate${NC}

  3. 跑 hello world
     ${YELLOW}python -m coding_agent --help${NC}

  4. 跑自建任务
     ${YELLOW}make eval TASK=A_safe_divide${NC}

EOF