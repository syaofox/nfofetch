from __future__ import annotations

import re
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
except ImportError:  # pragma: no cover - 运行环境未安装 curl_cffi 时兜底
    curl_requests = None  # type: ignore[assignment, misc]
    _HAS_CURL_CFFI = False


class Jav321Scraper(BaseScraper):
    """jav321 站点刮削实现。

    jav321 是 DMM 数据的镜像站，不支持 Cloudflare。
    页面结构为 Bootstrap 3，数据在 .panel.panel-info 中。
    """

    name = "jav321"

    def supports(self, url: str) -> bool:
        parsed = urlparse(url)
        host = parsed.netloc.lower()
        return "jav321" in host and parsed.path.startswith("/video/")

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
        if settings.jav321_cookie:
            headers["Cookie"] = settings.jav321_cookie

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
        search_url = "https://www.jav321.com/search"
        headers = {
            "User-Agent": settings.user_agent,
            "Content-Type": "application/x-www-form-urlencoded",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "zh-CN,zh;q=0.7,en;q=0.5",
        }
        if settings.jav321_cookie:
            headers["Cookie"] = settings.jav321_cookie
        proxy = settings.http_proxy
        data = {"sn": query}

        html: str = ""
        final_url: str = search_url
        for attempt in range(2):
            try:
                if _HAS_CURL_CFFI:
                    kwargs = {}
                    if proxy:
                        kwargs["proxy"] = proxy
                    resp = curl_requests.post(  # type: ignore[union-attr]
                        search_url,
                        headers=headers,
                        data=data,
                        impersonate="chrome",
                        timeout=settings.http_timeout,
                        allow_redirects=True,
                        **kwargs,  # type: ignore[arg-type]
                    )
                    resp.raise_for_status()
                    html = resp.text
                    final_url = str(resp.url)
                else:
                    client_kwargs = {
                        "headers": headers,
                        "timeout": settings.http_timeout,
                    }
                    if proxy:
                        client_kwargs["proxies"] = {
                            "http://": proxy,
                            "https://": proxy,
                        }
                    with httpx.Client(**client_kwargs, follow_redirects=True) as client:  # type: ignore[arg-type]
                        resp = client.post(search_url, data=data)
                        resp.raise_for_status()
                        html = resp.text
                        final_url = str(resp.url)
                break
            except Exception:
                if attempt == 1:
                    raise

        return self._parse_search_results(html, base_url=final_url)

    def _parse_metadata(self, tree: HTMLParser, base_url: str) -> MovieMetadata:
        number = self._parse_number(tree)
        main_title = self._parse_title(tree)
        if number and main_title:
            title = f"{number} {main_title}"
        else:
            title = main_title or number or "Unknown Title"

        actors = self._parse_actors(tree)
        studio = self._parse_studio(tree)
        premiered = self._parse_premiered(tree)
        rating = self._parse_rating(tree)
        runtime = self._parse_runtime(tree)
        plot = self._parse_plot(tree)
        genres = self._parse_genres(tree)
        posters, art = self._parse_images(tree, base_url)

        return MovieMetadata(
            title=title,
            number=number,
            plot=plot,
            premiered=premiered,
            releasedate=premiered,
            runtime=runtime,
            genres=genres,
            actors=actors,
            studio=studio,
            rating=rating,
            posters=posters,  # type: ignore[arg-type]
            art=art,  # type: ignore[arg-type]
        )

    def _parse_title(self, tree: HTMLParser) -> str | None:
        h3 = tree.css_first("div.panel-heading h3")
        if h3:
            small = h3.css_first("small")
            if small:
                small.decompose()
            return h3.text(strip=True) or None
        return None

    def _parse_number(self, tree: HTMLParser) -> str | None:
        text = self._get_info_text(tree)
        if not text:
            return None
        m = re.search(r"(?:SN|品番)\s*:\s*(\S+)", text)
        if m:
            return m.group(1).strip()
        return None

    def _parse_plot(self, tree: HTMLParser) -> str | None:
        panel_body = tree.css_first("div.panel-body")
        if not panel_body:
            return None
        rows = panel_body.css("div.row")
        for row in rows:
            col = row.css_first("div.col-md-12")
            if col and not col.css_first("video"):
                text = col.text(strip=True)
                if text and len(text) > 20:
                    return text
        return None

    def _parse_premiered(self, tree: HTMLParser) -> str | None:
        text = self._get_info_text(tree)
        if not text:
            return None
        m = re.search(r"(?:Release Date|配信開始日)\s*:\s*(\d{4}-\d{2}-\d{2})", text)
        return m.group(1) if m else None

    def _parse_runtime(self, tree: HTMLParser) -> int | None:
        text = self._get_info_text(tree)
        if not text:
            return None
        m = re.search(r"収録時間\s*:\s*(\d+)\s*minutes?", text)
        return int(m.group(1)) if m else None

    def _parse_rating(self, tree: HTMLParser) -> float | None:
        text = self._get_info_text(tree)
        if not text:
            return None
        m = re.search(r"(?:Rating|平均評価)\s*:\s*([\d.]+)", text)
        return float(m.group(1)) if m else None

    def _parse_genres(self, tree: HTMLParser) -> list[str]:
        genres: list[str] = []
        info_div = tree.css_first("div.col-md-9")
        if not info_div:
            return genres
        for a in info_div.css('a[href^="/genre/"]'):
            text = a.text(strip=True)
            if text and text not in genres:
                genres.append(text)
        return genres

    def _parse_actors(self, tree: HTMLParser) -> list[Actor]:
        actors: list[Actor] = []
        info_div = tree.css_first("div.col-md-9")
        if not info_div:
            return actors
        for a in info_div.css('a[href*="/star/"]'):
            name = a.text(strip=True)
            if name:
                actors.append(Actor(name=name))
        if not actors:
            text = self._get_info_text(tree)
            if not text:
                return actors
            m = re.search(
                r"(?:Stars|出演者)\s*:\s*(.+?)(?:\s+(?:Studio|メーカー)|$)", text
            )
            if m:
                name = m.group(1).strip().rstrip(",")
                if name:
                    actors.append(Actor(name=name))
        return actors

    def _parse_studio(self, tree: HTMLParser) -> str | None:
        info_div = tree.css_first("div.col-md-9")
        if info_div:
            company_a = info_div.css_first('a[href*="/company/"]')
            if company_a:
                return company_a.text(strip=True)
        text = self._get_info_text(tree)
        if text:
            m = re.search(r"(?:Studio|メーカー)\s*:\s*(.+?)(?:\s+SN|品番|$)", text)
            if m:
                return m.group(1).strip()
        return None

    def _parse_images(
        self, tree: HTMLParser, base_url: str
    ) -> tuple[list[str], list[str]]:
        posters: list[str] = []
        art: list[str] = []

        poster_img = tree.css_first("div.panel-body div.row div.col-md-3 img")
        if poster_img:
            url = self._get_img_url(poster_img, base_url)
            if url:
                posters.append(url)

        sidebar = tree.css_first(".col-md-7.col-md-offset-1 + .col-md-3")
        if not sidebar:
            sidebar = tree.css_first(".col-md-3:last-child")
        if sidebar:
            for img_node in sidebar.css("img"):
                url = self._get_img_url(img_node, base_url)
                if url and url not in art:
                    art.append(url)

        if not art and posters:
            art.append(posters[0])

        posters.sort()
        art.sort()
        return posters, art

    def _get_info_text(self, tree: HTMLParser) -> str | None:
        info_div = tree.css_first("div.col-md-9")
        if not info_div:
            return None
        text = info_div.text(strip=True, separator=" ")
        return re.sub(r"\s+", " ", text).strip()

    def _get_img_url(self, node, base_url: str) -> str | None:
        for attr in ("data-original", "src"):
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

        not_found = tree.css_first(".alert.alert-danger")
        if not_found:
            return []

        if tree.css_first("div.panel-heading h3"):
            return self._parse_single_video_result(tree, base_url)

        results: list[SearchResult] = []
        for item in tree.css("div.thumbnail"):
            link = item.css_first("a[href^='/video/']")
            if not link:
                continue
            href = link.attributes.get("href")
            if not href:
                continue
            video_url = self._abspath_url(href, base_url)
            title_text = link.text(strip=True) or ""
            number_match = re.search(r"(\S+-\d+)", title_text)
            number_text = number_match.group(1) if number_match else None
            img = link.css_first("img")
            poster_url = None
            if img:
                poster_url = self._get_img_url(img, base_url)
            results.append(
                SearchResult(
                    title=title_text,
                    number=number_text,
                    url=video_url,
                    poster_url=poster_url,
                )
            )

        seen = set()
        unique_results: list[SearchResult] = []
        for r in results:
            if r.url not in seen:
                seen.add(r.url)
                unique_results.append(r)
        return unique_results

    def _parse_single_video_result(
        self, tree: HTMLParser, base_url: str
    ) -> list[SearchResult]:
        h3 = tree.css_first("div.panel-heading h3")
        if not h3:
            return []
        title_main = self._parse_title(tree)
        number = self._parse_number(tree)
        small = h3.css_first("small")
        small_text = small.text(strip=True) if small else ""
        small_number = small_text.split()[0] if small_text else None
        full_title = (
            f"{number} {title_main}"
            if number and title_main
            else title_main or "Unknown Title"
        )

        poster_url = None
        poster_img = tree.css_first("div.panel-body div.row div.col-md-3 img")
        if poster_img:
            poster_url = self._get_img_url(poster_img, base_url)

        return [
            SearchResult(
                title=full_title,
                number=number or small_number,
                url=base_url,
                poster_url=poster_url,
            )
        ]
