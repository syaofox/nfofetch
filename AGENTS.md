# AGENTS.md

nfofetch: FastAPI + HTMX 影片刮削工具，生成 Jellyfin 兼容的 NFO/图片。

## 重要事项
- 修改前先评估合理性与可行性。
- Python 代码必须有完整 pytest 单元测试，通过 mypy + ruff。
- 不明确的地方先提问，不要猜测意图。
- 修改后评估 AGENTS.md 和 `.opencode/skills/` 是否需要更新。

## 关键命令

```bash
uv sync                          # 修改 pyproject.toml 后
uv run ruff check --fix . && uv run ruff format . && uv run mypy app/ tests/ && uv run pytest   # 提交前必跑
uv run uvicorn app.main:app --reload  # 开发服务器
```

## 易错点速查

### FUSE 规则（目标用户使用 rclone FUSE 挂载 115 网盘）

| 规则 | 说明 |
|------|------|
| **FUSE 操作 fail-fast，绝不重试** | 重试增加过载 FUSE daemon 负载，导致断开更频繁。HTTP 请求可重试 1 次 |
| **`Path.resolve()` 禁止使用** | 触发网络 stat 慢，改用 `absolute()` |
| **`stat` / `exists()` 优先于 `scandir`** | 单个 stat 比全目录扫描快得多 |
| **绝不往 FUSE 目录写临时文件** | 即使用例在 FUSE 上，临时文件也必须放 `/tmp`。任何 `tempfile.NamedTemporaryFile(dir=...)` 如果 dir 是 FUSE 路径，都改成不加 dir（默认 `/tmp`） |
| **写入前停顿 `write_delay` 秒** | 默认 0.2s，`shutil.move`/`rename`/`mkdir` 前插入，测试时置 0 |
| **extrafanart 批量 move** | 全部下载到 `/tmp`，一次性 `shutil.move` 到 FUSE |
| **scandir 前执行 `current.stat()`** | 触发 FUSE getattr 刷新缓存 |
| **ffprobe timeout=10s** | 读网络大文件耗时久，不要用默认 30s |

### HTMX 前端规则

| 规则 | 说明 |
|------|------|
| **内联 `<script>` in partial** | HTMX swap 后自动执行，不要依赖 `document.body.addEventListener` |
| **`escapejs` + `| safe`** | JS 字符串嵌入必须同时使用（缺少 `| safe` 会被 HTML 转义破坏） |
| **`?: undefined` 守卫** | 读取 HTMX 动态渲染的元素时，不存在则 `undefined`，避免覆盖已有设置 |
| **确认弹窗用按钮 click，不用 `beforeRequest`** | 多个 `beforeRequest` handler 同时 `preventDefault()` 导致异步流程混乱 |
| **`escapejs` 在测试中不可用** | 测试环境没有该过滤器，改用 `data-*` 属性传值 |

### 代码风格

- `from __future__ import annotations`
- `str | None` 而非 `Optional[str]`
- HTML 解析用 `selectolax`，HTTP 优先 `curl-cffi`，兜底 `httpx`
- 纯单元测试（`tests/`），不依赖网络

### 配置系统

- **`Settings`**（`config.py`）: 环境变量驱动，`frozen=True`，`@lru_cache` 缓存
- **`UserSettings`**（`schemas.py`）: UI 驱动，持久化到 JSON
- 合并：`_merge_ui_settings()` 返回**新实例**，不修改缓存单例，保证线程安全
- UI 可覆盖的字段：`cookie / serial_writes / lock_enabled / write_delay / max_extra_images / delete_orphan_extrafanart / filter_actor_gender / download_concurrency / auto_trim_white_borders / enabled_scrapers`
- 另一些字段仅表单传递：`move_to_subdir / rename_format / rename_dir / last_browse_path`

### NFO

- **URL hash 存 NFO XML**：`<poster_url_hash>` / `<fanart_url_hash>` / `<art_url hash="...">01.jpg`，不额外创建文件
- **poster/fanart 文件名固定**：`poster.jpg` / `fanart.jpg`
- **extrafanart 顺序命名**：`01.jpg` `02.jpg`…，NFO 中存 hash→文件名映射
- **永不删除 extrafanart**，只补充新 URL
- **NFO 写入时机**：图片下载完成后，在 `_write_nfo_and_images` 中追加 hash 再写入。调用者传入的 `nfo_text` 不含 hash

### 文件操作

- 临时文件统一放 `/tmp`（`tempfile.NamedTemporaryFile(prefix="._nfofetch_")`）
- 上传图片也放 `/tmp`（`._nfofetch_upload_` 前缀），预览通过 `/api/uploaded-image?path=...`
- 写入成功后 `_cleanup_uploaded()` 自动删除
- `Path.resolve()` → `absolute()`
- 目录锁默认关闭（`NFOFETCH_LOCK_ENABLED=false`）
- 版本号从 `pyproject.toml` 读取，**Dockerfile 运行阶段必须拷贝 `pyproject.toml`**
