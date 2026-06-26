---
name: add-new-scraper
description: 为 nfofetch 添加新的影片刮削站点源
---

## 概述

本文档指导如何为 nfofetch 添加新的影片信息刮削源。

## 文件结构

```
app/scrapers/
├── base.py      # 抽象基类定义
├── javdb.py     # javdb 站点实现（参考实现）
├── jav321.py    # jav321 站点实现（另一参考）
├── dmm.py       # DMM/FANZA 实现（CSR 站点，用 Playwright 渲染 JS）
├── registry.py  # scraper 注册与工厂函数
└── your_site.py # 新站点实现
```

## 步骤 1：创建 Scraper 类

新建文件 `app/scrapers/your_site.py`，继承 `BaseScraper`：

```python
from __future__ import annotations

from urllib.parse import urljoin, urlparse

import httpx
from selectolax.parser import HTMLParser

from app.config import Settings
from app.retry import retry_request
from app.schemas import Actor, MovieMetadata, SearchResult
from app.scrapers.base import BaseScraper

try:
    from curl_cffi import requests as curl_requests
    _HAS_CURL_CFFI = True
except ImportError:  # pragma: no cover
    curl_requests = None  # type: ignore[assignment, misc]
    _HAS_CURL_CFFI = False


class YourSiteScraper(BaseScraper):
    """站点名称及简要说明。"""

    name = "yoursite"

    def supports(self, url: str) -> bool:
        parsed = urlparse(url)
        host = parsed.netloc.lower()
        return "yoursite.com" in host and parsed.path.startswith("/v/")

    def _request_page(
        self, url: str, settings: Settings, timeout: int | None = None
    ) -> str:
        headers = {
            "User-Agent": settings.user_agent,
            "Referer": f"{urlparse(url).scheme}://{urlparse(url).netloc}/",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "zh-CN,zh;q=0.7,en;q=0.5",
        }
        timeout_val = timeout or settings.http_timeout
        proxy = settings.http_proxy

        def _request() -> str:
            if _HAS_CURL_CFFI:
                kwargs = {}
                if proxy:
                    kwargs["proxy"] = proxy
                resp = curl_requests.get(  # type: ignore[union-attr]
                    url, headers=headers, impersonate="chrome",
                    timeout=timeout_val, **kwargs,  # type: ignore[arg-type]
                )
                resp.raise_for_status()
                return resp.text
            else:
                client_kwargs = {"headers": headers, "timeout": timeout_val}
                if proxy:
                    client_kwargs["proxies"] = {
                        "http://": proxy, "https://": proxy,
                    }
                with httpx.Client(**client_kwargs) as client:  # type: ignore[arg-type]
                    resp = client.get(url)
                    resp.raise_for_status()
                    return resp.text

        return retry_request(_request, max_retries=2)

    def scrape(self, url: str, settings: Settings) -> MovieMetadata:
        html = self._request_page(url, settings)
        tree = HTMLParser(html)
        metadata = self._parse_metadata(tree, base_url=url)
        metadata.source_url = url  # type: ignore[assignment]
        return metadata

    def search(self, query: str, settings: Settings) -> list[SearchResult]:
        """可选：实现搜索。search_movie() 会自动并行调用所有 scraper 的 search()。
        搜索仅番号精确匹配时使用 POST，否则使用 GET。"""
        search_url = f"https://yoursite.com/search?q={urllib.parse.quote(query)}"
        html = self._request_page(search_url, settings)
        return self._parse_search_results(html, base_url=search_url)

    def _parse_metadata(self, tree: HTMLParser, base_url: str) -> MovieMetadata:
        number = self._parse_number(tree)
        main_title = self._parse_title(tree)
        if number and main_title:
            title = f"{number} {main_title}"
        else:
            title = main_title or number or "Unknown Title"

        return MovieMetadata(
            title=title,
            number=number,
            plot=self._parse_plot(tree),
            premiered=self._parse_premiered(tree),
            releasedate=self._parse_premiered(tree),
            runtime=self._parse_runtime(tree),
            genres=self._parse_genres(tree),
            actors=self._parse_actors(tree),
            studio=self._parse_studio(tree),
            rating=self._parse_rating(tree),
            posters=self._parse_images(tree, base_url)[0],  # type: ignore[arg-type]
            art=self._parse_images(tree, base_url)[1],  # type: ignore[arg-type]
        )

    def _parse_title(self, tree: HTMLParser) -> str | None:
        node = tree.css_first("h2.title")
        return node.text(strip=True) if node else None

    def _parse_number(self, tree: HTMLParser) -> str | None: ...

    def _parse_plot(self, tree: HTMLParser) -> str | None: ...

    def _parse_premiered(self, tree: HTMLParser) -> str | None: ...

    def _parse_runtime(self, tree: HTMLParser) -> int | None: ...

    def _parse_genres(self, tree: HTMLParser) -> list[str]:
        return []

    def _parse_actors(self, tree: HTMLParser) -> list[Actor]:
        return []

    def _parse_studio(self, tree: HTMLParser) -> str | None: ...

    def _parse_rating(self, tree: HTMLParser) -> float | None: ...

    def _parse_images(
        self, tree: HTMLParser, base_url: str
    ) -> tuple[list[str], list[str]]:
        return [], []

    def _abspath_url(self, url: str, base_url: str) -> str:
        if url.startswith("//"):
            parsed = urlparse(base_url)
            return f"{parsed.scheme}:{url}"
        return urljoin(base_url, url)

    def _parse_search_results(self, html: str, base_url: str) -> list[SearchResult]:
        return []
```

## 步骤 2：注册 Scraper

在 `app/scrapers/registry.py` 中添加：

```python
from app.scrapers.your_site import YourSiteScraper

SCRAPERS: list[BaseScraper] = [
    JavdbScraper(),
    Jav321Scraper(),
    YourSiteScraper(),
]
```

注意：`search_movie()` 会通过 `ThreadPoolExecutor` 并行调用所有 `SCRAPERS` 的 `search()` 方法，
结果去重后合并展示。无需修改搜索路由。

## 步骤 3：环境变量（如需要）

在 `app/config.py` 中添加需要的配置字段。

## 关键要点

1. 优先使用 `curl_cffi` 绕过 Cloudflare，兜底 `httpx`
2. 使用 `_request_page()` 封装 HTTP 请求（复用 `retry_request` 重试 429/5xx）
3. 返回统一的 `MovieMetadata` 格式
4. 使用 Python 3.10+ 类型注解（`str | None` 而非 `Optional[str]`）
5. `search()` 返回空列表 = 不支持搜索，`search_movie()` 不会报错
6. **CSR（客户端渲染）站点**（如 DMM）：服务器 HTML 不含数据，必须用 Playwright 渲染 JS。参考 `dmm.py` 的 `_request_page()`，通过 `asyncio.get_running_loop()` 自动切换同步/异步线程池。添加依赖：`pyproject.toml` 加 `playwright>=1.50.0`，Dockerfile 安装 Chromium
7. **站点有新旧版本时**（如 DMM 新旧站）：可创建两个 Scraper 共享 `_fetch_page()`，`supports()` 按域名区分，注册时后者兜底。`get_enabled_scrapers` 中自动关联（如开启 `dmm` 自动包含 `dmm_legacy`）
8. **解析策略建议**：
   - 优先用页面文本稳定标签（`配信開始日`、`収録時間`）而非 CSS 类名
   - 旧站不同产品类型（DVD/租赁/DOD）用同一解析器，注意标签名差异
   - 图片 URL 从 `<img src>` 或 `<a href>` 中提取，小图转为大图（如 `-N.jpg` → `jp-N.jpg`）

## 测试

```bash
uv run python -m app.cli --url "https://yoursite.com/v/xxx"
```

注册后验证并行搜索：
```bash
uv run pytest tests/test_scrape_service.py -v -k "test_search_movie"
```
