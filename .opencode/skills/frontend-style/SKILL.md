---
name: frontend-style
description: nfofetch 前端风格规范。新增或修改页面/组件时遵循此 skill。
---

## CSS 命名规范

- 所有 class 以 `nf-` 前缀开头（`nf-card`、`nf-button`、`nf-input`）
- 状态变体以 `-` 连接后缀：`nf-alert-error`、`nf-button-secondary`、`nf-sort-btn-active`
- 子元素用完整单词连接：`nf-file-browser-title`、`nf-image-option-controls`、`nf-meta-poster-img`
- 禁止 BEM 双连字符（`nf-card__title`），禁止嵌套选择器，禁止 CSS Modules

## 颜色体系

| 用途 | 色值 | Token |
|------|------|-------|
| Header/Footer 背景 | `#111827` | — |
| Header 文字 | `#e5e7eb` | — |
| 页面背景 | `#f3f4f6` | `.nf-main` |
| 卡片背景 | `#ffffff` | `.nf-card` |
| 主色/链接/焦点色 | `#2563eb` | blue-600 |
| 次要文字 | `#6b7280` | gray-500 |
| 正文 | `#111827` / `#374151` | gray-900 / gray-700 |
| 成功 | `#22c55e` / `#059669` | green-500 / green-600 |
| 错误 | `#dc2626` / `#ef4444` | red-600 / red-500 |
| 边框/分割线 | `#e5e7eb` / `#d1d5db` | gray-200 / gray-300 |

参见 `app/static/css/style.css:1-7`（容器）、`:48-57`（主色布局）、`:201-216`（错误色）。

## 布局组件

- **容器**：`.nf-container`（max-width: 960px, 居中），所有内容放里面
- **卡片**：`.nf-card`（白色圆角卡片，1.5rem padding，0.75rem border-radius，hover 上移 1px）
- **按钮**：`.nf-button`（圆角 999px，蓝渐变背景，白字），变体有 `-secondary`（灰底）、`-danger`（红底）、`-ghost`（透明）
- **输入框**：`.nf-input`（圆角 0.5rem，focus 时 blue-600 边框+阴影）
- 按钮+输入框组合：`.nf-input-with-button`（flex row + gap）

## 组件模式

### 表单组
```html
<div class="nf-form-group">
  <label class="nf-label">标题</label>
  <input class="nf-input" />
  <p class="nf-hint">帮助文字</p>
</div>
```
- `.nf-form`：父级 flex column gap 1rem
- `.nf-inline-fields`：水平排列的小字段组（flex wrap gap 1rem align-items end）
- `.nf-label-inline`：内联字段的小标签（0.8rem，灰色）

### 模态框
- 容器：`.nf-modal`（fixed 全屏，z-index 9998，flex 居中）
- 遮罩：`.nf-modal-backdrop`（absolute 全屏，黑色半透明）
- 盒子：`.nf-modal-box`（白色圆角，max-width 420px，入口动画 `nf-modal-in`）
- 标题/正文/操作区：`.nf-modal-title` / `.nf-modal-body` / `.nf-modal-actions`

### 开关组件
```html
<label class="nf-toggle">
  <input type="checkbox" class="nf-toggle-input" />
  <span class="nf-toggle-track"><span class="nf-toggle-knob"></span></span>
  <span class="nf-toggle-label">标签</span>
</label>
```
input opacity 0，track 用 checked 状态切换背景色，knob 用 cubic-bezier 动画滑移。

### 自定义 radio
```html
<label class="nf-radio-custom">
  <input type="radio" name="x" value="y" />
  <span>文字</span>
</label>
```
input `appearance: none` 自绘圆点，checked 时 5px border 实心。

### 图片选择网格
```html
<div class="nf-image-grid">
  <div class="nf-image-option">
    <img class="nf-image-thumb" />
    <div class="nf-image-option-controls">
      <label class="nf-img-pill">
        <input type="radio" name="poster_url" hidden />
        <span class="nf-img-pill-text">poster</span>
      </label>
    </div>
  </div>
</div>
```
- 网格：`grid-template-columns: repeat(auto-fill, minmax(140px, 1fr))`，md 断点变 160px
- pill：圆角标签（999px），半透明底，checked 时 blue-600 背景

## 微交互规范

- 按钮 hover：`filter: brightness(1.05~1.1)`（而非改变背景色）
- 按钮 active：`transform: scale(0.97)`（`.nf-btn-press`）
- ripple 效果：`.nf-btn-ripple` — `::after` 伪元素 400px 扩散动画
- 卡片 hover：`translateY(-1px)` + 加强 shadow
- 文件项 hover：`translateX(2px)` + `background: #eff6ff`
- 所有动画使用 `cubic-bezier(0.34, 1.56, 0.64, 1)`（弹性）或 `ease`

## Jinja2 模板规范

- 继承 `base.html`，使用 `{% block content %}`
- 变量：`{{ var }}`，过滤器：`{{ var | filter }}`
- 内联 `<script>` 用于 HTMX partial 的 DOM 操作（`app/templates/partials/scrape_result.html:151-158`）
- 自定义 `escapejs` 过滤器需追加 `| safe`（`app/main.py` 注册）
- 隐藏输入存元数据 `{% if condition %}<input type="hidden" name="x" value="{{ v }}" />{% endif %}`

## JavaScript 规范

- 全局函数以 `nf` 前缀开头（`nfOpenFileBrowser`、`nfBrowseTo`、`nfSelectFile`）
- HTMX 事件监听使用 `document.addEventListener` 挂靠到 body 级别（base.html:149-174）
- 避免 jQuery，使用原生 DOM API（`document.getElementById`、`querySelector`）
- IIFE 封装状态型逻辑（base.html:177、258、719、829）
- 变量名使用 `camelCase`，常量 WFT：`ALL_CAPS`

## HTMX 用法

- `hx-post` / `hx-target="#result"` / `hx-swap="innerHTML"` 标准模式
- 加载遮罩通过监听 `htmx:beforeRequest` / `htmx:afterRequest` 控制
- 进度轮询：拦截 `write-form` 提交，先 POST 创建任务，再轮询 `/api/scrape-task/{id}`
- **确认弹窗不可放在 `htmx:beforeRequest` 中**：多个 handler 同时 `preventDefault()` 会导致异步流程混乱（遮罩/轮询残留）。改为 `<button type="button" onclick="window.nfFn(event)">` 劫持点击，检查通过后 `htmx.trigger(form, "submit")` 触发正常 HTMX 流程

## 文件位置

| 文件 | 内容 |
|------|------|
| `app/static/css/style.css` | 全部样式（单文件，1283 行） |
| `app/templates/base.html` | HTML 骨架、全局 JS（加载遮罩、模态框、文件浏览器、设置） |
| `app/templates/index.html` | 首页（搜索表单、设置模态框） |
| `app/templates/partials/*.html` | HTMX partial：搜索结果、图片选择、文件浏览器、刮削结果 |

## 原则

- 保持单文件 CSS，不引入预处理器/原子化框架
- 保持 vanilla JS，不引入前端框架
- HTMX partial 返回纯 HTML 片段，不返回 JSON
- 所有文字使用中文，保持统一风格
