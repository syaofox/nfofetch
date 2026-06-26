from __future__ import annotations

import asyncio
import json
import logging
import re
import urllib.parse
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import urljoin, urlparse

from selectolax.parser import HTMLParser

from app.config import Settings
from app.schemas import Actor, MovieMetadata, SearchResult
from app.scrapers.base import BaseScraper

try:
    from playwright.sync_api import sync_playwright

    _HAS_PLAYWRIGHT = True
except ImportError:  # pragma: no cover
    _HAS_PLAYWRIGHT = False

logger = logging.getLogger(__name__)

_CID_RE = re.compile(r"(?:cid=|id=)([a-z0-9_]+)", re.IGNORECASE)


class DmmScraper(BaseScraper):
    """DMM / FANZA (dmm.co.jp) 站点刮削实现。

    - 搜索：www.dmm.co.jp （全站搜索，结果更全）
    - 详情页：video.dmm.co.jp （Playwright 渲染 JS）
    解析策略基于页面文本中的稳定标签（如「配信開始日」「収録時間」等）。
    """

    name = "dmm"

    def supports(self, url: str) -> bool:
        parsed = urlparse(url)
        host = parsed.netloc.lower()
        return "dmm.co.jp" in host or "dmm.com" in host

    _PW_EXECUTOR = ThreadPoolExecutor(max_workers=1, thread_name_prefix="playwright")

    def _request_page(
        self, url: str, settings: Settings, timeout: int | None = None
    ) -> str:
        """使用 Playwright 无头浏览器渲染 DMM 页面（Next.js 需要 JS 执行）。

        Playwright Sync API 不能在 asyncio 事件循环中直接使用，因此在
        检测到事件循环时自动切换到线程池执行。
        """
        if not _HAS_PLAYWRIGHT:
            raise RuntimeError(
                "DMM 刮削需要 Playwright。请运行: uv sync && uv run playwright install chromium"
            )

        def _run() -> str:
            with sync_playwright() as p:
                browser = p.chromium.launch(
                    headless=True,
                    args=[
                        "--no-sandbox",
                        "--disable-setuid-sandbox",
                        "--disable-dev-shm-usage",
                        "--disable-gpu",
                    ],
                )
                try:
                    timeout_ms = (timeout or settings.http_timeout) * 1000
                    context = browser.new_context(
                        user_agent=settings.user_agent,
                        locale="ja-JP",
                        timezone_id="Asia/Tokyo",
                    )
                    if settings.dmm_cookie:
                        for pair in settings.dmm_cookie.split(";"):
                            pair = pair.strip()
                            if "=" in pair:
                                name, value = pair.split("=", 1)
                                context.add_cookies(
                                    [
                                        {
                                            "name": name.strip(),
                                            "value": value.strip(),
                                            "domain": ".dmm.co.jp",
                                            "path": "/",
                                        }
                                    ]
                                )
                    if settings.http_proxy:
                        context.set_default_navigation_timeout(timeout_ms)

                    page = context.new_page()
                    page.goto(url, wait_until="domcontentloaded", timeout=timeout_ms)

                    try:
                        page.wait_for_selector(
                            "text=配信開始日",
                            timeout=min(timeout_ms or 30000, 20000),
                        )
                    except Exception:
                        logger.warning("DMM: 等待 配信開始日 超时，内容可能不完整")

                    page.wait_for_timeout(3000)
                    return page.content()
                finally:
                    browser.close()

        try:
            asyncio.get_running_loop()
            # 在事件循环中 → 使用线程池
            future = self._PW_EXECUTOR.submit(_run)
            return future.result()
        except RuntimeError:
            # 没有事件循环 → 直接运行
            return _run()

    def _extract_cid(self, url: str) -> str | None:
        """从 URL 中提取 content ID。"""
        m = _CID_RE.search(url)
        if m:
            return m.group(1).lower()
        return None

    def scrape(self, url: str, settings: Settings) -> MovieMetadata:
        raw_html = self._request_page(url, settings)
        tree = HTMLParser(raw_html)
        self._validate_content_page(tree, url)
        product_data = self._get_next_product_data(tree)
        metadata = self._parse_metadata(
            tree, base_url=url, raw_html=raw_html, product_data=product_data
        )
        metadata.source_url = url  # type: ignore[assignment]
        return metadata

    def search(self, query: str, settings: Settings) -> list[SearchResult]:
        """搜索影片，使用 www.dmm.co.jp 全站搜索。"""
        url = (
            "https://www.dmm.co.jp/search/"
            f"/=/searchstr={urllib.parse.quote(query)}/limit=30/sort=rankprofile/"
        )
        html = self._request_page(url, settings)
        return self._parse_search_results(html, base_url=url)

    @staticmethod
    def _extract_next_data(tree: HTMLParser) -> dict | None:
        """从 Next.js 页面提取 __NEXT_DATA__ JSON。"""
        script = tree.css_first("script#__NEXT_DATA__")
        if script is None:
            return None
        raw = script.text(strip=True)
        if not raw:
            return None
        try:
            return json.loads(raw)
        except (json.JSONDecodeError, ValueError):
            return None

    @staticmethod
    def _get_next_data_props(tree: HTMLParser) -> dict | None:
        """从 __NEXT_DATA__ 中提取 pageProps 或 props。"""
        data = DmmScraper._extract_next_data(tree)
        if data is None:
            return None
        props = data.get("props") or {}
        page_props = props.get("pageProps") or {}
        if page_props:
            return page_props
        return props

    @staticmethod
    def _get_next_product_data(tree: HTMLParser) -> dict | None:
        """从 Next.js __NEXT_DATA__ 中提取影片商品数据。"""
        props = DmmScraper._get_next_data_props(tree)
        if props is None:
            return None
        product = (
            props.get("product") or props.get("content") or props.get("video") or {}
        )
        if product:
            return product
        return props

    def _validate_content_page(self, tree: HTMLParser, url: str) -> None:
        """检查页面是否为有效的 DMM 影片详情页。

        仅检查明显的错误/拦截页面，不校验具体标签（DMM Next.js 页面内容
        可能在 JS 渲染后才会出现，服务器返回的 HTML 可能不含完整标签）。
        """
        body = tree.body
        page_text = body.text(strip=True) if body is not None else ""

        if "404" in page_text and "Not Found" in page_text:
            cid = self._extract_cid(url) or "unknown"
            raise ValueError(f"DMM 上未找到该影片 (CID: {cid})，页面返回 404。")

        if "年齢認証" in page_text or ("18歳" in page_text and "はい" in page_text):
            raise ValueError(
                "DMM 返回了年龄验证页面。请确保 DMM Cookie 中包含 'age_check_done=1'。"
            )

        # DMM 页面始终显示ログイン按钮，即使已登录，不拦截

    @staticmethod
    def _strip_html(html: str) -> str:
        """去除 HTML 标签并保留块级元素间的换行结构。"""
        text = re.sub(
            r"<script[^>]*>.*?</script>", "", html, flags=re.DOTALL | re.IGNORECASE
        )
        text = re.sub(
            r"<style[^>]*>.*?</style>", "", text, flags=re.DOTALL | re.IGNORECASE
        )
        text = re.sub(r"<br\s*/?>", "\n", text, flags=re.IGNORECASE)
        text = re.sub(
            r"</(div|p|li|h[1-6]|tr|section|header|footer|nav)>",
            "\n",
            text,
            flags=re.IGNORECASE,
        )
        text = re.sub(r"<[^>]+>", " ", text)
        text = re.sub(r"[ \t]+", " ", text)
        text = re.sub(r"\n\s*\n+", "\n", text)
        return text.strip()

    def _parse_metadata(
        self,
        tree: HTMLParser,
        base_url: str,
        raw_html: str | None = None,
        product_data: dict | None = None,
    ) -> MovieMetadata:
        page_text = (
            self._strip_html(raw_html)
            if raw_html
            else (tree.text(strip=False) if tree.body else "")
        )

        number = self._parse_number(page_text, raw_html=raw_html)
        main_title = self._parse_title(tree, number, raw_html=raw_html)
        if number and main_title:
            title = f"{number} {main_title}"
        else:
            title = main_title or number or "Unknown Title"

        premiered = self._parse_premiered(page_text)
        runtime = self._parse_runtime(page_text)
        genres = self._parse_genres(page_text)
        actors = self._parse_actors(page_text)
        studio, label, series = self._parse_companies(page_text)
        rating = self._parse_rating(page_text)
        posters, art = self._parse_images(tree, base_url)

        plot = self._parse_plot(page_text)

        return MovieMetadata(
            title=title,
            original_title=None,
            number=number,
            plot=plot,
            year=int(premiered.split("-")[0])
            if premiered and "-" in premiered
            else None,
            premiered=premiered,
            releasedate=premiered,
            runtime=runtime,
            genres=genres,
            tags=[],
            actors=actors,
            studio=studio,
            label=label,
            series=series,
            directors=[],
            rating=rating,
            posters=posters,  # type: ignore[arg-type]
            art=art,  # type: ignore[arg-type]
        )

    # ---- 字段解析方法（基于页面文本标签） ----

    def _parse_title(
        self, tree: HTMLParser, number: str | None, raw_html: str | None = None
    ) -> str | None:
        title_text: str | None = None

        title_tag = tree.css_first("title")
        if title_tag:
            title_text = title_tag.text(strip=True)

        if not title_text and raw_html:
            m = re.search(
                r"<title[^>]*>(.*?)</title>", raw_html, re.DOTALL | re.IGNORECASE
            )
            if m:
                title_text = m.group(1).strip()

        if not title_text and tree.body:
            for sel in ("h1", "h2"):
                node = tree.css_first(sel)
                if node and node.text(strip=True):
                    title_text = node.text(strip=True)
                    break

        if not title_text:
            return None

        sep = "｜"
        if sep in title_text:
            title_text = title_text.split(sep)[0]

        if number and title_text:
            title_text = re.sub(
                re.escape(number) + r"\s*", "", title_text, count=1
            ).strip()

        return title_text or None

    def _parse_number(self, page_text: str, raw_html: str | None = None) -> str | None:
        _text = page_text or raw_html or ""
        # メーカー品番优先（如 KAVR-501），配信品番（如 kavr00501）作为兜底
        m = re.search(r"メーカー品番[：:]\s*([a-zA-Z0-9_\-]+)", _text)
        if m:
            return m.group(1).strip()
        m = re.search(r"配信品番[：:]\s*([a-zA-Z0-9_\-]+)", _text)
        if m:
            return m.group(1).strip()
        return None

    def _parse_premiered(self, page_text: str) -> str | None:
        for label in ("配信開始日", "商品発売日"):
            m = re.search(
                re.escape(label) + r"[：:]\s*(\d{4})/(\d{2})/(\d{2})", page_text
            )
            if m:
                return f"{m.group(1)}-{m.group(2)}-{m.group(3)}"
        return None

    def _parse_runtime(self, page_text: str) -> int | None:
        m = re.search(r"収録時間[：:]\s*(\d+)分", page_text)
        if m:
            try:
                return int(m.group(1))
            except ValueError:
                return None
        return None

    def _parse_genres(self, page_text: str) -> list[str]:
        genres: list[str] = []
        in_genres = False
        next_labels = (
            "配信品番",
            "メーカー品番",
            "平均評価",
            "お気に入り登録数",
            "対応デバイス",
            "コンテンツタイプ",
        )
        for line in page_text.split("\n"):
            line_stripped = line.strip()
            if "ジャンルから探す" in line_stripped or "ジャンル一覧" in line_stripped:
                continue
            if "ジャンル" in line_stripped and "：" in line_stripped:
                in_genres = True
                # Genres might be on the same line after ジャンル：
                after_label = re.sub(r"^.*?ジャンル[：:]\s*", "", line_stripped)
                if after_label:
                    for g in after_label.split():
                        if g and g not in genres:
                            genres.append(g)
                continue
            if in_genres:
                if line_stripped and any(
                    line_stripped.startswith(lb) for lb in next_labels
                ):
                    break
                if line_stripped and line_stripped not in genres:
                    genres.append(line_stripped)
        return genres

    def _parse_actors(self, page_text: str) -> list[Actor]:
        actors: list[Actor] = []
        m = re.search(
            r"出演者[：:][\s　]*\n([\s\S]+?)(?=\n\n|\n\S+[：:]|\Z)", page_text
        )
        if not m:
            m = re.search(r"出演者[：:][\s　]*(.+?)(?=\s*[^\s]+\s*：)", page_text)
        if m:
            raw = m.group(1)
            for name in re.findall(r"[^\s　]+", raw.strip()):
                name_clean = name.strip("、，,")
                if name_clean:
                    actors.append(Actor(name=name_clean))
        return actors

    def _parse_companies(
        self, page_text: str
    ) -> tuple[str | None, str | None, str | None]:
        studio: str | None = None
        label: str | None = None
        series: str | None = None

        m = re.search(r"メーカー[：:]\s*([^\n]+)", page_text)
        if m:
            studio = m.group(1).strip()

        m = re.search(r"レーベル[：:]\s*([^\n]+)", page_text)
        if m:
            label = m.group(1).strip()

        m = re.search(r"シリーズ[：:]\s*([^\n]+)", page_text)
        if m:
            series = m.group(1).strip()

        return studio, label, series

    def _parse_rating(self, page_text: str) -> float | None:
        for pat in (r"平均評価[：:][\s　]*([\d.]+)", r"平均評価[\s　]*([\d.]+)点"):
            m = re.search(pat, page_text)
            if m:
                try:
                    return float(m.group(1))
                except ValueError:
                    return None
        return None

    def _parse_plot(self, page_text: str) -> str | None:
        lines = page_text.split("\n")
        plot_parts: list[str] = []
        in_plot = False
        for i, line in enumerate(lines):
            if re.search(r"出演者[：:]", line):
                in_plot = True
                continue
            if in_plot and re.search(r"[：:]\s*----", line):
                continue
            if in_plot and re.search(r"シリーズ[：:]", line):
                continue
            if in_plot and re.search(r"メーカー[：:]", line):
                continue
            if in_plot and re.search(r"レーベル[：:]", line):
                continue
            if in_plot and re.search(r"コンテンツタイプ[：:]", line):
                continue
            if in_plot and re.search(r"ジャンル[：:]", line):
                continue
            if in_plot and re.search(r"配信品番[：:]", line):
                continue
            if in_plot and re.search(r"メーカー品番[：:]", line):
                continue
            if in_plot and re.search(r"平均評価[：:]", line):
                continue
            if in_plot and re.search(r"お気に入り登録数", line):
                continue
            if in_plot and re.search(r"対応デバイス", line):
                continue
            if in_plot and re.search(r"※この商品", line):
                continue
            if in_plot and re.search(r"ご購入はこちらから", line):
                continue
            if in_plot and re.search(r"サンプル画像", line):
                continue
            if in_plot and re.search(r"出演者をお気に入り", line):
                continue
            if in_plot and re.search(r"視聴できるデバイス", line):
                continue
            if in_plot and re.search(r"ポストする", line):
                continue
            if in_plot and re.search(r"この商品に出演しているAV女優", line):
                break

            if in_plot and line.strip() and len(line.strip()) > 5:
                plot_parts.append(line.strip())

        if plot_parts:
            return "\n".join(plot_parts)

        return None

    @staticmethod
    def _clean_img_url(url: str) -> str:
        """去掉 DMM 图片 URL 的查询参数（尺寸/质量裁剪参数）。"""
        parsed = urlparse(url)
        path = parsed.path
        if parsed.hostname and "dmm.co.jp" in parsed.hostname:
            return f"{parsed.scheme}://{parsed.hostname}{path}"
        return url

    def _parse_images(
        self, tree: HTMLParser, base_url: str
    ) -> tuple[list[str], list[str]]:
        posters: list[str] = []
        art: list[str] = []

        cid_str = ""
        cid_match = _CID_RE.search(base_url)
        if cid_match:
            cid_str = cid_match.group(1)

        # 1. 从 <a> 标签 href 收集样本大图（jp-*.jpg）
        for a in tree.css("a[href]"):
            href = a.attributes.get("href") or ""
            if cid_str and cid_str in href and "jp-" in href and href.endswith(".jpg"):
                url = self._clean_img_url(self._abspath_url(href, base_url))
                if url not in art:
                    art.append(url)

        # 2. 从 <img> 标签 src 收集封面和样本缩略图
        for img in tree.css("img"):
            src = img.attributes.get("src") or ""
            if not cid_str:
                continue
            # pl.jpg = 大封面（用作 poster）
            if "pl.jpg" in src and cid_str in src:
                if not posters:
                    url = self._clean_img_url(self._abspath_url(src, base_url))
                    posters.append(url)
            # -N.jpg = 样本缩略图（去参后对应 jp-N.jpg）
            # jp-N.jpg = 样本大图（已在 <a> href 中收集）

        # 3. 兜底：用 pl.jpg 作为 poster
        if not posters and cid_str:
            url = f"https://pics.dmm.co.jp/digital/video/{cid_str}/{cid_str}pl.jpg"
            posters.append(url)

        # 4. 兜底：从 <img> 找最大图作 poster
        if not posters:
            for img in tree.css("img"):
                src = img.attributes.get("src") or ""
                clean = self._clean_img_url(src)
                if cid_str and cid_str in clean and clean.endswith(".jpg"):
                    url = self._abspath_url(src, base_url)
                    posters.append(self._clean_img_url(url))
                    break

        if not art and posters:
            art.append(posters[0])

        posters.sort()
        art.sort()
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

    @staticmethod
    def _find_search_poster(a) -> str | None:
        """从搜索结果项向上遍历找到产品缩略图 URL。"""
        seen: set[str] = set()
        node = a
        for _ in range(6):
            if node is None:
                break
            for img in node.css("img"):
                src = img.attributes.get("src") or ""
                if "dmm.co.jp" in src and ("pics_dig" in src or "ps.jpg" in src):
                    clean = re.sub(r"\?.*$", "", src)
                    if clean not in seen:
                        seen.add(clean)
                        return clean
            node = node.parent
        return None

    def _parse_search_results(self, html: str, base_url: str) -> list[SearchResult]:
        """解析搜索结果，兼容旧站（cid=）和新站（content/?id=）格式。"""
        tree = HTMLParser(html)
        seen_urls: set[str] = set()
        results: list[SearchResult] = []

        # 旧站：a[href*="cid="]
        for a in tree.css('a[href*="cid="]'):
            href = a.attributes.get("href") or ""
            m = re.search(r"cid=([a-z0-9_]+)", href, re.I)
            if not m:
                continue
            raw_cid = m.group(1).lower()
            title = (a.text(strip=True) or "").strip()
            if not title or len(title) < 5:
                continue
            content_url = (
                f"https://video.dmm.co.jp/av/content/?id={raw_cid}"
            )
            if content_url in seen_urls:
                continue
            seen_urls.add(content_url)
            number = self._cid_to_number(raw_cid)
            poster_url = self._find_search_poster(a)
            results.append(SearchResult(
                title=title, number=number, url=content_url, poster_url=poster_url,
            ))

        # 新站：a[href*="content/?id="]
        for a in tree.css('a[href*="content/?id="]'):
            href = a.attributes.get("href") or ""
            title = a.text(strip=True) or ""
            if not title:
                continue
            video_url = href if href.startswith("http") else self._abspath_url(href, base_url)
            if video_url in seen_urls:
                continue
            seen_urls.add(video_url)
            cid_match = re.search(r"content/\?id=([a-z0-9_]+)", href)
            number = self._cid_to_number(cid_match.group(1)) if cid_match else None
            poster_url = self._find_search_poster(a)
            results.append(SearchResult(
                title=title, number=number, url=video_url, poster_url=poster_url,
            ))

        return results

    @staticmethod
    def _cid_to_number(cid: str) -> str:
        """将 DMM CID（kavr00501）转为番号（KAVR-501）。

        数字去除前导零后至少保留 3 位（如 00051→051），
        尾部字母后缀（如 5421ksd051r 的 r）自动忽略。
        """
        m = re.search(r"([A-Za-z]+)(\d+)[A-Za-z]*$", cid)
        if m:
            num = str(int(m.group(2))).zfill(3)
            return f"{m.group(1)}-{num}".upper()
        m = re.search(r"([A-Za-z]+)(\d+)", cid)
        if m:
            num = str(int(m.group(2))).zfill(3)
            return f"{m.group(1)}-{num}".upper()
        return cid.upper()
