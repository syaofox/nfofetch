from __future__ import annotations

from app.config import Settings
from app.schemas import MovieMetadata
from app.scrapers.registry import get_scraper


def scrape_movie(url: str, settings: Settings) -> MovieMetadata:
    """根据 URL 选择合适的站点 scraper 并执行刮削。"""
    scraper = get_scraper(url)
    return scraper.scrape(url, settings=settings)

