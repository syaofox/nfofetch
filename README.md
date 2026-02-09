## nfofetch

基于 **FastAPI + HTMX** 的影片刮削小工具，目前支持从 **javdb** 抓取影片信息，并生成适用于 **Jellyfin** 的 `movie.nfo`、`poster.jpg`、`fanart.jpg`、`extrafanart/*` 等文件（推荐「一片一文件夹」结构）。

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

- 在首页输入 javdb 影片页面 URL（例如 `https://javdb.com/v/82ebmO`）。
- 选择本地的视频文件。
- 提交后后台会：
  - 抓取 javdb 页面信息，生成统一的影片元数据。
  - 生成 Jellyfin 兼容的 `movie.nfo`。
  - 下载封面 / 背景图 / 剧照到目标目录。
  - 将上传的视频文件保存到同一影片文件夹（文件名会根据番号 + 标题自动生成，可在 `app/services/file_service.py` 中调整逻辑）。

默认输出根目录为项目运行目录下的 `output/`，可通过环境变量修改：

```bash
export NFOFETCH_OUTPUT_ROOT=/path/to/your/library
```

如需使用代理访问 javdb，可以设置：

```bash
export NFOFETCH_HTTP_PROXY=http://127.0.0.1:7890
```

如需只生成 NFO / 图片而**不复制上传的视频文件**，可以设置：

```bash
export NFOFETCH_SKIP_VIDEO_COPY=true
```

此时仍会根据番号 + 标题计算出目标视频文件名路径，但不会在输出目录写入视频文件。

### 命令行模式：针对已有视频文件

除了 Web 界面外，还提供一个命令行入口，方便对硬盘上已存在的视频直接生成 NFO 和图片（不会复制/移动视频）。

示例：

```bash
uv run python -m app.cli \
  --url "https://javdb.com/v/82ebmO" \
  --video "/path/to/your/movie.mp4"
```

行为说明：

- 根据 `--url` 解析 javdb 页面；
- 在 `--video` 所在目录下生成：
  - `movie.nfo`
  - `poster.jpg`
  - `fanart.jpg`
  - `extrafanart/*`
- 原视频文件保持不变，仅在旁边多出 NFO 与图片资源。

### Cookie 管理

访问 javdb 时通常需要带上浏览器里的 Cookie（含 `cf_clearance` 等），本项目支持两种配置方式：

- **环境变量（全局优先级最高）**：

  ```bash
  export NFOFETCH_JAVDB_COOKIE='在浏览器中复制的完整 Cookie 串'
  ```

- **站点预设 Cookie（模块配置）**：

  编辑 `app/cookie_store.py`，在 `SITE_COOKIES` 中按站点名或域名填入预设值，例如：

  ```python
  SITE_COOKIES = {
      "javdb": "theme=auto; locale=zh; over18=1; ...",
      # "javdb565.com": "..."
  }
  ```

Cookie 优先级为：

1. 环境变量 `NFOFETCH_JAVDB_COOKIE`
2. `SITE_COOKIES` 中按域名 / 站点匹配到的预设 Cookie

命令行模式和 Web 模式共用同一套配置逻辑。

> 当前实现基于 javdb 页面的一般结构做了解析，若站点结构调整导致字段抓取不完整，可根据实际 HTML 调整 `app/scrapers/javdb.py` 中的 CSS 选择器。

