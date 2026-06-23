from __future__ import annotations

from app.scrapers.base import BaseScraper
from app.scrapers.jav321 import Jav321Scraper
from app.scrapers.javdb import JavdbScraper
from app.scrapers.javhoo import JavhooScraper


SCRAPERS: list[BaseScraper] = [
    JavdbScraper(),
    Jav321Scraper(),
    JavhooScraper(),
]


class NoSupportedScraperError(RuntimeError):
    """没有找到能够处理给定 URL 的 scraper。"""


def get_scraper(url: str) -> BaseScraper:
    """根据 URL 选择合适的站点 scraper。"""
    for scraper in SCRAPERS:
        if scraper.supports(url):
            return scraper
    raise NoSupportedScraperError(f"没有找到能处理该 URL 的 scraper: {url}")


def get_default_scraper() -> BaseScraper:
    """获取默认的 scraper 用于搜索等操作。"""
    return SCRAPERS[0]
