from __future__ import annotations

import re
import urllib.parse
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


class JavhooScraper(BaseScraper):
    """javhoo.com 站点刮削实现。"""

    name = "javhoo"

    def supports(self, url: str) -> bool:
        parsed = urlparse(url)
        host = parsed.netloc.lower()
        return "javhoo.com" in host

    def _request_page(
        self, url: str, settings: Settings, timeout: int | None = None
    ) -> str:
        headers = {
            "User-Agent": settings.user_agent,
            "Referer": f"{urlparse(url).scheme}://{urlparse(url).netloc}/",
            "Accept": (
                "text/html,application/xhtml+xml,application/xml;q=0.9,"
                "image/avif,image/webp,image/apng,*/*;q=0.8"
            ),
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
                    url,
                    headers=headers,
                    impersonate="chrome",
                    timeout=timeout_val,
                    **kwargs,  # type: ignore[arg-type]
                )
                resp.raise_for_status()
                return resp.text
            else:
                client_kwargs = {"headers": headers, "timeout": timeout_val}
                if proxy:
                    client_kwargs["proxies"] = {
                        "http://": proxy,
                        "https://": proxy,
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
        search_url = f"https://www.javhoo.com/en/?s={urllib.parse.quote(query)}"
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
            plot=None,
            premiered=self._parse_premiered(tree),
            releasedate=self._parse_premiered(tree),
            runtime=self._parse_runtime(tree),
            genres=self._parse_genres(tree),
            actors=self._parse_actors(tree),
            studio=self._parse_studio(tree),
            series=self._parse_series(tree),
            rating=None,
            posters=self._parse_images(tree, base_url)[0],  # type: ignore[arg-type]
            art=self._parse_images(tree, base_url)[1],  # type: ignore[arg-type]
        )

    def _parse_title(self, tree: HTMLParser) -> str | None:
        node = tree.css_first("h1.article-title")
        if not node:
            return None
        text = node.text(strip=True)
        if not text:
            return None
        # 标题格式为 "番号 主标题"（如 "ABF-360 河合あすなの異常な愛情"）
        # 去掉番号部分只保留主标题
        m = re.search(r"^[A-Za-z0-9-]+\s+(.*)", text)
        if m:
            return m.group(1).strip()
        return text

    def _parse_number(self, tree: HTMLParser) -> str | None:
        for widget in tree.css(".widget.pods_widget_field"):
            h3 = widget.css_first("h3")
            if not h3:
                continue
            label = h3.text(strip=True)
            if "識別碼" in label or "ID" in label or "番号" in label:
                span = widget.css_first("span")
                if span:
                    return span.text(strip=True)
                return widget.text(strip=True).replace(label, "", 1).strip()
        return None

    def _parse_premiered(self, tree: HTMLParser) -> str | None:
        for widget in tree.css(".widget.pods_widget_field"):
            h3 = widget.css_first("h3")
            if not h3:
                continue
            label = h3.text(strip=True)
            if "發行日期" in label or "Date" in label or "发行日期" in label:
                text = widget.text(strip=True).replace(label, "", 1).strip()
                m = re.search(r"(\d{4}-\d{2}-\d{2})", text)
                if m:
                    return m.group(1)
        return None

    def _parse_runtime(self, tree: HTMLParser) -> int | None:
        for widget in tree.css(".widget.pods_widget_field"):
            h3 = widget.css_first("h3")
            if not h3:
                continue
            label = h3.text(strip=True)
            if "長度" in label or "Length" in label or "长度" in label:
                text = widget.text(strip=True).replace(label, "", 1).strip()
                m = re.search(r"(\d+)", text)
                if m:
                    try:
                        return int(m.group(1))
                    except ValueError:
                        pass
        return None

    def _parse_genres(self, tree: HTMLParser) -> list[str]:
        for widget in tree.css(".widget.pods_widget_field"):
            h3 = widget.css_first("h3")
            if not h3:
                continue
            label = h3.text(strip=True)
            if "類別" in label or "Genre" in label or "类别" in label:
                genres: list[str] = []
                for a in widget.css("a"):
                    text = a.text(strip=True)
                    if text and text not in genres:
                        genres.append(text)
                return genres
        return []

    def _parse_studio(self, tree: HTMLParser) -> str | None:
        for widget in tree.css(".widget.pods_widget_field"):
            h3 = widget.css_first("h3")
            if not h3:
                continue
            label = h3.text(strip=True)
            if "製作商" in label or "Studio" in label or "制作商" in label:
                a = widget.css_first("a")
                if a:
                    return a.text(strip=True)
        return None

    def _parse_series(self, tree: HTMLParser) -> str | None:
        for widget in tree.css(".widget.pods_widget_field"):
            h3 = widget.css_first("h3")
            if not h3:
                continue
            label = h3.text(strip=True)
            if "系列" in label or "Series" in label:
                a = widget.css_first("a")
                if a:
                    return a.text(strip=True)
        return None

    def _parse_actors(self, tree: HTMLParser) -> list[Actor]:
        for widget in tree.css(".widget.pods_widget_field"):
            h3 = widget.css_first("h3")
            if not h3:
                continue
            label = h3.text(strip=True)
            if "演員" in label or "Actor" in label or "演员" in label:
                actors: list[Actor] = []
                for a in widget.css("a"):
                    name = a.text(strip=True)
                    if name:
                        actors.append(Actor(name=name))
                return actors
        return []

    def _parse_images(
        self, tree: HTMLParser, base_url: str
    ) -> tuple[list[str], list[str]]:
        posters: list[str] = []
        art: list[str] = []

        # 封面：article-content 中的主图
        img = tree.css_first(".article-content img")
        if img:
            url = self._get_img_url(img, base_url)
            if url:
                posters.append(url)

        # 剧照：the_excerpt 中的 dt-mfp-item 链接
        for a in tree.css(".the_excerpt a.dt-mfp-item"):
            href = a.attributes.get("href")
            if href:
                url = self._abspath_url(href, base_url)
                if url not in art:
                    art.append(url)

        return posters, art

    def _get_img_url(self, node, base_url: str) -> str | None:
        for attr in ("data-src", "src"):
            val = node.attributes.get(attr)
            if val:
                return self._abspath_url(val, base_url)
        return None

    def _abspath_url(self, url: str, base_url: str) -> str:
        if url.startswith("//"):
            parsed = urlparse(base_url)
            return f"{parsed.scheme}:{url}"
        return urljoin(base_url, url)

    def _parse_search_results(self, html: str, base_url: str) -> list[SearchResult]:
        tree = HTMLParser(html)
        results: list[SearchResult] = []

        for article in tree.css("article.excerpt"):
            link = article.css_first("h2 a")
            if not link:
                continue
            href = link.attributes.get("href")
            if not href:
                continue
            video_url = self._abspath_url(href, base_url)
            title = link.text(strip=True) or ""

            number: str | None = None
            m = re.search(r"^([A-Za-z0-9]+-[A-Za-z0-9]+)", title)
            if m:
                number = m.group(1)

            poster_url: str | None = None
            thumb_img = article.css_first("img.thumb")
            if thumb_img:
                poster_url = self._get_img_url(thumb_img, base_url)

            date_text: str | None = None
            time_node = article.css_first("time")
            if time_node:
                dt = time_node.text(strip=True)
                # "Jun 20,2026" → "2026-06-20"
                try:
                    from datetime import datetime

                    parsed = datetime.strptime(dt, "%b %d,%Y")
                    date_text = parsed.strftime("%Y-%m-%d")
                except (ValueError, ImportError):
                    date_text = dt

            results.append(
                SearchResult(
                    title=title,
                    number=number,
                    url=video_url,
                    poster_url=poster_url,
                    date=date_text,
                )
            )

        return results
