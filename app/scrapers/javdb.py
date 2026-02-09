from __future__ import annotations

import os
from typing import List, Optional
from urllib.parse import urljoin, urlparse

import httpx
from selectolax.parser import HTMLParser

from app.config import Settings
from app.schemas import Actor, MovieMetadata
from app.scrapers.base import BaseScraper
from app.cookie_store import get_cookie_for_url

try:  # 尝试使用 curl_cffi 来模拟浏览器指纹，绕过 Cloudflare
    from curl_cffi import requests as curl_requests

    _HAS_CURL_CFFI = True
except Exception:  # pragma: no cover - 运行环境未安装 curl_cffi 时兜底
    curl_requests = None  # type: ignore[assignment]
    _HAS_CURL_CFFI = False


class JavdbScraper(BaseScraper):
    """javdb 站点刮削实现。

    由于站点结构可能调整，这里采用相对宽松的 CSS 选择器，并在字段缺失时做容错。
    """

    name = "javdb"

    def supports(self, url: str) -> bool:
        parsed = urlparse(url)
        host = parsed.netloc.lower()
        return "javdb" in host and parsed.path.startswith("/v/")

    def scrape(self, url: str, settings: Settings) -> MovieMetadata:
        parsed = urlparse(url)
        # 如果用户用了主域名 javdb.com，尝试改成当前常见镜像域名，减少被墙/403 概率。
        host = parsed.netloc.lower()
        if host == "javdb.com":
            url = parsed._replace(netloc="javdb565.com").geturl()
            parsed = urlparse(url)

        headers = {
            "User-Agent": settings.user_agent,
            "Referer": f"{parsed.scheme}://{parsed.netloc}/",
            "Accept": (
                "text/html,application/xhtml+xml,application/xml;q=0.9,"
                "image/avif,image/webp,image/apng,*/*;q=0.8"
            ),
            "Accept-Language": "zh-CN,zh;q=0.7,en;q=0.5",
            "Accept-Encoding": "gzip, deflate, br",
            "Connection": "keep-alive",
            "Upgrade-Insecure-Requests": "1",
        }

        # Cookie 优先顺序：
        # 1. 环境变量 NFOFETCH_JAVDB_COOKIE
        # 2. app.cookie_store.SITE_COOKIES 中按站点预设的 Cookie
        cookie = get_cookie_for_url(url, env_cookie=settings.javdb_cookie)
        if cookie:
            headers["Cookie"] = cookie
        # 代理通过环境变量传递，curl_cffi / httpx 都能识别。
        if settings.http_proxy:
            os.environ.setdefault("HTTP_PROXY", settings.http_proxy)
            os.environ.setdefault("HTTPS_PROXY", settings.http_proxy)

        # 优先使用 curl_cffi 模拟浏览器指纹，减少 Cloudflare 403 可能性。
        if _HAS_CURL_CFFI:
            resp = curl_requests.get(  # type: ignore[union-attr]
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
        metadata.source_url = url  # type: ignore[assignment]
        return metadata

    def _parse_metadata(self, tree: HTMLParser, base_url: str) -> MovieMetadata:
        number = self._parse_number(tree)
        main_title = self._parse_title(tree)
        if number and main_title:
            title = f"{number} {main_title}"
        else:
            title = main_title or number or "Unknown Title"
        plot = self._parse_plot(tree)
        year, premiered = self._parse_dates(tree)
        runtime = self._parse_runtime(tree)
        genres = self._parse_genres(tree)
        actors = self._parse_actors(tree, base_url)
        studio, label, series = self._parse_companies(tree)
        directors, rating = self._parse_directors_and_rating(tree)
        posters, art = self._parse_images(tree, base_url)

        return MovieMetadata(
            title=title,
            original_title=None,
            number=number,
            plot=plot,
            year=year,
            premiered=premiered,
            releasedate=premiered,
            runtime=runtime,
            genres=genres,
            tags=[],
            actors=actors,
            studio=studio,
            label=label,
            series=series,
            directors=directors,
            rating=rating,
            posters=posters,
            art=art,
        )

    # ---- 字段解析辅助方法 ----

    def _parse_title(self, tree: HTMLParser) -> Optional[str]:
        # 当前 javdb 详情页结构：
        # <div class="video-detail">
        #   <h2 class="title is-4">
        #     <strong>IPVR-335 </strong>
        #     <strong class="current-title">日文标题...</strong>
        #   </h2>
        # </div>
        node = tree.css_first("div.video-detail h2.title.is-4 strong.current-title")
        if node and node.text():
            return node.text(strip=True)

        # 兜底：视频详情页的大标题
        candidates = [
            "h2.title",
            "h2.video-title",
            "div.video-title h2",
            "main h2",
        ]
        for sel in candidates:
            node = tree.css_first(sel)
            if node and node.text():
                return node.text(strip=True)
        # 兜底：页面第一个 h2
        node = tree.css_first("h2")
        return node.text(strip=True) if node else None

    def _parse_number(self, tree: HTMLParser) -> Optional[str]:
        # 当前结构：
        # <div class="panel-block first-block">
        #   <strong>番號:</strong>
        #   &nbsp;<span class="value"><a>IPVR</a>-335</span>
        #   ...
        #   <a class="button ... copy-to-clipboard" data-clipboard-text="IPVR-335">
        # 优先读 data-clipboard-text，其次 span.value 文本。
        for block in tree.css("nav.movie-panel-info div.panel-block"):
            label = block.css_first("strong")
            label_text = label.text(strip=True) if label else ""
            if "番號" in label_text or "番号" in label_text:
                # 1) data-clipboard-text
                btn = block.css_first("a.copy-to-clipboard")
                if btn:
                    code = btn.attributes.get("data-clipboard-text")
                    if code:
                        return code.strip()
                # 2) span.value 里的文本
                value_span = block.css_first("span.value")
                if value_span and value_span.text():
                    return value_span.text(strip=True)

        # 兜底：从标题中提取形如 `ABC-123` 的番号
        title = self._parse_title(tree) or ""
        import re

        m = re.search(r"([A-Za-z]{2,5}-?\d{2,5})", title)
        if m:
            return m.group(1)
        return None

    def _parse_plot(self, tree: HTMLParser) -> Optional[str]:
        # 简介区域
        for sel in ["div.description", "div.synopsis", "section#introduction", "p.description"]:
            node = tree.css_first(sel)
            if node and node.text():
                return node.text(strip=True)
        return None

    def _parse_dates(self, tree: HTMLParser) -> tuple[Optional[int], Optional[str]]:
        # 当前结构：
        # <div class="panel-block">
        #   <strong>日期:</strong>
        #   &nbsp;<span class="value">2025-10-23</span>
        # </div>
        # 兼容老结构中的「發行日期/发行日期/上市日期」文案。
        import re

        date_text: Optional[str] = None
        for node in tree.css("div.panel-block, div.panel-item, tr"):
            text = node.text(strip=True)
            if (
                "發行日期" in text
                or "发行日期" in text
                or "上市日期" in text
                or "日期:" in text
                or "日期：" in text
            ):
                m = re.search(r"(\d{4}-\d{2}-\d{2})", text)
                if m:
                    date_text = m.group(1)
                    break

        year: Optional[int] = None
        if date_text:
            try:
                year = int(date_text.split("-")[0])
            except ValueError:
                year = None
        return year, date_text

    def _parse_runtime(self, tree: HTMLParser) -> Optional[int]:
        import re

        for node in tree.css("div.panel-block, div.panel-item, tr"):
            text = node.text(strip=True)
            if "分鐘" in text or "分" in text or "min" in text.lower():
                m = re.search(r"(\d+)", text)
                if m:
                    try:
                        return int(m.group(1))
                    except ValueError:
                        continue
        return None

    def _parse_genres(self, tree: HTMLParser) -> List[str]:
        genres: List[str] = []
        # 优先从「類別」信息块提取：
        # <div class="panel-block">
        #   <strong>類別:</strong>
        #   &nbsp;<span class="value"><a>情侶</a>, ...</span>
        # </div>
        for block in tree.css("nav.movie-panel-info div.panel-block"):
            label = block.css_first("strong")
            label_text = label.text(strip=True) if label else ""
            if "類別" in label_text or "类别" in label_text:
                value_span = block.css_first("span.value")
                if value_span:
                    for a in value_span.css("a"):
                        text = a.text(strip=True)
                        if text and text not in genres:
                            genres.append(text)

        # 兜底：页面其它标签链接
        for sel in [
            "a.category",
            "a.tag",
            "span.category a",
            "div.tags a",
        ]:
            for node in tree.css(sel):
                text = node.text(strip=True)
                if text and text not in genres:
                    genres.append(text)
        return genres

    def _parse_actors(self, tree: HTMLParser, base_url: str) -> List[Actor]:
        actors: List[Actor] = []
        # 当前结构：
        # <div class="panel-block">
        #   <strong>演員:</strong>
        #   &nbsp;<span class="value">
        #     <a href="/actors/...">藤咲舞</a><strong class="symbol female">♀</strong>
        #   </span>
        # </div>
        for block in tree.css("nav.movie-panel-info div.panel-block"):
            label = block.css_first("strong")
            label_text = label.text(strip=True) if label else ""
            if "演員" in label_text or "演员" in label_text:
                value_span = block.css_first("span.value")
                if not value_span:
                    continue
                for a in value_span.css("a"):
                    name = a.text(strip=True)
                    if not name:
                        continue
                    actors.append(Actor(name=name, role=None, thumb=None))
        return actors

    def _parse_companies(
        self, tree: HTMLParser
    ) -> tuple[Optional[str], Optional[str], Optional[str]]:
        studio = label = series = None
        # 当前结构：
        # <div class="panel-block"><strong>片商:</strong><span class="value"><a>IDEA POCKET</a></span></div>
        # <div class="panel-block"><strong>系列:</strong><span class="value"><a>アイポケ8KVR</a></span></div>
        for block in tree.css("nav.movie-panel-info div.panel-block"):
            label_el = block.css_first("strong")
            label_text = label_el.text(strip=True) if label_el else ""
            value_span = block.css_first("span.value")
            value_text = value_span.text(strip=True) if value_span else ""
            if not value_text:
                continue
            if "片商" in label_text or "Studio" in label_text:
                studio = value_text
            elif "發行" in label_text or "发行" in label_text or "Label" in label_text:
                label = value_text
            elif "系列" in label_text or "Series" in label_text:
                series = value_text
        return studio, label, series

    def _parse_directors_and_rating(
        self, tree: HTMLParser
    ) -> tuple[List[str], Optional[float]]:
        """解析导演和评分信息。

        - 导演：优先从「導演 / 导演 / Director」信息块中读取 a 标签文本；
        - 评分：从包含「評分 / 评分」的块中提取第一个数字（支持小数）。
        """

        directors: List[str] = []
        rating: Optional[float] = None

        # 导演
        for block in tree.css("nav.movie-panel-info div.panel-block"):
            label_el = block.css_first("strong")
            label_text = label_el.text(strip=True) if label_el else ""
            if (
                "導演" in label_text
                or "导演" in label_text
                or "Director" in label_text
            ):
                value_span = block.css_first("span.value")
                if not value_span:
                    continue
                for a in value_span.css("a"):
                    name = a.text(strip=True)
                    if name and name not in directors:
                        directors.append(name)

        # 评分
        import re

        if rating is None:
            for node in tree.css("div.panel-block, div.panel-item, tr, section, div"):
                text = node.text(strip=True)
                if not text:
                    continue
                if "評分" in text or "评分" in text or "Rating" in text:
                    m = re.search(r"(\d+(?:\.\d+)?)", text)
                    if m:
                        try:
                            rating = float(m.group(1))
                        except ValueError:
                            rating = None
                    break

        return directors, rating

    def _parse_images(
        self, tree: HTMLParser, base_url: str
    ) -> tuple[List[str], List[str]]:
        posters: List[str] = []
        art: List[str] = []

        # 封面：视频详情页大图
        # <div class="column column-video-cover">
        #   <a href="https://...covers/...jpg"><img src="...covers/...jpg" class="video-cover"></a>
        cover_link = tree.css_first("div.column-video-cover a")
        if cover_link:
            href = cover_link.attributes.get("href")
            if href:
                posters.append(self._abspath_url(href, base_url))
        if not posters:
            cover_selectors = [
                "div.video-cover img",
                "div.cover img",
                "img.video-cover",
            ]
            for sel in cover_selectors:
                node = tree.css_first(sel)
                if node:
                    url = self._get_img_url(node, base_url)
                    if url:
                        posters.append(url)
                        break

        # 剧照 / 预览图
        # 当前结构：
        # <div class="tile-images preview-images">
        #   <a class="tile-item" href="..._l_0.jpg"><img src="..._s_0.jpg"></a>
        # </div>
        for a in tree.css("div.preview-images a.tile-item"):
            href = a.attributes.get("href")
            if href:
                url = self._abspath_url(href, base_url)
                if url not in art:
                    art.append(url)

        # 兜底：老结构下的 img
        if not art:
            for sel in [
                "div.sample-images img",
                "div.preview-images img",
                "div.screenshots img",
            ]:
                for node in tree.css(sel):
                    url = self._get_img_url(node, base_url)
                    if url and url not in art:
                        art.append(url)

        return posters, art

    # ---- 通用辅助 ----

    def _get_img_url(self, node, base_url: str) -> Optional[str]:
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

    def _extract_value_after_label(self, text: str) -> Optional[str]:
        # 移除常见 label 之后取余下文本
        for label in ["片商", "Studio", "發行", "发行", "Label", "系列", "Series"]:
            if label in text:
                return text.split(label, 1)[-1].strip(" ：: ")
        return None

