from __future__ import annotations

import concurrent.futures
from urllib.parse import urlparse

from app.config import Settings
from app.schemas import MovieMetadata, SearchResult
from app.scrapers.registry import SCRAPERS, NoSupportedScraperError, get_scraper


def is_url(text: str) -> bool:
    """判断输入是 URL 还是搜索关键字。"""
    try:
        result = urlparse(text)
        return bool(result.scheme and result.netloc)
    except Exception:
        return False


def search_movie(query: str, settings: Settings) -> list[SearchResult]:
    """并行搜索所有支持的站点，结果合并后去重返回。"""
    results: list[SearchResult] = []

    def _search(scraper) -> list[SearchResult]:
        items = scraper.search(query, settings=settings)
        for item in items:
            item.source = scraper.name
        return items

    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as executor:
        future_to_scraper = {
            executor.submit(_search, scraper): scraper for scraper in SCRAPERS
        }
        for future in concurrent.futures.as_completed(future_to_scraper):
            try:
                results.extend(future.result())
            except Exception:
                pass

    seen = set()
    unique: list[SearchResult] = []
    for r in results:
        if r.url not in seen:
            seen.add(r.url)
            unique.append(r)
    return unique


def scrape_movie(url: str, settings: Settings) -> MovieMetadata:
    """根据 URL 选择合适的站点 scraper 并执行刮削。"""
    try:
        scraper = get_scraper(url)
    except NoSupportedScraperError as e:
        raise ValueError(str(e)) from e
    return scraper.scrape(url, settings=settings)
