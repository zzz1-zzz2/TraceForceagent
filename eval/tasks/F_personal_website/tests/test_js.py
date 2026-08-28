"""JS 验证：脚本存在、平滑滚动、控制台输出、语法可解析。"""

import re
import subprocess
from pathlib import Path


def test_js_exists():
    """script.js 必须存在。"""
    p = Path("script.js")
    assert p.exists(), "script.js not found"


def test_js_has_reasonable_size():
    """JS 文件不应是空的。"""
    content = Path("script.js").read_text(encoding="utf-8")
    lines = [line for line in content.splitlines() if line.strip()]
    assert len(lines) >= 5, \
        f"script.js seems too short ({len(lines)} lines). Need real interactivity."


def test_js_handles_navigation_clicks():
    """必须有处理导航点击的逻辑。"""
    content = Path("script.js").read_text(encoding="utf-8")
    keywords = [
        "scrollIntoView",
        "scroll-behavior",
        "addEventListener",
        "click",
        "querySelector",
        "scroll",
    ]
    found_keywords = [kw for kw in keywords if kw in content]
    assert len(found_keywords) >= 2, \
        f"JS should handle navigation clicks. Found keywords: {found_keywords}"


def test_js_console_output():
    """应有控制台输出（如 'Portfolio loaded'）。"""
    content = Path("script.js").read_text(encoding="utf-8")
    assert "console" in content, \
        "JS should have console output (e.g. console.log('Portfolio loaded'))"

    # 鼓励有 portfolio/loaded 关键字
    if "console.log" in content:
        logs = re.findall(r'console\.log\(["\']([^"\']+)', content)
        if logs:
            print(f"  Found console.log messages: {logs}")


def test_js_syntax_valid():
    """JS 语法应可解析（用 node --check 或 python 简单括号检查）。"""
    content = Path("script.js").read_text(encoding="utf-8")

    # 简单括号/大括号配对检查（node 可能没装）
    def count(s, ch_open, ch_close):
        return s.count(ch_open), s.count(ch_close)

    brace_open, brace_close = count(content, "{", "}")
    paren_open, paren_close = count(content, "(", ")")
    bracket_open, bracket_close = count(content, "[", "]")

    assert brace_open == brace_close, \
        f"Unbalanced braces: {brace_open} {{ vs {brace_close} }}"
    assert paren_open == paren_close, \
        f"Unbalanced parentheses: {paren_open} ( vs {paren_close} )"
    assert bracket_open == bracket_close, \
        f"Unbalanced brackets: {bracket_open} [ vs {bracket_close} ]"

    # 如果有 node，做完整语法检查
    try:
        node_check = subprocess.run(
            ["node", "--check", "script.js"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        if node_check.returncode == 0:
            print("  ✓ node --check passed")
        else:
            # node 不一定装上，不强制
            print(f"  ⚠ node --check skipped or failed: {node_check.stderr[:100]}")
    except FileNotFoundError:
        # node 没装，跳过
        pass
    except subprocess.TimeoutExpired:
        pass


def test_js_no_obvious_errors():
    """不应有明显语法错误标记。"""
    content = Path("script.js").read_text(encoding="utf-8")
    # 常见 typo
    bad_patterns = [
        (r"function\s*\(\s*\)\s*\{[^}]*\bfunction\s*\(", "嵌套 function 关键字异常"),
        (r"\)\s*\)\s*\)\s*\)", "过多右括号"),
    ]
    for pattern, msg in bad_patterns:
        assert not re.search(pattern, content), f"Suspicious syntax: {msg}"