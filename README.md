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

### 使用流程

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

> 当前实现基于 javdb 页面的一般结构做了解析，若站点结构调整导致字段抓取不完整，可根据实际 HTML 调整 `app/scrapers/javdb.py` 中的 CSS 选择器。

