"""HTML 结构验证：验证 index.html 是否包含所有必需的 section 和导航。"""

import re
from pathlib import Path


def test_index_exists():
    """index.html 必须存在。"""
    p = Path("index.html")
    assert p.exists(), "index.html not found"


def test_html_has_doctype():
    """必须有正确的 HTML5 doctype。"""
    content = Path("index.html").read_text(encoding="utf-8")
    assert re.search(r"<!DOCTYPE\s+html>", content, re.IGNORECASE), \
        "Missing <!DOCTYPE html>"


def test_html_has_navigation():
    """必须有 <nav> 元素。"""
    content = Path("index.html").read_text(encoding="utf-8")
    assert re.search(r"<nav[\s>]", content), "Missing <nav>"


def test_html_has_at_least_4_nav_links():
    """导航至少 4 个锚点链接。"""
    content = Path("index.html").read_text(encoding="utf-8")
    nav_links = re.findall(r'href="#[\w-]+"', content)
    assert len(nav_links) >= 4, \
        f"Need ≥4 anchor links, found {len(nav_links)}: {nav_links}"


def test_html_has_hero_section():
    """必须有 id="hero" 的 section。"""
    content = Path("index.html").read_text(encoding="utf-8")
    assert 'id="hero"' in content or "id='hero'" in content, \
        "Missing hero section (id=\"hero\")"


def test_html_has_about_section():
    """必须有 id="about" 的 section。"""
    content = Path("index.html").read_text(encoding="utf-8")
    assert 'id="about"' in content or "id='about'" in content, \
        "Missing about section (id=\"about\")"


def test_html_has_projects_section():
    """必须有 id="projects" 的 section。"""
    content = Path("index.html").read_text(encoding="utf-8")
    assert 'id="projects"' in content or "id='projects'" in content, \
        "Missing projects section (id=\"projects\")"


def test_html_has_contact_section():
    """必须有 id="contact" 的 section。"""
    content = Path("index.html").read_text(encoding="utf-8")
    assert 'id="contact"' in content or "id='contact'" in content, \
        "Missing contact section (id=\"contact\")"


def test_html_has_three_project_cards():
    """projects section 至少 3 个项目卡片。"""
    content = Path("index.html").read_text(encoding="utf-8")

    # 抽出 projects section
    match = re.search(
        r'<section[^>]*id=["\']projects["\'][^>]*>(.*?)</section>',
        content,
        re.DOTALL | re.IGNORECASE,
    )
    assert match, "projects section not found or not properly closed"

    projects_html = match.group(1)
    # 项目卡片可以是 <article> 或 class 含 project / card
    cards = len(re.findall(
        r'<article|class=["\'][^"\']*(?:project|card)[^"\']*["\']',
        projects_html,
    ))
    assert cards >= 3, f"Need ≥3 project cards, found {cards}"


def test_html_links_stylesheet():
    """index.html 必须引入 styles.css。"""
    content = Path("index.html").read_text(encoding="utf-8")
    assert re.search(r'<link[^>]*rel=["\']stylesheet["\'][^>]*href=["\']styles\.css["\']', content) or \
           re.search(r'<link[^>]*href=["\']styles\.css["\'][^>]*rel=["\']stylesheet["\']', content), \
        "Missing <link rel=\"stylesheet\" href=\"styles.css\">"


def test_html_includes_script():
    """index.html 必须引入 script.js。"""
    content = Path("index.html").read_text(encoding="utf-8")
    assert re.search(r'<script[^>]*src=["\']script\.js["\']', content), \
        "Missing <script src=\"script.js\">"


def test_about_has_skills():
    """about section 应有技能列表（≥3 项）。"""
    content = Path("index.html").read_text(encoding="utf-8")
    about_match = re.search(
        r'<section[^>]*id=["\']about["\'][^>]*>(.*?)</section>',
        content,
        re.DOTALL | re.IGNORECASE,
    )
    assert about_match, "about section not found"

    about_html = about_match.group(1)
    # 技能列表项
    list_items = len(re.findall(r'<li[\s>]', about_html))
    assert list_items >= 3, \
        f"About section should have ≥3 skill items, found {list_items}"


def test_contact_has_email_or_social():
    """contact section 应有邮箱或社交链接。"""
    content = Path("index.html").read_text(encoding="utf-8")
    contact_match = re.search(
        r'<section[^>]*id=["\']contact["\'][^>]*>(.*?)</section>',
        content,
        re.DOTALL | re.IGNORECASE,
    )
    assert contact_match, "contact section not found"

    contact_html = contact_match.group(1)
    # 邮箱或社交链接（mailto: 或 http:// 链接）
    has_email = "@" in contact_html and ("mailto:" in contact_html or re.search(r"\b\w+@\w+\.\w+", contact_html))
    has_social = bool(re.search(r'href=["\']https?://', contact_html))

    assert has_email or has_social, \
        "Contact section should have email or social media link"