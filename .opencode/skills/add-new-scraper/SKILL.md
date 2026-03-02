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
├── registry.py  # scraper 注册与工厂函数
└── your_site.py # 新站点实现
```

## 步骤 1：创建 Scraper 类

新建文件 `app/scrapers/your_site.py`，继承 `BaseScraper`：

```python
from __future__ import annotations

import os
from typing import List, Optional
from urllib.parse import urljoin, urlparse

import httpx
from selectolax.parser import HTMLParser

from app.config import Settings
from app.schemas import Actor, MovieMetadata, SearchResult
from app.scrapers.base import BaseScraper

try:
    from curl_cffi import requests as curl_requests
    _HAS_CURL_CFFI = True
except Exception:
    curl_requests = None
    _HAS_CURL_CFFI = False


class YourSiteScraper(BaseScraper):
    """站点名称及简要说明。"""

    name = "yoursite"

    def supports(self, url: str) -> bool:
        parsed = urlparse(url)
        host = parsed.netloc.lower()
        return "yoursite.com" in host and parsed.path.startswith("/v/")

    def scrape(self, url: str, settings: Settings) -> MovieMetadata:
        parsed = urlparse(url)
        headers = {
            "User-Agent": settings.user_agent,
            "Referer": f"{parsed.scheme}://{parsed.netloc}/",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "zh-CN,zh;q=0.7,en;q=0.5",
        }

        if settings.http_proxy:
            os.environ.setdefault("HTTP_PROXY", settings.http_proxy)
            os.environ.setdefault("HTTPS_PROXY", settings.http_proxy)

        if _HAS_CURL_CFFI:
            resp = curl_requests.get(
                url,
                headers=headers,
                impersonate="chrome",
                timeout=20.0,
            )
            resp.raise_for_status()
            html = resp.text
        else:
            with httpx.Client(headers=headers, timeout=20.0) as client:
                resp = client.get(url)
                resp.raise_for_status()
                html = resp.text

        tree = HTMLParser(html)
        metadata = self._parse_metadata(tree, base_url=url)
        metadata.source_url = url
        return metadata

    def search(self, query: str, settings: Settings) -> List[SearchResult]:
        search_url = f"https://yoursite.com/search?q={urllib.parse.quote(query)}"
        return self._parse_search_results(html, base_url=search_url)

    def _parse_metadata(self, tree: HTMLParser, base_url: str) -> MovieMetadata:
        number = self._parse_number(tree)
        title = self._parse_title(tree)
        full_title = f"{number} {title}" if number and title else title or number or "Unknown Title"

        return MovieMetadata(
            title=full_title,
            original_title=self._parse_original_title(tree),
            number=number,
            plot=self._parse_plot(tree),
            year=self._parse_year(tree),
            premiered=self._parse_premiered(tree),
            runtime=self._parse_runtime(tree),
            genres=self._parse_genres(tree),
            tags=self._parse_tags(tree),
            actors=self._parse_actors(tree),
            studio=self._parse_studio(tree),
            label=self._parse_label(tree),
            series=self._parse_series(tree),
            directors=self._parse_directors(tree),
            rating=self._parse_rating(tree),
            posters=self._parse_posters(tree, base_url),
            art=self._parse_art(tree, base_url),
        )

    def _parse_title(self, tree: HTMLParser) -> Optional[str]:
        node = tree.css_first("h2.title")
        return node.text(strip=True) if node else None

    def _parse_number(self, tree: HTMLParser) -> Optional[str]:
        pass

    def _parse_plot(self, tree: HTMLParser) -> Optional[str]:
        pass

    def _parse_year(self, tree: HTMLParser) -> Optional[int]:
        pass

    def _parse_premiered(self, tree: HTMLParser) -> Optional[str]:
        pass

    def _parse_runtime(self, tree: HTMLParser) -> Optional[int]:
        pass

    def _parse_genres(self, tree: HTMLParser) -> List[str]:
        return []

    def _parse_tags(self, tree: HTMLParser) -> List[str]:
        return []

    def _parse_actors(self, tree: HTMLParser) -> List[Actor]:
        return []

    def _parse_studio(self, tree: HTMLParser) -> Optional[str]:
        pass

    def _parse_label(self, tree: HTMLParser) -> Optional[str]:
        pass

    def _parse_series(self, tree: HTMLParser) -> Optional[str]:
        pass

    def _parse_directors(self, tree: HTMLParser) -> List[str]:
        return []

    def _parse_rating(self, tree: HTMLParser) -> Optional[float]:
        pass

    def _parse_posters(self, tree: HTMLParser, base_url: str) -> List[str]:
        return []

    def _parse_art(self, tree: HTMLParser, base_url: str) -> List[str]:
        return []

    def _absolutize_url(self, url: str, base_url: str) -> str:
        if url.startswith("//"):
            parsed = urlparse(base_url)
            return f"{parsed.scheme}:{url}"
        return urljoin(base_url, url)

    def _parse_search_results(self, html: str, base_url: str) -> List[SearchResult]:
        return []
```

## 步骤 2：注册 Scraper

在 `app/scrapers/registry.py` 中添加：

```python
from app.scrapers.your_site import YourSiteScraper

SCRAPERS: List[BaseScraper] = [
    JavdbScraper(),
    YourSiteScraper(),
]
```

## 步骤 3：环境变量（如需要）

在 `app/config.py` 中添加需要的配置字段。

## 关键要点

1. 优先使用 `curl_cffi` 绕过 Cloudflare
2. 使用多个 CSS 选择器兜底，保证容错
3. 返回统一的 `MovieMetadata` 格式
4. 使用 Python 3.10+ 类型注解

## 测试

```bash
uv run python -m app.cli --url "https://yoursite.com/v/xxx"
```
