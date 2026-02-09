from __future__ import annotations

from typing import List

from app.scrapers.base import BaseScraper
from app.scrapers.javdb import JavdbScraper


SCRAPERS: List[BaseScraper] = [
    JavdbScraper(),
]


class NoSupportedScraperError(RuntimeError):
    """没有找到能够处理给定 URL 的 scraper。"""


def get_scraper(url: str) -> BaseScraper:
    """根据 URL 选择合适的站点 scraper。"""
    for scraper in SCRAPERS:
        if scraper.supports(url):
            return scraper
    raise NoSupportedScraperError(f"暂不支持该 URL: {url}")

