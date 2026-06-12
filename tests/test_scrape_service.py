from __future__ import annotations

from app.services.scrape_service import is_url


class TestIsUrl:
    def test_http_url(self) -> None:
        assert is_url("http://example.com") is True

    def test_https_url(self) -> None:
        assert is_url("https://javdb.com/v/abcdef") is True

    def test_url_with_path(self) -> None:
        assert is_url("https://example.com/path/to/page") is True

    def test_search_keyword(self) -> None:
        assert is_url("ABP-123") is False

    def test_search_with_spaces(self) -> None:
        assert is_url("田中丽奈 作品") is False

    def test_empty_string(self) -> None:
        assert is_url("") is False

    def test_number_only(self) -> None:
        assert is_url("12345") is False
