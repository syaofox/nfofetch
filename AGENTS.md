# AGENTS.md - nfofetch 开发指南

本文件面向 AI 编程代理，为其提供项目开发规范与操作指南。

## 项目概述

nfofetch 是一个基于 **FastAPI + HTMX** 的影片刮削工具，支持从 javdb 抓取影片信息并生成 Jellyfin 兼容的 NFO 文件与图片资源。

## 技术栈

- **Python**: 3.10+
- **Web 框架**: FastAPI
- **依赖管理**: uv
- **代码检查**: ruff, mypy
- **容器化**: Docker, docker-compose

## 环境配置

### 安装 uv（如未安装）

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
```

### 安装依赖

```bash
uv sync
```

### 激活虚拟环境

```bash
source .venv/bin/activate
# 或使用 uv run
```

## 开发命令

### 启动开发服务器

```bash
uv run uvicorn app.main:app --reload
```

启动后访问 `http://127.0.0.1:8000/`

### 运行单个测试（如有测试）

```bash
# 使用 uv 运行 pytest
uv run pytest tests/某个测试文件.py::测试函数名 -v
# 或使用 pytest 直接运行
pytest tests/某个测试文件.py::测试函数名 -v
```

### 运行所有测试

```bash
uv run pytest
```

### 代码检查

```bash
# 运行 ruff 检查
uv run ruff check .

# 运行 ruff 格式化检查
uv run ruff format --check .

# 运行 mypy 类型检查
uv run mypy .
```

### 自动修复

```bash
# ruff 自动修复
uv run ruff check --fix .
uv run ruff format .
```

## 代码规范

### 导入规范

- 使用绝对导入：`from app.config import get_settings`
- 导入顺序：标准库 → 第三方库 → 本地模块
- 导入时按字母排序
- 使用 `from __future__ import annotations` 启用延迟注解

```python
from __future__ import annotations

import os
import re
from pathlib import Path

from fastapi import FastAPI
from pydantic import BaseModel

from app.config import Settings
from app.schemas import MovieMetadata
```

### 类型注解

- 优先使用 Python 3.10+ 的内置类型注解：`str | None` 而非 `Optional[str]`
- 对于复杂类型，使用 `typing` 模块
- 函数返回值必须有类型注解
- 公开接口（API、Service）必须有完整的类型注解

```python
def scrape_movie(url: str, settings: Settings) -> MovieMetadata:
    ...

def search_movie(query: str, settings: Settings) -> list[SearchResult]:
    ...
```

### 命名约定

- **函数/变量**: 蛇形命名法 `scrape_movie`, `user_agent`
- **类**: 帕斯卡命名法 `BaseScraper`, `MovieMetadata`
- **常量**: 全大写蛇形 `MAX_RETRIES`, `DEFAULT_TIMEOUT`
- **文件**: 蛇形命名法 `file_service.py`, `nfo_service.py`

### Pydantic 模型

- 使用 Pydantic v2 的 `BaseModel`
- 使用 `Field` 定义字段元数据（描述、默认值）
- 使用 `HttpUrl` 处理 URL 类型

```python
from pydantic import BaseModel, Field, HttpUrl

class MovieMetadata(BaseModel):
    title: str = Field(..., description="主标题")
    poster_url: HttpUrl | None = None
```

### 数据类

- 简单配置使用 `@dataclass`

```python
from dataclasses import dataclass

@dataclass
class Settings:
    user_agent: str
    http_proxy: str | None = None
```

### 错误处理

- 使用具体异常类型而非裸 `except:`
- 对于需要用户感知的错误，可以在 except 块中使用 `# noqa: BLE001` 抑制 ruff 警告
- API 端点应捕获异常并返回有意义的错误信息

```python
try:
    metadata = scrape_movie(url, settings=settings)
except Exception as exc:  # noqa: BLE001
    error = str(exc)
```

### 异步编程

- FastAPI 路由使用 `async def`
- 避免在异步函数中使用阻塞 I/O，优先使用 `httpx.AsyncClient`

### 文档字符串

- 使用 Google 风格的文档字符串
- 为公开 API 编写简洁的描述

```python
def scrape(url: str, settings: Settings) -> MovieMetadata:
    """从 URL 抓取并解析影片信息，返回统一的 MovieMetadata。"""
    ...
```

### 路径处理

- 使用 `pathlib.Path` 而非字符串拼接
- 优先使用 `Path.resolve()` 获取绝对路径

```python
from pathlib import Path

base_dir = Path(__file__).resolve().parent
```

### 常量定义

- 模块级常量放在文件顶部
- 使用有意义的命名

```python
BASE_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = BASE_DIR.parent
TEMPLATES_DIR = BASE_DIR / "templates"
```

## Docker 相关

**重要**: 每次修改代码后，必须检查以下文件是否需要同步更新：

- `Dockerfile`: 依赖声明、构建阶段
- `docker-compose.yml`: 服务配置、卷挂载、环境变量

### Dockerfile 更新检查清单

1. 新增依赖：确保在 `pip install` 命令中添加
2. 端口变更：检查 `EXPOSE` 指令
3. 入口命令变更：检查 `CMD` 指令

### 构建 Docker 镜像

```bash
docker compose up -d --build
```

### 查看日志

```bash
docker compose logs -f
```

## 项目结构

```
nfofetch/
├── app/
│   ├── main.py          # FastAPI 应用入口
│   ├── cli.py           # 命令行入口
│   ├── config.py        # 配置管理
│   ├── schemas.py       # Pydantic 模型
│   ├── scrapers/        # 站点刮削器
│   │   ├── base.py
│   │   ├── javdb.py
│   │   └── registry.py
│   └── services/        # 业务逻辑服务
│       ├── file_service.py
│       ├── nfo_service.py
│       └── scrape_service.py
├── Dockerfile
├── docker-compose.yml
├── pyproject.toml
└── uv.lock
```

## 环境变量

| 变量名 | 说明 | 默认值 |
|--------|------|--------|
| `NFOFETCH_USER_AGENT` | HTTP User-Agent | 浏览器 UA |
| `NFOFETCH_HTTP_PROXY` | HTTP 代理 | 无 |
| `NFOFETCH_JAVDB_COOKIE` | javdb Cookie（含 cf_clearance） | 无 |
| `NFOFETCH_BROWSE_ROOT` | 文件浏览器根目录 | 当前工作目录 |

## 常用操作

### 添加新依赖

```bash
uv add <package>
uv add -d <package>  # 开发依赖
```

### 运行 CLI

```bash
uv run python -m app.cli --url "URL" --video "/path/to/video.mp4"
```

## 注意事项

1. 提交代码前务必运行 `ruff check --fix .` 和 `ruff format .`
2. 修改 `pyproject.toml` 后运行 `uv sync` 更新虚拟环境
3. 任何涉及依赖或环境配置的修改，都必须同步更新 Dockerfile
4. 保持代码简洁，避免不必要的复杂性
