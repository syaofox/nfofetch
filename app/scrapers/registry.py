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


def get_enabled_scrapers(enabled_names: set[str] | None = None) -> list[BaseScraper]:
    """返回启用的 scraper 列表。enabled_names 为 None 时返回全部。"""
    if enabled_names is None:
        return list(SCRAPERS)
    return [s for s in SCRAPERS if s.name in enabled_names]


def get_scraper(url: str, enabled_names: set[str] | None = None) -> BaseScraper:
    """根据 URL 选择合适的站点 scraper（仅在启用的 scraper 中查找）。"""
    candidates = get_enabled_scrapers(enabled_names)
    for scraper in candidates:
        if scraper.supports(url):
            return scraper
    raise NoSupportedScraperError(
        f"没有找到能处理该 URL 的 scraper（当前启用的站点：{enabled_names or '全部'}）"
    )


def get_default_scraper() -> BaseScraper:
    """获取默认的 scraper 用于搜索等操作。"""
    return SCRAPERS[0]
