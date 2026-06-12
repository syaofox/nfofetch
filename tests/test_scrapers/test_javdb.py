from __future__ import annotations

from app.scrapers.javdb import JavdbScraper


class TestJavdbSupports:
    def setup_method(self) -> None:
        self.scraper = JavdbScraper()

    def test_javdb_com(self) -> None:
        assert self.scraper.supports("https://javdb.com/v/abcdef") is True

    def test_javdb_mirror(self) -> None:
        assert self.scraper.supports("https://javdb565.com/v/abcdef") is True

    def test_non_javdb_url(self) -> None:
        assert self.scraper.supports("https://example.com/movie") is False

    def test_javdb_not_video_page(self) -> None:
        assert self.scraper.supports("https://javdb.com/search?q=test") is False

    def test_missing_host(self) -> None:
        assert self.scraper.supports("not-a-url") is False
