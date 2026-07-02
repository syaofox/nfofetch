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
| **精确裁切上传 canvas Blob** | `nfConfirmCrop` 通过 `getCroppedCanvas().toBlob()` 上传裁切结果到 `/api/upload-image`，不走坐标传后端；方向裁切仍用 `crop_direction` 后端处理 |

### 代码风格

- `from __future__ import annotations`
- `str | None` 而非 `Optional[str]`
- HTML 解析用 `selectolax`，HTTP 优先 `curl-cffi`，兜底 `httpx`
- CSR 站点（如 DMM）用 Playwright 渲染 JS，`ThreadPoolExecutor` 规避 asyncio 冲突
- Playwright 安装：`uv run playwright install chromium`
- 纯单元测试（`tests/`），不依赖网络

### Playwright 通用规则

| 规则 | 说明 |
|------|------|
| **浏览器进程复用** | 模块级 `_get_browser()` 懒启动单例，`atexit` 清理，避免反复启停 |
| **全部走同一线程** | Playwright Sync API 绑定创建线程，必须统一走 `ThreadPoolExecutor`（`max_workers=1`） |
| **`_fetch_page()` 公共函数** | 共用 `_get_browser()` 和线程池，不同 scraper 无需重复实现 |
| **搜索页不等关键标签** | 仅内容页（`/content/`、`/detail/`）等 `配信開始日`，搜索页只 `wait_for_timeout(2000)` |
| **content 对象用完关闭** | 每个请求新建 `context`，`finally` 中 `context.close()` |

### 配置系统

- **`Settings`**（`config.py`）: 环境变量驱动，`frozen=True`，`@lru_cache` 缓存
- **`UserSettings`**（`schemas.py`）: UI 驱动，持久化到 JSON
- 合并：`_merge_ui_settings()` 返回**新实例**，不修改缓存单例，保证线程安全
- UI 可覆盖的字段：`cookie / serial_writes / lock_enabled / write_delay / max_extra_images / delete_orphan_extrafanart / filter_actor_gender / download_concurrency / auto_trim_white_borders / enabled_scrapers`
- DMM Cookie 字段名：`dmm_cookie`（环境变量 `NFOFETCH_DMM_COOKIE`）
- 另一些字段仅表单传递：`move_to_subdir / rename_format / rename_dir / last_browse_path`
- **DMM (video.dmm.co.jp)**：纯 CSR Next.js 站点，服务器 HTML 不含数据，必须用 Playwright 渲染 JS。解析策略基于页面文本标签（`配信開始日`、`収録時間` 等），不依赖 CSS 选择器
- DMM 图片 URL 前缀 `awsimgsrc.dmm.co.jp/pics_dig/`，保持此域名在图片下载白名单中

### DMM 架构说明（两个 Scraper）

| Scraper | 匹配域名 | 用途 | 图片路径 |
|---------|---------|------|---------|
| `DmmScraper` | `video.dmm.co.jp` | 新站数字视频详情页 | `awsimgsrc.dmm.co.jp/pics_dig/digital/video/{cid}/{cid}pl.jpg` |
| `DmmLegacyScraper` | `www.dmm.co.jp` | 旧站 DVD/租赁/DOD 页 | `pics.dmm.co.jp/mono/movie/{cid}/{cid}pl.jpg` |

`get_enabled_scrapers()` 开启 `dmm` 时自动包含 `dmm_legacy`（`registry.py` 中处理）。

### DMM 解析注意事项

- **旧站标签同号不同格式**：`配信開始日` vs `貸出開始日`，`メーカー品番` vs `品番`
- **旧站分类用 `&nbsp;` 分割**：`_parse_genres` 按 `&nbsp;` 切分
- **旧站演员正则**：lookahead 需 `\n\s*[^\s\n]+[：:]` 支持标签前的空格
- **旧站评分**：在用户评论区，格式 `平均評価\n 4.18`（无冒号）
- **旧站样本图**：HTML 中是 `-N.jpg`（小图），需转为 `jp-N.jpg`（大图）
- **旧站剧情**：截取 `平均評価` 后到 `サンプル画像`/`★` 之间的文本
- **旧站图片路径**：有 `/mono/movie/{cid}/` 和 `/mono/movie/adult/{cid}/` 两种
- **租赁 CID 后缀 `r`**：样本图用 base CID（如 `118abp880` 而非 `118abp880r`）
- **搜索结果保留原始 URL**：不转 CID，由 `get_scraper()` 自动分派到对应解析器

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
