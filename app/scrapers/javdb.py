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

try:  # 尝试使用 curl_cffi 来模拟浏览器指纹，绕过 Cloudflare
    from curl_cffi import requests as curl_requests

    _HAS_CURL_CFFI = True
except ImportError:  # pragma: no cover - 运行环境未安装 curl_cffi 时兜底
    curl_requests = None  # type: ignore[assignment, misc]
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
            "Accept-Encoding": "gzip, deflate, br",
            "Connection": "keep-alive",
            "Upgrade-Insecure-Requests": "1",
        }
        if settings.javdb_cookie:
            headers["Cookie"] = settings.javdb_cookie

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

    def _validate_video_page(self, tree: HTMLParser) -> None:
        """检查 HTML 是否为有效的 JavDB 影片详情页，若不是则抛出明确异常。"""
        has_video_detail = bool(tree.css_first("div.video-detail")) or bool(
            tree.css_first("nav.movie-panel-info")
        )
        has_login_form = bool(tree.css_first("form#new_user, form.new_user"))
        has_login_link = bool(tree.css_first('a[href*="/users/new"]'))
        has_over18 = bool(
            tree.css_first("div.over18-modal, div.modal.is-active.over18-modal")
        )

        # 登录页（含 over18 弹窗）优先报告登录问题
        if has_login_form or (has_login_link and not has_video_detail):
            raise ValueError(
                "需要登录 JavDB 或 JAVDB_COOKIE 已过期，请更新 JAVDB_COOKIE 环境变量。"
            )
        # 独立年龄验证墙（无登录表单时）
        if has_over18:
            raise ValueError(
                "JavDB 返回了年龄验证页面，请确保 JAVDB_COOKIE 包含有效的 over18 cookie。"
            )
        # 影片详情页核心结构缺失
        if not has_video_detail:
            raise ValueError(
                "无法获取影片信息，可能该页面已被删除或 JavDB 结构已变更。"
            )

    def scrape(self, url: str, settings: Settings) -> MovieMetadata:
        parsed = urlparse(url)
        # 如果用户用了主域名 javdb.com，尝试改成当前常见镜像域名，减少被墙/403 概率。
        host = parsed.netloc.lower()
        if host == "javdb.com":
            url = parsed._replace(netloc=settings.javdb_mirror).geturl()

        html = self._request_page(url, settings)
        tree = HTMLParser(html)
        self._validate_video_page(tree)
        metadata = self._parse_metadata(tree, base_url=url)
        metadata.source_url = url  # type: ignore[assignment]
        return metadata

    def search(self, query: str, settings: Settings) -> list[SearchResult]:
        """搜索影片，支持番号或标题搜索。"""

        search_url = f"https://{settings.javdb_mirror}/search?q={urllib.parse.quote(query)}&f=all"

        html = self._request_page(search_url, settings)
        return self._parse_search_results(html, base_url=search_url)

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
        actors = self._parse_actors(tree)
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
            posters=posters,  # type: ignore[arg-type]
            art=art,  # type: ignore[arg-type]
        )

    # ---- 字段解析辅助方法 ----

    def _parse_title(self, tree: HTMLParser) -> str | None:
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
            "h1",
        ]
        for sel in candidates:
            node = tree.css_first(sel)
            if node and node.text():
                return node.text(strip=True)
        # 兜底：页面第一个 h2
        node = tree.css_first("h2")
        return node.text(strip=True) if node else None

    def _parse_number(self, tree: HTMLParser) -> str | None:
        # 当前结构（中文/英文）：
        # <strong>番號:</strong> 或 <strong>ID:</strong>
        # <span class="value"><a>IPVR</a>-335</span> 或 <span class="value"><a>101413</a>-455</span>
        # <a class="button copy-to-clipboard" data-clipboard-text="IPVR-335">
        # 优先读 data-clipboard-text，其次 span.value 文本。
        for block in tree.css("nav.movie-panel-info div.panel-block"):
            label = block.css_first("strong")
            label_text = label.text(strip=True) if label else ""
            if any(x in label_text for x in ("番號", "番号", "ID", "Id", "id")):
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

        # 兜底：从标题中提取形如 `ABC-123` 或 `101413-455` 的番号
        title = self._parse_title(tree) or ""

        # 标准番号如 ABC-123 / ABC_123 → ABC-123
        m = re.search(r"([A-Za-z]{2,6})[-_]?(\d{2,8})", title)
        if m:
            return f"{m.group(1).upper()}-{str(int(m.group(2))).zfill(3)}"
        # 纯数字番号 101413-455（连字符版）
        m = re.search(r"(\d{4,})\s*-\s*(\d{2,6})", title)
        if m:
            return f"{m.group(1)}-{m.group(2)}"
        # 纯数字番号 101413_455（下划线版，与连字符版为不同番号）
        m = re.search(r"(\d{4,})\s*_\s*(\d{2,6})", title)
        if m:
            return f"{m.group(1)}-{m.group(2)}"
        return None

    def _parse_plot(self, tree: HTMLParser) -> str | None:
        # 简介区域
        for sel in [
            "div.description",
            "div.synopsis",
            "section#introduction",
            "p.description",
        ]:
            node = tree.css_first(sel)
            if node and node.text():
                return node.text(strip=True)
        return None

    def _parse_dates(self, tree: HTMLParser) -> tuple[int | None, str | None]:
        # 当前结构：
        # <div class="panel-block">
        #   <strong>日期:</strong>
        #   &nbsp;<span class="value">2025-10-23</span>
        # </div>
        # 兼容老结构中的「發行日期/发行日期/上市日期」文案。

        date_text: str | None = None
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

        year: int | None = None
        if date_text:
            try:
                year = int(date_text.split("-")[0])
            except ValueError:
                year = None
        return year, date_text

    def _parse_runtime(self, tree: HTMLParser) -> int | None:
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

    def _parse_genres(self, tree: HTMLParser) -> list[str]:
        genres: list[str] = []
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

    def _parse_actors(self, tree: HTMLParser) -> list[Actor]:
        actors: list[Actor] = []
        # 当前结构：
        # <div class="panel-block">
        #   <strong>演員:</strong>
        #   &nbsp;<span class="value">
        #     <a href="/actors/...">藤咲舞</a><strong class="symbol female">♀</strong>
        #     <a href="/actors/...">男性名</a><strong class="symbol male">♂</strong>
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
                    # 检查 <a> 后的兄弟元素是否为性别符号
                    gender: str | None = None
                    sibling = a.next
                    if sibling is not None and sibling.tag == "strong":
                        cls = sibling.attributes.get("class") or ""
                        if "female" in cls:
                            gender = "female"
                        elif "male" in cls:
                            gender = "male"
                    actors.append(Actor(name=name, gender=gender))
        return actors

    def _parse_companies(
        self, tree: HTMLParser
    ) -> tuple[str | None, str | None, str | None]:
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
    ) -> tuple[list[str], float | None]:
        """解析导演和评分信息。

        - 导演：优先从「導演 / 导演 / Director」信息块中读取 a 标签文本；
        - 评分：从包含「評分 / 评分」的块中提取第一个数字（支持小数）。
        """

        directors: list[str] = []
        rating: float | None = None

        # 导演
        for block in tree.css("nav.movie-panel-info div.panel-block"):
            label_el = block.css_first("strong")
            label_text = label_el.text(strip=True) if label_el else ""
            if "導演" in label_text or "导演" in label_text or "Director" in label_text:
                value_span = block.css_first("span.value")
                if not value_span:
                    continue
                for a in value_span.css("a"):
                    name = a.text(strip=True)
                    if name and name not in directors:
                        directors.append(name)

        # 评分

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
    ) -> tuple[list[str], list[str]]:
        posters: list[str] = []
        art: list[str] = []

        # 封面：视频详情页大图
        # <div class="column column-video-cover">
        #   <a href=".../play?..."><img src="https://...covers/...jpg" class="video-cover"></a>
        # 注意：<a> 的 href 可能是播放页链接而非图片直链，优先取内部 <img> 的 src
        cover_link = tree.css_first("div.column-video-cover a")
        if cover_link:
            img = cover_link.css_first("img")
            if img:
                url = self._get_img_url(img, base_url)
                if url:
                    posters.append(url)
            else:
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

        # 若仍无剧照，将封面作为 fanart 兜底
        if not art and posters:
            art.append(posters[0])

        posters.sort()
        art.sort()
        return posters, art

    # ---- 通用辅助 ----

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
        """解析搜索结果页面，返回搜索结果列表。"""
        tree = HTMLParser(html)
        results: list[SearchResult] = []

        for item in tree.css("div.movie-list div.item"):
            link = item.css_first("a.box")
            if not link:
                continue

            href = link.attributes.get("href")
            if not href or not href.startswith("/v/"):
                continue

            video_url = self._abspath_url(href, base_url)

            title_node = item.css_first("div.video-title")
            title_text = title_node.text(strip=True) if title_node else ""

            number_node = item.css_first("div.video-title strong")
            number_text = number_node.text(strip=True) if number_node else None

            date_node = item.css_first("div.meta")
            date_text = date_node.text(strip=True) if date_node else None
            if date_text:
                match = re.search(r"(\d{2})/(\d{2})/(\d{4})", date_text)
                if match:
                    date_text = f"{match.group(3)}-{match.group(1)}-{match.group(2)}"

            poster_img = item.css_first("img")
            poster_url = None
            if poster_img:
                poster_url = poster_img.attributes.get("src")
                if poster_url:
                    poster_url = self._abspath_url(poster_url, base_url)

            results.append(
                SearchResult(
                    title=title_text,
                    number=number_text,
                    url=video_url,
                    poster_url=poster_url,
                    date=date_text,
                )
            )

        return results
