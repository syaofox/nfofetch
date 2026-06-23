## nfofetch

基于 **FastAPI + HTMX** 的影片刮削小工具，支持从多个站点抓取影片信息，并生成适用于 **Jellyfin** 的 `movie.nfo`、`poster.jpg`、`fanart.jpg`、`extrafanart/*` 等文件（推荐「一片一文件夹」结构）。

### 环境与依赖（uv）

1. 安装 `uv`（如已安装可跳过）：

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
```

2. 在项目根目录安装依赖：

```bash
cd /mnt/github/nfofetch
uv sync
```

3. 启动开发服务器：

```bash
uv run uvicorn app.main:app --reload
```

启动后在浏览器访问 `http://127.0.0.1:8000/`。

### Web 使用流程

- 在首页输入影片页面 URL（例如站点详情页链接）。
- 填写**服务器本地视频文件路径**（例如 `/mnt/media/movies/IPVR-335.mp4`），或者点击「浏览…」按钮从服务器文件系统中选择文件：
  - 浏览范围默认限制在 `NFOFETCH_BROWSE_ROOT` 指定的目录（未设置时为服务启动时的当前工作目录）。
  - 只会在服务器端读取路径，不会上传或复制视频本身。
- （可选）等待图片候选加载后，在表单中选择哪一张作为 `poster.jpg`、哪一张作为 `fanart.jpg`。
- 提交后后台会：
  - 抓取站点页面信息，生成统一的影片元数据。
  - 生成 Jellyfin 兼容的 `movie.nfo`。
- 下载封面 / 背景图 / 剧照到该视频所在目录（`poster.jpg`、`fanart.jpg`、`extrafanart/*`），并在界面中预览你所选择的封面。
- **不会复制/移动原始视频文件**，仅在原目录旁生成 NFO 与图片资源。

文件浏览器的根目录可通过环境变量指定（默认等于当前工作目录）：

```bash
export NFOFETCH_BROWSE_ROOT=/mnt/media
```

如需使用代理访问站点，可以设置：

```bash
export NFOFETCH_HTTP_PROXY=http://127.0.0.1:7890
```

### 命令行模式：针对已有视频文件

除了 Web 界面外，还提供一个命令行入口，方便对硬盘上已存在的视频直接生成 NFO 和图片（不会复制/移动视频）。

示例：

```bash
uv run python -m app.cli \
  --url "https://example.com/v/xxx" \
  --video "/path/to/your/movie.mp4"
```

行为说明：

- 根据 `--url` 解析站点页面；
- 在 `--video` 所在目录下生成：
  - `movie.nfo`
  - `poster.jpg`
  - `fanart.jpg`
  - `extrafanart/*`
- 原视频文件保持不变，仅在旁边多出 NFO 与图片资源。

### Cookie 管理

部分站点需要带上浏览器里的 Cookie（含 `cf_clearance` 等），通过环境变量配置：

```bash
export NFOFETCH_JAVDB_COOKIE='在浏览器中复制的完整 Cookie 串'
```

Web 模式和命令行模式共用这一配置。

> 刮削器位于 `app/scrapers/` 目录下，每个站点对应一个文件。站点结构变化导致字段抓取不完整时，可根据实际 HTML 调整对应的 CSS 选择器。

### 使用 Docker / docker-compose 运行

本仓库提供了生产环境可用的 `Dockerfile` 与 `docker-compose.yml`。

1. **准备 `.env`（可选但推荐）**

   在项目根目录复制示例文件并填入真实 Cookie：

   ```bash
   cp .env.example .env
   # 然后编辑 .env，设置 NFOFETCH_JAVDB_COOKIE 为浏览器中复制的完整 Cookie 串
   ```

2. **根据自己的媒体库路径修改卷挂载**

   编辑 `docker-compose.yml` 中的卷，将宿主机路径替换为你自己的路径：

   ```yaml
   services:
     nfofetch:
       volumes:
         - /mnt/dnas:/data/media       # 媒体库所在目录（NFO 与图片也会生成在此目录内）
   ```

   NFO 及图片总是生成在你选择的视频文件所在目录中。
3. **构建并启动**

   ```bash
   docker compose up -d --build
   ```

   默认会监听 `8000` 端口，对应浏览器访问地址为 `http://127.0.0.1:8000/`。

### 环境变量参考

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `NFOFETCH_BROWSE_ROOT` | 当前工作目录 | Web 文件浏览器的根目录 |
| `NFOFETCH_SETTINGS_PATH` | `~/.config/nfofetch/settings.json` | 用户设置持久化路径 |
| `NFOFETCH_USER_AGENT` | Mozilla/5.0 ... Firefox/117.0 | 自定义 HTTP User-Agent |
| `NFOFETCH_HTTP_PROXY` | 无 | HTTP 代理地址 |
| `NFOFETCH_JAVDB_COOKIE` | 无 | JavDB 站点 Cookie |
| `NFOFETCH_JAV321_COOKIE` | 无 | Jav321 站点 Cookie |
| `NFOFETCH_JAVDB_MIRROR` | `javdb565.com` | JavDB 镜像域名 |
| `NFOFETCH_MAX_EXTRA_IMAGES` | `8` | extrafanart 最大保存数量，0 禁用 |
| `NFOFETCH_HTTP_TIMEOUT` | `20` | 单个 HTTP 请求超时（秒） |
| `NFOFETCH_BATCH_TIMEOUT` | `120` | extrafanart 批量下载总超时（秒） |
| `NFOFETCH_SERIAL_WRITES` | `false` | 串行写入图片（FUSE 场景） |
| `NFOFETCH_LOCK_ENABLED` | `false` | 启用目录锁（多用户场景） |
| `NFOFETCH_WRITE_DELAY` | `0.2` | 每次写入前停顿（秒），0 关闭 |
| `NFOFETCH_DELETE_ORPHAN_EXTRAFANART` | `false` | 重新刮削时删除孤立剧照 |
| `NFOFETCH_FILTER_ACTOR_GENDER` | `true` | `{actor}` 仅包含女演员 |
| `NFOFETCH_DOWNLOAD_CONCURRENCY` | `4` | extrafanart 下载并发数 |
| `NFOFETCH_AUTO_TRIM_WHITE_BORDERS` | `false` | 封面裁切前自动去白边 |
| `NFOFETCH_ENABLED_SCRAPERS` | 全部启用 | 启用的刮削站点列表，逗号分隔 |
| `NFOFETCH_LOG_LEVEL` | `WARNING` | 日志等级（DEBUG/INFO/WARNING/ERROR） |

