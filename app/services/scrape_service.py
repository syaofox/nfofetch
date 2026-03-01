from __future__ import annotations

from urllib.parse import urlparse

from app.config import Settings
from app.schemas import MovieMetadata, SearchResult
from app.scrapers.registry import get_default_scraper, get_scraper


def is_url(text: str) -> bool:
    """判断输入是 URL 还是搜索关键字。"""
    try:
        result = urlparse(text)
        return bool(result.scheme and result.netloc)
    except Exception:
        return False


def search_movie(query: str, settings: Settings) -> list[SearchResult]:
    """根据关键字搜索影片。"""
    scraper = get_default_scraper()
    return scraper.search(query, settings=settings)


def scrape_movie(url: str, settings: Settings) -> MovieMetadata:
    """根据 URL 选择合适的站点 scraper 并执行刮削。"""
    scraper = get_scraper(url)
    return scraper.scrape(url, settings=settings)
