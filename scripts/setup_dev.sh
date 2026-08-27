#!/usr/bin/env bash
# 设置开发环境（已在 bootstrap.sh 中调用，可单独使用）
# 用法： bash scripts/setup_dev.sh

set -euo pipefail

cd "$(dirname "$0")/.."

# 创建虚拟环境
if [ ! -d .venv ]; then
    echo "[+] 创建虚拟环境..."
    if command -v uv >/dev/null 2>&1; then
        uv venv --python python3.11 .venv
    else
        python3.11 -m venv .venv
    fi
fi

# 激活
# shellcheck disable=SC1091
source .venv/bin/activate

# 安装依赖
echo "[+] 安装依赖..."
if command -v uv >/dev/null 2>&1; then
    uv pip install --upgrade pip
    uv pip install -e ".[dev]"
else
    pip install --upgrade pip
    pip install -e ".[dev]"
fi

echo "[+] 完成。激活： source .venv/bin/activate"