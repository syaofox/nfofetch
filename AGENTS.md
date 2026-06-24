# AGENTS.md

nfofetch: FastAPI + HTMX 影片刮削工具，从多个站点抓取信息并生成 Jellyfin 兼容的 NFO/图片。

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

### 坑 3：`escapejs` 在测试环境的 Jinja2 中不可用

| 问题 | 原因 | 解决方案 |
|------|------|----------|
| 测试渲染模板时报 `No filter named 'escapejs'` | `escapejs` 只在 `app/main.py` 中注册，测试中创建的独立 `Jinja2Templates` 实例没有该过滤器 | 改用 `data-*` 属性传值代替 onclick 中内联 JS（如 `data-poster-url="{{ url }}"` → `onclick="fn(this)"` → JS 读 `getAttribute`） |

### 坑 4：`nfSaveSettings()` 读取 HTMX 动态渲染的元素

| 问题 | 原因 | 解决方案 |
|------|------|----------|
| 设置弹窗保存时，覆盖了用户其他偏好 | `nfSaveSettings()` 读取的某些 `id`（如 `#move_to_subdir`）只存在于 HTMX 动态加载的 partial 中，未加载时返回 `null`，代码发 `false` 覆盖了用户已有设置 | 对该类字段用 `?: undefined` 三元守卫：元素不存在时值为 `undefined`，`JSON.stringify` 自动跳过该字段，服务端 `exclude_unset=True` 保留原值 |

**正确做法：**
```javascript
move_to_subdir: document.getElementById("move_to_subdir")
  ? document.getElementById("move_to_subdir").checked
  : undefined,  // 元素不存在时不发送，避免覆盖已有设置
```

### 坑 5：多个 `htmx:beforeRequest` handler 同时 `preventDefault()` 导致遮罩残留

| 问题 | 原因 | 解决方案 |
|------|------|----------|
| 弹窗取消后加载遮罩仍显示（"正在准备中"） | `write-form` 有 3 个 `htmx:beforeRequest` handler（加载遮罩、任务ID注入、重命名确认），各 handler 独立调用 `preventDefault()` 并启动异步流程。任务ID注入的 handler 在异步回调中创建了轮询任务并 re-submit，此时重命名确认 handler 的 `preventDefault()` 使请求取消但轮询仍在运行，"正在准备中" 就是轮询写入的 | **确认/拦截逻辑不要放在 `htmx:beforeRequest` 中**，改为劫持按钮的 `click` 事件，检查通过后调用 `htmx.trigger(form, "submit")` 触发正常 HTMX 流程（加载遮罩、任务ID注入等由后续 handler 自动处理） |

**错误做法：** 在 `htmx:beforeRequest` 中 `preventDefault()` + 异步 fetch 做确认，然后手动 re-submit。

**正确做法：** 按钮改为 `type="button"` + `onclick`，点击 handler 中完成检查后手动触发提交：
```javascript
// onclick 中检查通过后
htmx.trigger(form, "submit");
// HTMX 自动接管后续：加载遮罩、任务ID注入、进度轮询等
```

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
- **重复刮削检测**：NFO 中 `<source_url>` 或 `<id>` 匹配即有记录；若已有同源记录，仍然重新下载图片并更新 NFO hash（委托 `_write_nfo_and_images` 统一处理，extrafanart 始终并行下载）。
- **目录锁默认关闭**：`NFOFETCH_LOCK_ENABLED=false`，单人使用不需锁。多用户 Web 场景需开启。可通过环境变量或 UI 设置页调整。
- **`Path.resolve()` 禁用**：FUSE 上 `resolve()` 触发网络 stat 慢，改用 `absolute()`。
- **自定义上传图片**：
  - `POST /api/upload-image` 接收文件 → 保存到系统 `/tmp`（`._nfofetch_upload_` 前缀）→ 返回 `{"path": "<本地路径>", "serve_url": "/api/uploaded-image?path=..."}`。支持 jpg/png/webp，限 20MB。写入后通过 `_cleanup_uploaded()` 自动清理。
  - 旧端点 `POST /api/upload-poster` 保留向后兼容，委托给 `upload-image`。
  - `custom_poster_path` / `custom_fanart_path` 覆盖 `poster_url` / `fanart_url`，`_download_to_temp` 检测到本地路径直接复制不走 HTTP。
  - 前端上传区显示在候选图片网格上方，支持点击选择/拖拽/Ctrl+V 三种上传方式。上传后自动加入候选网格，用户通过 radio 选择角色（poster/fanart）。
  - 写入成功后通过 `_cleanup_uploaded()` 自动删除 `/tmp` 中的上传文件。
- **文件浏览器记住的路径**：刮削完成后，服务端自动将 `last_browse_path` 更新为 `result.movie_dir`（`app/main.py:438`），同时内联 `<script>` 将 `#video_path` 输入框更新为新的视频路径（`scrape_result.html:147-156`）。下次打开文件浏览器时自动定位到新目录。
- **move_to_subdir**：写入后自动将视频移动到子目录。执行顺序：`move_to_subdir` → `rename_format` → `rename_dir`（仅未启用 move_to_subdir 时执行）。子目录名复用 `rename_dir` 格式（空则 `{id}`）。分集检测 `_is_split_base()` 识别 `-CD1`/`-part1`/`_1` 等后缀。设置持久化到 `UserSettings`，通过 checkbox `change` 事件和 `htmx:beforeRequest` 双重自动保存。
- **重命名文件数预览**（`POST /api/rename-preview`）：接受 `video_path`/`rename_format`/`move_to_subdir`，返回 `{count: N}`。按钮点击先调此接口检查，`count > 3` 时弹出确认弹窗。关键逻辑：
  - `rename_format` 为空 → count=0
  - 不含 `{idx}` → count=1（仅选中文件）
  - 含 `{idx}` 且 `move_to_subdir=false` → 扫描目录内所有视频
  - 含 `{idx}` 且 `move_to_subdir=true` → 用 `_strip_split_suffix` 提取基名，`_count_split_group` 只统计同基名文件（含 `-CD1`/`_part2`/`_1` 等），**不统计移入子目录后目录内其他视频**

## 架构要点

- **入口**: `app/main.py`（FastAPI）、`app/cli.py`（CLI）
- **刮削器注册**: `app/scrapers/registry.py` — 新增站点注册到 `SCRAPERS` 列表
- **HTML 解析**: `selectolax`；**HTTP 客户端**: 优先 `curl-cffi`，兜底 `httpx`
- **配置**: `get_settings()` 由 `@lru_cache` 缓存，环境变量 → `Settings` dataclass（`frozen=True`，不可变）。部分配置（cookie / serial_writes / lock_enabled / write_delay / max_extra_images / delete_orphan_extrafanart / filter_actor_gender / download_concurrency / auto_trim_white_borders / enabled_scrapers）也可通过 UI 设置页调整，存储于 `UserSettings`（`schemas.py`），通过 `_merge_ui_settings()`（`app/main.py`）合并后**返回新 `Settings` 实例**，不修改缓存单例，保证线程安全。
- **用户偏好**: 重命名格式、最后浏览路径等持久化到 JSON（`settings_service.py`，默认 `~/.config/nfofetch/settings.json`），启动时加载
- **注意区分 Settings 和 UserSettings**：`Settings`（`config.py`）由环境变量驱动，`UserSettings`（`schemas.py`）由 UI 操作驱动。部分字段（`serial_writes`/`lock_enabled`/`write_delay` 等）通过 `_merge_ui_settings()` 合并到 `Settings` 中统一使用；另一些字段（如 `move_to_subdir`/`rename_format`/`rename_dir`/`last_browse_path`）仅由表单直接传递或 UI 自行读写，不进入 `Settings`。
- **重名前确认**：`rename_utils.py` 新增 `_count_files_to_rename` / `_count_split_group` / `_strip_split_suffix`，`main.py` 新增 `POST /api/rename-preview` 供前端写入前预览计数。详见「文件操作约定」。

## 特殊约定

- 所有文件 `from __future__ import annotations`
- 类型 `str | None` 而非 `Optional[str]`
- 纯单元测试（`tests/`），pytest 管理，不依赖网络
- 依赖声明在 `pyproject.toml`，Dockerfile 使用 `uv sync --frozen` 基于 `uv.lock` 安装；更新依赖或版本号后务必提交 `uv.lock`
- 版本号 `VERSION` 在 `app/main.py` 启动时从 `pyproject.toml` 读取（`PROJECT_ROOT / "pyproject.toml"`），**Dockerfile 运行阶段必须拷贝 `pyproject.toml`**，否则 UI 右下角显示 `v0.0.0`
