# AGENTS.md

nfofetch: FastAPI + HTMX 影片刮削工具，生成 Jellyfin 兼容的 NFO/图片。

> **Before any task**: run `index_repository(repo_path, mode: "moderate")` to keep the knowledge graph in sync.

## 关键命令

```bash
uv sync                          # 修改 pyproject.toml 后
uv run ruff check --fix . && uv run ruff format . && uv run mypy app/ tests/ && uv run pytest
uv run uvicorn app.main:app --reload  # 开发服务器
```

## 硬约束

### FUSE（目标用户使用 rclone FUSE 挂载 115 网盘）

| 规则 | 原因 |
|------|------|
| fail-fast，绝不重试 | 重试增加 FUSE daemon 负载，导致断开更频繁；HTTP 请求可重试 1 次 |
| `Path.resolve()` 禁止，改用 `absolute()` | `resolve()` 触发网络 stat 慢（主要在 main.py browse/file 操作中） |
| 临时文件禁止写 FUSE 目录 | 必须用 `tempfile.NamedTemporaryFile(prefix="._nfofetch_")`（默认 `/tmp`） |
| 写入前停顿 `write_delay` 秒（默认 0.2s） | `shutil.move`/`rename`/`mkdir` 前插入；测试时置 0 |
| extrafanart 批量 move | 全部先下载到 `/tmp`，一次性 `shutil.move` 到 FUSE |
| ffprobe timeout=10s | 读网络大文件耗时久 |

### 配置系统

- **`Settings`**（`config.py`）：环境变量驱动，`frozen=True`，`@lru_cache` 缓存单例
- **`UserSettings`**（`schemas.py`）：UI 驱动，持久化到 JSON
- **合并**：`_merge_ui_settings()` 返回新实例，不修改缓存单例
- Cookie 字段名：`javdb_cookie` / `jav321_cookie` / `dmm_cookie`（环境变量 `NFOFETCH_DMM_COOKIE`）

### DMM 两个 Scraper（`app/scrapers/dmm.py`）

| Scraper | 域名 | 图片 URL |
|---------|------|---------|
| `DmmScraper` | `video.dmm.co.jp` | `awsimgsrc.dmm.co.jp/pics_dig/digital/video/{cid}/{cid}pl.jpg` |
| `DmmLegacyScraper` | `www.dmm.co.jp` | `pics.dmm.co.jp/mono/movie/{cid}/{cid}pl.jpg` |

- video.dmm.co.jp 是纯 CSR Next.js，必须用 Playwright 渲染 JS，全部走 `ThreadPoolExecutor(max_workers=1)`
- `get_enabled_scrapers()` 开启 `dmm` 时自动包含 `dmm_legacy`
- 旧站解析差异：`配信開始日` vs `貸出開始日`；分类用 `&nbsp;` 分割；评分 `平均評価\n 4.18`（无冒号）
- 旧站样本图：HTML 中 `-N.jpg` → `jp-N.jpg`；图片路径有 `/mono/movie/` 和 `/mono/movie/adult/` 两种
- 租赁 CID 后缀 `r`，样本图用 base CID（如 `118abp880` 而非 `118abp880r`）

### NFO

- **URL hash 存 NFO XML**（`<poster_url_hash>` / `<fanart_url_hash>` / `<art_url hash="...">`），不额外创建文件
- poster/fanart 固定文件名 `poster.jpg` / `fanart.jpg`；extrafanart 顺序命名 `01.jpg` `02.jpg`…
- **永不删除 extrafanart**，只补充新 URL
- **写入时机**：图片下载完成后，在 `_write_nfo_and_images` 中追加 hash 再写入；调用者传入的 `nfo_text` 不含 hash

### 前端约束

- **`escapejs` 在测试环境不可用**（`app/main.py` 注册的自定义过滤器），改用 `data-*` 属性传值
- **确认弹窗用按钮 click，不用 `htmx:beforeRequest`**：多个 `beforeRequest` handler 同时 `preventDefault()` 导致异步流程混乱
- 前端详细规范见 `.opencode/skills/frontend-style/SKILL.md`
