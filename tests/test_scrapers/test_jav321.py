from __future__ import annotations

from app.scrapers.jav321 import Jav321Scraper


class TestJav321Supports:
    def setup_method(self) -> None:
        self.scraper = Jav321Scraper()

    def test_en_jav321_com(self) -> None:
        assert self.scraper.supports("https://en.jav321.com/video/sone00614") is True

    def test_jp_jav321_com(self) -> None:
        assert self.scraper.supports("https://jp.jav321.com/video/sone00614") is True

    def test_www_jav321_com(self) -> None:
        assert self.scraper.supports("https://www.jav321.com/video/sone00614") is True

    def test_tw_jav321_com(self) -> None:
        assert self.scraper.supports("https://tw.jav321.com/video/sone00614") is True

    def test_non_jav321_url(self) -> None:
        assert self.scraper.supports("https://example.com/movie") is False

    def test_jav321_not_video_page(self) -> None:
        assert self.scraper.supports("https://www.jav321.com/search") is False

    def test_jav321_other_path(self) -> None:
        assert self.scraper.supports("https://www.jav321.com/genre_list") is False

    def test_missing_host(self) -> None:
        assert self.scraper.supports("not-a-url") is False

    def test_javdb_url_not_confused(self) -> None:
        assert self.scraper.supports("https://javdb.com/v/abcdef") is False

    def test_best_seller_not_match(self) -> None:
        assert (
            self.scraper.supports("https://en.jav321.com/best_seller/1/2025/1") is False
        )
