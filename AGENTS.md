# AGENTS.md

nfofetch: FastAPI + HTMX 影片刮削工具，从 javdb 抓取信息并生成 Jellyfin 兼容的 NFO/图片。

## 关键命令

```bash
uv sync                          # 安装依赖
uv run uvicorn app.main:app --reload  # 开发服务器
uv run python -m app.cli --url <URL> --video <PATH>  # CLI 模式
uv run ruff check --fix . && uv run ruff format . && uv run mypy app/ tests/ && uv run pytest   # 提交前必跑
```

## FUSE / 网络文件系统踩坑记录

目标用户使用 fnos 挂载 115 网盘（rclone FUSE），以下坑已修：

| # | 问题 | 原因 | 解决方案 |
|---|------|------|----------|
| 1 | `fcntl.flock` 导致挂载 hang | 多数 FUSE 不支持 POSIX 文件锁 | `lock_utils.py`: 改用 `O_CREAT \| O_EXCL` 原子创建锁文件，60s 过期检测 |
| 2 | poster + fanart + extrafanart 并发写 FUSE 导致断开 | 4-6 路同时写入压垮 FUSE daemon | `file_service.py`: 新增 `NFOFETCH_SERIAL_WRITES=true`，所有图片串行写入 |
| 3 | 文件夹 rename 后立即写入图片 → mount 断开 | rename 在 FUSE 上需时间同步，后续写入加剧负载 | `file_service.py`: rename 后 `_settle_rename()` stat 验证 + sleep 2s |
| 4 | `shutil.move` 从 `/tmp` 到 FUSE 失败 | 网络闪断导致 EIO/ESTALE | `image_utils.py`: `_move_with_retry()` 遇到重试 errno 自动重试 |
| 5 | `os.scandir` 网络抖动失败 | FUSE 短暂断开 | `file_service.py`: `_scan_dir_names_impl` 加 `@retry_on_oserror` |
| 6 | ffprobe 读网络视频阻塞 30s | 大文件通过网络读取耗时久 | `rename_utils.py`: timeout 30s → 10s |
| 7 | `mkdir` 在 FUSE 上失败 | 网络闪断导致 EIO | `file_utils.py`: `_mkdir_with_retry()` 重试 2 次，支持 `parents=True` |
| 8 | `Path.rename` 文件/目录失败 | FUSE 网络闪断导致 EIO/ESTALE | `file_utils.py`: `_rename_with_retry()` 重试 2 次，覆盖文件、目录、字幕三类 rename |

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
- **目录锁默认关闭**：`NFOFETCH_LOCK_ENABLED=false`，单人使用不需锁。多用户 Web 场景需开启。
- **`Path.resolve()` 禁用**：FUSE 上 `resolve()` 触发网络 stat 慢，改用 `absolute()`。

## 架构要点

- **入口**: `app/main.py` (FastAPI), `app/cli.py` (CLI)
- **刮削器注册**: `app/scrapers/registry.py` — 新增站点注册到 `SCRAPERS` 列表
- **HTML 解析**: `selectolax`；**HTTP 客户端**: 优先 `curl-cffi`，兜底 `httpx`
- **配置**: `get_settings()` 由 `@lru_cache` 缓存，环境变量 → `Settings` dataclass
- **用户偏好**: 重命名格式等持久化到 JSON（`settings_service.py`），启动时加载

## 特殊约定

- 所有文件 `from __future__ import annotations`
- 类型 `str | None` 而非 `Optional[str]`
- 纯单元测试 (`tests/`)，pytest 管理，不依赖网络
- 依赖声明在 `pyproject.toml`，Dockerfile 重复列了 `pip install` 行，新增需同步
