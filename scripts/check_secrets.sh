#!/usr/bin/env bash
# 提交前检查：确保仓库里没有 API key
# 用法： bash scripts/check_secrets.sh

set -euo pipefail

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

errors=0

log() { echo -e "${GREEN}[+]${NC} $*"; }
warn() { echo -e "${YELLOW}[!]${NC} $*"; }
err() { echo -e "${RED}[x]${NC} $*"; errors=$((errors + 1)); }

log "扫描可能的 API key / 敏感凭据..."

# 检查常见 API key 模式
patterns=(
    "sk-[a-zA-Z0-9]{20,}"           # OpenAI / DeepSeek
    "sk_live_[a-zA-Z0-9]{20,}"      # Stripe live
    "AKIA[0-9A-Z]{16}"              # AWS
    "ghp_[a-zA-Z0-9]{36}"           # GitHub PAT
    "gho_[a-zA-Z0-9]{36}"           # GitHub OAuth
    "xox[baprs]-[a-zA-Z0-9-]{10,}"  # Slack
)

# 在所有跟踪的文件里找（排除 .git/）
mapfile -t files < <(git ls-files 2>/dev/null || find . -type f -not -path './.git/*' -not -path './.venv/*' -not -path './runs/*')

for pattern in "${patterns[@]}"; do
    matches=$(grep -rEn "$pattern" "${files[@]}" 2>/dev/null || true)
    if [ -n "$matches" ]; then
        err "发现可能的 API key (匹配 $pattern):"
        echo "$matches" | head -5
        echo ""
    fi
done

# 确认 .env 在 .gitignore
if [ -f .gitignore ]; then
    if ! grep -q "^\.env$" .gitignore; then
        err ".env 不在 .gitignore 中！"
    else
        log ".env 已在 .gitignore"
    fi
fi

# 确认 .env 不在 git 里
if git ls-files --error-unmatch .env 2>/dev/null; then
    err ".env 被 git 跟踪！立即执行： git rm --cached .env"
fi

# 检查 docx 原始文件
if ls *.docx 2>/dev/null | head -1 | grep -q .; then
    warn "根目录有 .docx 文件，建议删除（保留 .md 即可）"
fi

if [ $errors -eq 0 ]; then
    log "✅ 检查通过，无敏感信息泄漏"
    exit 0
else
    err "❌ 发现 $errors 个问题，请修复后再提交"
    exit 1
fi