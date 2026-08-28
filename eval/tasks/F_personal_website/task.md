# 任务 F：创建个人作品集网页

从零（Greenfield）构建一个个人作品集网页，演示完整的 HTML/CSS/JS 开发能力。

## 文件要求

### 1. `index.html`（必须包含以下结构）

- **`<nav>`**：顶部导航栏，至少 4 个锚点链接（Home / About / Projects / Contact）
- **`<section id="hero">`**：姓名、一句话简介、CTA 按钮
- **`<section id="about">`**：个人介绍 + 技能列表（至少 3 项技能）
- **`<section id="projects">`**：至少 3 个项目卡片（可用 `<article>` 或 `class="project"` / `class="card"`）
- **`<section id="contact">`**：联系邮箱或社交媒体链接

### 2. `styles.css`（必须满足）

- 使用 **CSS 变量** 管理颜色（如 `--primary-color`，并在某处使用 `var(--xxx)`）
- 包含至少 1 个 **响应式 `@media` 查询**
- hero 区有渐变背景（`linear-gradient` 或 `radial-gradient`）

### 3. `script.js`（必须实现）

- **平滑滚动**：点击导航链接，平滑跳转到对应 section（可用 `scrollIntoView({ behavior: 'smooth' })` 或等效实现）
- **控制台输出**：页面加载完成后 `console.log("Portfolio loaded")` 或类似消息

### 4. 链接关系

- `index.html` 必须通过 `<link rel="stylesheet" href="styles.css">` 引入 CSS
- `index.html` 必须通过 `<script src="script.js">` 引入 JS（可以放在 body 末尾）

## 验证步骤

1. 用 `python -m http.server 8000` 启动本地服务器
2. curl `http://localhost:8000/` 检查返回 200 + HTML 内容
3. 跑 `pytest` 验证所有结构测试通过

## 验收标准

- pytest 全部通过（`tests/` 下 3 个测试文件）
- 启动 HTTP 服务器后，浏览器能看到完整页面（Hero + 4 个 section + 响应式 + JS 交互）

## 提示

- 这是 Greenfield 任务，workspace 初始为空
- 建议先创建 `index.html` 骨架，再创建 `styles.css` 美化，最后创建 `script.js` 添加交互
- 不需要后端，纯粹的静态页面即可