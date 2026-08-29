"""CSS 验证：CSS 变量、响应式、链接、渐变背景。"""

import re
from pathlib import Path


def test_css_exists():
    """styles.css 必须存在。"""
    p = Path("styles.css")
    assert p.exists(), "styles.css not found"


def test_css_uses_variables():
    """必须使用 CSS 变量（定义 --xxx 和使用 var(--xxx)）。"""
    content = Path("styles.css").read_text(encoding="utf-8")

    # 至少 1 个变量定义
    var_defs = re.findall(r'--[\w-]+\s*:', content)
    assert len(var_defs) >= 1, \
        f"Need ≥1 CSS variable definition (e.g. --primary-color: red), found {len(var_defs)}"

    # 至少 1 个 var() 使用
    var_uses = re.findall(r'var\(--[\w-]+', content)
    assert len(var_uses) >= 1, \
        f"Need ≥1 var(--xxx) usage, found {len(var_uses)}"


def test_css_has_media_query():
    """必须包含至少 1 个 @media 响应式断点。"""
    content = Path("styles.css").read_text(encoding="utf-8")
    media_queries = re.findall(r'@media\s+[^{]+', content)
    assert len(media_queries) >= 1, \
        f"Need ≥1 @media query for responsive design, found {len(media_queries)}"


def test_hero_has_gradient_background():
    """hero 区应有渐变背景。"""
    content = Path("styles.css").read_text(encoding="utf-8")

    # 找 hero 相关规则
    hero_match = re.search(
        r'(?:#hero|hero)\s*\{[^}]*\}',
        content,
        re.DOTALL | re.IGNORECASE,
    )
    assert hero_match, "No CSS rule for hero selector"

    hero_css = hero_match.group(0)
    has_gradient = bool(re.search(
        r'(?:linear|radial|conic)-gradient',
        hero_css,
    ))
    assert has_gradient, \
        f"Hero section should have gradient background. Got: {hero_css[:200]}"


def test_css_has_reasonable_size():
    """CSS 不应该是空文件或只有一两行。"""
    content = Path("styles.css").read_text(encoding="utf-8")
    lines = [line for line in content.splitlines() if line.strip()]
    assert len(lines) >= 10, \
        f"styles.css seems too short ({len(lines)} lines). Need a real stylesheet."

    # 不应全是注释
    code_lines = [
        line for line in lines
        if not line.strip().startswith("/*") and not line.strip().startswith("*")
    ]
    assert len(code_lines) >= 5, "styles.css should have substantive CSS rules"


def test_css_targets_modern_layout():
    """鼓励使用 flex 或 grid（现代布局）。"""
    content = Path("styles.css").read_text(encoding="utf-8")
    has_flex = "flex" in content or "flexbox" in content.lower()
    has_grid = "grid" in content.lower()
    assert has_flex or has_grid, \
        "CSS should use flex or grid for modern layout"