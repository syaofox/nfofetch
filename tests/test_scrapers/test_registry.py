from __future__ import annotations

from app.scrapers.jav321 import Jav321Scraper
from app.scrapers.javdb import JavdbScraper
from app.scrapers.registry import SCRAPERS, get_default_scraper, get_scraper


class TestScrapers:
    def test_scrapers_list_not_empty(self) -> None:
        assert len(SCRAPERS) >= 1

    def test_first_scraper_is_javdb(self) -> None:
        assert isinstance(SCRAPERS[0], JavdbScraper)

    def test_second_scraper_is_jav321(self) -> None:
        assert isinstance(SCRAPERS[1], Jav321Scraper)


class TestGetScraper:
    def test_returns_javdb_for_javdb_url(self) -> None:
        scraper = get_scraper("https://javdb.com/v/abcdef")
        assert isinstance(scraper, JavdbScraper)

    def test_returns_javdb_for_mirror_domain(self) -> None:
        scraper = get_scraper("https://javdb565.com/v/abcdef")
        assert isinstance(scraper, JavdbScraper)

    def test_returns_jav321_for_jav321_url(self) -> None:
        scraper = get_scraper("https://en.jav321.com/video/sone00614")
        assert isinstance(scraper, Jav321Scraper)


class TestGetDefaultScraper:
    def test_returns_javdb(self) -> None:
        scraper = get_default_scraper()
        assert isinstance(scraper, JavdbScraper)
