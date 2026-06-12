# AGENTS.md

nfofetch: FastAPI + HTMX 影片刮削工具，从 javdb 抓取信息并生成 Jellyfin 兼容的 NFO/图片。

## 工作方式

遇到多步骤任务时，**主 agent 只负责拆解和协调**，把可并行的子任务（如同时搜索多个文件、同时处理多个模块）分配给子 agent 并行执行。各子 agent 完成后由主 agent 汇总、验证、提交。

## 关键命令

```bash
uv sync                          # 安装依赖
uv run uvicorn app.main:app --reload  # 开发服务器 (http://127.0.0.1:8000)
uv run python -m app.cli --url <URL> --video <PATH>  # CLI 模式
uv run ruff check --fix . && uv run ruff format . && uv run mypy app/ && uv run pytest   # 修改代码后必跑
```

## 架构要点

- **入口**: `app/main.py` (FastAPI), `app/cli.py` (CLI)
- **刮削器注册**: `app/scrapers/registry.py` — 新增站点需注册到 `SCRAPERS` 列表
- **唯一刮削器**: javdb (`.opencode/skills/add-new-scraper/` 提供了添加新站点的 skill)
- **HTML 解析**: `selectolax` (非 BeautifulSoup)
- **HTTP 客户端**: 优先 `curl-cffi`（绕过 Cloudflare），兜底 `httpx`
- **设置缓存**: `get_settings()` 由 `@lru_cache` 缓存，仅读取一次环境变量
- **任务进度**: 内存 dict + threading.Lock（Web 端用于 HTMX 轮询）
- **并发锁**: 目录级 `fcntl.flock`，防止同一目录并发刮削

## 特殊约定

- 所有文件使用 `from __future__ import annotations`
- 类型注解用 `str | None` 而非 `Optional[str]`
- `ruff` 是代码检查工具，`mypy` 负责类型检查，`pytest` 负责测试（dev 依赖，在 `dependency-groups.dev` 中）
- 测试在 `tests/` 目录，用 pytest 管理。纯单元测试，不依赖网络
- 依赖在 `pyproject.toml` 声明，Dockerfile 中重复列出了 `pip install` 行。新增依赖需同步更新两处
- `NFOFETCH_JAVDB_COOKIE` 环境变量是访问 javdb 的必备配置

## Docker

```bash
docker compose up -d --build     # 构建并启动
docker compose logs -f           # 查看日志
```

卷挂载和端口映射在 `docker-compose.yml`，环境变量占位在 `.env.example`。入口脚本 `docker-entrypoint.sh` 处理容器内权限和目录检查。

## 项目布局

```
app/
  main.py           # FastAPI 路由 & HTMX 端点
  cli.py            # CLI 入口 (python -m app.cli)
  config.py         # get_settings() — 环境变量 → dataclass
  schemas.py        # MovieMetadata / SearchResult / ScrapeResult
  scrapers/         # 站点刮削器 (base.py / javdb.py / registry.py)
  services/         # 业务逻辑 (scrape / nfo / file / settings)
  templates/        # Jinja2 模板 (HTMX partials)
```
