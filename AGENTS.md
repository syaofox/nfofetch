# AGENTS.md

nfofetch: FastAPI + HTMX 影片刮削工具，从 javdb 抓取信息并生成 Jellyfin 兼容的 NFO/图片。

## 重要事项
- 实际修改前，要先评估此次修改的合理性与可行性。
- 修改后的代码必须有完整的 pytest 单元测试，并通过 mypy 和 ruff 检测。
- 请使用提问的方式帮助我确认需求。
- 不要猜测我的意图。任何不明确的地方都必须向我提问。

## 关键命令

```bash
uv sync                          # 安装依赖（修改 pyproject.toml 后必跑）
uv lock                          # 更新 uv.lock（修改 pyproject.toml 后必跑，如版本号变更需提交 uv.lock）
uv run uvicorn app.main:app --reload  # 开发服务器
uv run python -m app.cli --url <URL> --video <PATH>  # CLI 模式
uv run ruff check --fix . && uv run ruff format . && uv run mypy app/ tests/ && uv run pytest   # 提交前必跑
uv run pytest tests/test_scrape_path_update.py -v   # 仅跑新增的路径更新测试
```

## FUSE / 网络文件系统踩坑记录

目标用户使用 fnos 挂载 115 网盘（rclone FUSE），以下坑已修：

| # | 问题 | 原因 | 解决方案 |
|---|------|------|----------|
| 1 | `fcntl.flock` 导致挂载 hang | 多数 FUSE 不支持 POSIX 文件锁 | `lock_utils.py`: 改用 `O_CREAT \| O_EXCL` 原子创建锁文件，60s 过期检测 |
| 2 | poster + fanart + extrafanart 并发写 FUSE 导致断开 | 4-6 路同时写入压垮 FUSE daemon | `file_service.py`: 新增 `NFOFETCH_SERIAL_WRITES=true`，所有图片串行写入 |
| 3 | ffprobe 读网络视频阻塞 30s | 大文件通过网络读取耗时久 | `rename_utils.py`: timeout 30s → 10s |
| 4 | 文件夹 rename 后立即写入图片 → mount 断开 | rename 在 FUSE 上需时间同步，后续写入加剧负载 | ~~`_settle_rename()`~~ → 最终结论：FUSE 重试弊大于利，已全部移除，改 fail-fast |
| 5 | 远程添加文件后 UI 文件浏览器看不到 | 内核 dcache + rclone 内部缓存导致 `scandir` 返回旧数据 | `app/main.py:170`: `scandir` 前加 `current.stat()` 尝试触发 getattr 刷新缓存; 也可在 fnos 侧设 `--dir-cache-timeout=30s` |

### 关键教训：FUSE 重试是反模式

最初我们给所有 FUSE 操作加了重试（`_rename_with_retry` / `_mkdir_with_retry` / `_move_with_retry` / `_settle_rename` / scandir retry loop / `retry_on_oserror`），结果**断开更频繁了**。

原因：FUSE daemon 已经过载时，重试只会增加负载，让它更难恢复。

最终策略（经过实际验证有效）：

| 操作 | 做法 | 原因 |
|---|---|---|
| `mkdir` | 直调，不重试 | 重试无意义 |
| `scandir` | 直调，不重试 | 失败就失败 |
| `rename` 文件/目录/字幕 | 直调 `Path.rename()` | 不重试 |
| `shutil.move` 从 `/tmp` 到 FUSE | 直调，不重试 | 不重试 |
| **HTTP 请求**（远程服务器） | `retry_request` 重试 1 次 | 429/5xx 可恢复 |
| **`stat` / `exists()`** 轻量检查 | 优先于全目录扫描 | 单个 stat 比 scandir 快得多 |

### FUSE 通讯量优化清单

从最初到最终，一次刮削从 ~90 次 FUSE 操作降至 ~20 次：

| 优化 | 效果 |
|---|---|
| ffprobe 按需执行（格式不用 `{resolution}`/`{vr}` 时跳过） | 省 1~4 次 ffprobe |
| 去掉所有 retry（rename/mkdir/move/scandir） | 每步省 66% 调用 |
| `stat` 判 NFO 存在代替全目录扫描（首次刮削） | 省 1 次 scandir |
| `existing_names` 参数传递避免重复扫描 | 省 1 次 scandir |
| extrafanart 批量 move（全部下载到 `/tmp` 再一次性 move 到 FUSE） | 减少 FUSE daemon 切换开销 |
| `_download_to_temp` / `_download_image` 分离 | 支持批量 move |
| `NFOFETCH_WRITE_DELAY=0.2` 每次写入前停顿 200ms | 给 FUSE daemon 喘息空间，缓解随机断开 |

### 写入停顿（`NFOFETCH_WRITE_DELAY`）

新增 `write_delay` 配置项（默认 0.2 秒），在每次 FUSE 文件写入（`shutil.move`、`rename`、`mkdir`）前插入 `time.sleep()`。

| 停顿位置 | 文件 | 效果 |
|---------|------|------|
| `_download_image` / `_download_image_with_crop` | `image_utils.py` | 每张图片 move 到 FUSE 前停顿 |
| `_atomic_write_text` | `file_utils.py` | NFO 写入前停顿 |
| extrafanart 批量 move 循环 | `file_service.py` | 每个 extrafanart 文件 move 前停顿 |
| poster→fanart 阶段之间 | `file_service.py` | 图片类型间停顿 |
| extrafanart→NFO 之间 | `file_service.py` | 图片全部完成 → NFO 写入前停顿 |
| rename 视频/目录后 | `file_service.py` | rename 后 → 下一个 FUSE 操作前停顿 |

测试默认 `write_delay=0` 避免减慢。用户可通过环境变量 `NFOFETCH_WRITE_DELAY=0.5` 或 UI 设置页调整。

## HTMX / 前端踩坑记录

### 坑 1：`htmx:afterRequest` 事件冒泡因 DOM 分离失效

| 问题 | 原因 | 解决方案 |
|------|------|----------|
| `htmx:afterRequest`/`afterSwap` 监听器不执行 | swap 后发起请求的元素（`elt`）被移出 DOM，事件无法冒泡到 `document.body` | **内联 `<script>`**：在返回的 HTML partial 中嵌入 `<script>`，HTMX 会在 swap 后自动执行 |

**错误做法：** 在 `base.html` 中靠 `document.body.addEventListener("htmx:afterRequest", ...)` 监听 `#write-form` 完成事件来更新 UI。

**正确做法：** 在 `scrape_result.html` 中直接输出 `<script>document.getElementById("video_path").value = "{{ path | escapejs | safe }}";</script>`。

### 坑 2：`<script>` 在 innerHTML swap 中不执行

HTML 规范规定 `innerHTML` 插入的 `<script>` 不执行。HTMX 内部会主动查找并执行它们，所以依赖 HTMX 的 script 执行没问题。但如果用原生 `fetch` + `innerHTML` 手动插入内容，需要自行处理脚本执行。

### `escapejs` 过滤器

在 `app/main.py` 中注册了自定义 Jinja2 过滤器 `escapejs`，用于安全地将 Python 字符串嵌入 JavaScript 字符串上下文（单/双引号、反斜杠、换行符均被转义）。用法：

```
{{ value | escapejs | safe }}
```

注意必须追加 `| safe`，否则 Jinja2 的 HTML 自动转义会破坏 JS 字符串。

## VR 格式判定

`{vr}` 占位符用于文件/目录重命名，根据视频分辨率判定格式：

| 条件 | 结果 | 含义 |
|---|---|---|
| `w > h`（宽>高） | `180_LR` | 左右格式（横屏/标准 SBS） |
| `w <= h`（宽≤高） | `360_TB` | 上下格式（竖屏/正方形均为 TB） |
| 无分辨率（ffprobe 失败） | `180_LR` | 兜底默认 |

- `_is_vr()` 检查番号、genres、tags 中是否含 `"VR"` 来判断是否为 VR 视频
- 文件重命名 `_format_rename` 和目录重命名 `_format_dir_rename` 使用相同的 VR 判定逻辑
- 目录重命名曾遗漏分辨率判断（始终输出 `180_LR`），已修复

## NFO 设计原则

- **URL hash 存 NFO，不额外创建文件**：`<poster_url_hash>` / `<fanart_url_hash>` /
  `<art_url hash="...">01.jpg</art_url>` 写在 `movie.nfo` 里。避免网盘同步工具上传/同步额外标记文件。
- **旧 NFO 兼容**：无 hash 元素的旧 NFO 会导致全量重下载，仅一次。
- **poster/fanart 文件名固定**：`poster.jpg`、`fanart.jpg`（Jellyfin 标准），不能改成 hash 文件名。
- **extrafanart 顺序命名**：`01.jpg`、`02.jpg`…，NFO 中存 hash→文件名映射用于去重。
- **永不删除 extrafanart**：已有文件保留，只补充新 URL。
- **NFO 写入时机**：图片下载完成后，在 `_write_nfo_and_images` 中解析 XML、追加 hash 元素、重新序列化写入。调用者传入的 `nfo_text` 不含 hash。

## 文件操作约定

- **临时文件放 `/tmp`**：`tempfile.NamedTemporaryFile(prefix="._nfofetch_")` + `shutil.move` 到目标目录，避免网盘同步工具上传扫描到半成品。
- **重复刮削检测**：NFO 中 `<source_url>` 或 `<id>` 匹配即有记录；若已有同源记录，仍然重新下载图片并更新 NFO hash。
- **目录锁默认关闭**：`NFOFETCH_LOCK_ENABLED=false`，单人使用不需锁。多用户 Web 场景需开启。可通过环境变量或 UI 设置页调整。
- **`Path.resolve()` 禁用**：FUSE 上 `resolve()` 触发网络 stat 慢，改用 `absolute()`。
- **文件浏览器记住的路径**：刮削完成后，服务端自动将 `last_browse_path` 更新为 `result.movie_dir`（`app/main.py:438`），同时内联 `<script>` 将 `#video_path` 输入框更新为新的视频路径（`scrape_result.html:147-156`）。下次打开文件浏览器时自动定位到新目录。

## 架构要点

- **入口**: `app/main.py`（FastAPI）、`app/cli.py`（CLI）
- **刮削器注册**: `app/scrapers/registry.py` — 新增站点注册到 `SCRAPERS` 列表
- **HTML 解析**: `selectolax`；**HTTP 客户端**: 优先 `curl-cffi`，兜底 `httpx`
- **配置**: `get_settings()` 由 `@lru_cache` 缓存，环境变量 → `Settings` dataclass。部分配置（cookie / serial_writes / lock_enabled / write_delay / max_extra_images）也可通过 UI 设置页调整，存储于 `UserSettings`（`schemas.py`），通过 `_merge_ui_settings()`（`app/main.py`）合并到 `Settings`，优先于环境变量。
- **用户偏好**: 重命名格式、最后浏览路径等持久化到 JSON（`settings_service.py`，默认 `~/.config/nfofetch/settings.json`），启动时加载

## 特殊约定

- 所有文件 `from __future__ import annotations`
- 类型 `str | None` 而非 `Optional[str]`
- 纯单元测试（`tests/`），pytest 管理，不依赖网络
- 依赖声明在 `pyproject.toml`，Dockerfile 使用 `uv sync --frozen` 基于 `uv.lock` 安装；更新依赖或版本号后务必提交 `uv.lock`
