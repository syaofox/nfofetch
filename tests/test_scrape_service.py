from __future__ import annotations

from app.config import Settings
from app.scrapers.registry import SCRAPERS
from app.services.scrape_service import is_url, search_movie
from app.schemas import SearchResult


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


def test_search_movie_merges_results_from_multiple_scrapers() -> None:
    """验证 search_movie 会合并多个 scraper 的搜索结果并去重。"""
    settings = Settings(user_agent="t", http_proxy=None, javdb_cookie=None)
    original = list(SCRAPERS)

    class ScraperA:
        name = "alpha"

        def search(self, query, settings):
            return [
                SearchResult(title="AAA", url="https://a.com/v/1", number="A-001"),
            ]

    class ScraperB:
        name = "beta"

        def search(self, query, settings):
            return [
                SearchResult(title="BBB", url="https://b.com/v/1", number="B-001"),
            ]

    try:
        SCRAPERS[:] = [ScraperA(), ScraperB()]  # type: ignore[list-item]
        results = search_movie("test", settings=settings)
        assert len(results) == 2
        urls = {r.url for r in results}
        assert "https://a.com/v/1" in urls
        assert "https://b.com/v/1" in urls
    finally:
        SCRAPERS[:] = original


def test_search_movie_deduplicates_by_url() -> None:
    """验证相同 URL 的结果会被去重。"""
    settings = Settings(user_agent="t", http_proxy=None, javdb_cookie=None)
    original = list(SCRAPERS)

    class DupScraper1:
        name = "src1"

        def search(self, query, settings):
            return [SearchResult(title="A", url="https://same.url", number="X-001")]

    class DupScraper2:
        name = "src2"

        def search(self, query, settings):
            return [SearchResult(title="A", url="https://same.url", number="X-001")]

    try:
        SCRAPERS[:] = [DupScraper1(), DupScraper2()]  # type: ignore[list-item]
        results = search_movie("test", settings=settings)
        assert len(results) == 1
    finally:
        SCRAPERS[:] = original


def test_search_movie_sets_source_label() -> None:
    """验证每个结果都带有正确的 source 标签。"""
    settings = Settings(user_agent="t", http_proxy=None, javdb_cookie=None)
    original = list(SCRAPERS)

    class LabelScraper:
        name = "test_label"

        def search(self, query, settings):
            return [SearchResult(title="X", url="https://x.com/v/1", number="X-001")]

    try:
        SCRAPERS[:] = [LabelScraper()]  # type: ignore[list-item]
        results = search_movie("test", settings=settings)
        assert len(results) == 1
        assert results[0].source == "test_label"
    finally:
        SCRAPERS[:] = original


def test_search_movie_handles_scraper_exception_gracefully() -> None:
    """验证单个 scraper 抛出异常不影响其他 scraper 的结果。"""
    settings = Settings(user_agent="t", http_proxy=None, javdb_cookie=None)
    original = list(SCRAPERS)

    class FailingScraper:
        name = "fail"

        def search(self, query, settings):
            raise RuntimeError("search failed")

    class GoodScraper:
        name = "good"

        def search(self, query, settings):
            return [SearchResult(title="OK", url="https://ok.com/v/1", number="OK-001")]

    try:
        SCRAPERS[:] = [FailingScraper(), GoodScraper()]  # type: ignore[list-item]
        results = search_movie("test", settings=settings)
        assert len(results) == 1
        assert results[0].source == "good"
        assert results[0].title == "OK"
    finally:
        SCRAPERS[:] = original


def test_search_movie_no_results_returns_empty() -> None:
    """验证所有 scraper 都返回空结果时返回空列表。"""
    settings = Settings(user_agent="t", http_proxy=None, javdb_cookie=None)
    original = list(SCRAPERS)

    class EmptyScraper:
        name = "empty"

        def search(self, query, settings):
            return []

    try:
        SCRAPERS[:] = [EmptyScraper()]  # type: ignore[list-item]
        results = search_movie("test", settings=settings)
        assert results == []
    finally:
        SCRAPERS[:] = original
