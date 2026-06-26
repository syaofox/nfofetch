from __future__ import annotations

import pytest
from app.scrapers.dmm import DmmScraper
from app.scrapers.jav321 import Jav321Scraper
from app.scrapers.javdb import JavdbScraper
from app.scrapers.javhoo import JavhooScraper
from app.scrapers.registry import (
    SCRAPERS,
    NoSupportedScraperError,
    get_default_scraper,
    get_enabled_scrapers,
    get_scraper,
)


class TestScrapers:
    def test_scrapers_list_not_empty(self) -> None:
        assert len(SCRAPERS) >= 1

    def test_first_scraper_is_javdb(self) -> None:
        assert isinstance(SCRAPERS[0], JavdbScraper)

    def test_second_scraper_is_jav321(self) -> None:
        assert isinstance(SCRAPERS[1], Jav321Scraper)

    def test_third_scraper_is_javhoo(self) -> None:
        assert isinstance(SCRAPERS[2], JavhooScraper)

    def test_fourth_scraper_is_dmm(self) -> None:
        assert isinstance(SCRAPERS[3], DmmScraper)


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

    def test_returns_javhoo_for_javhoo_url(self) -> None:
        scraper = get_scraper("https://www.javhoo.com/en/ABF-360")
        assert isinstance(scraper, JavhooScraper)

    def test_returns_dmm_for_dmm_url(self) -> None:
        scraper = get_scraper(
            "https://www.dmm.co.jp/digital/video/-/detail/=/cid=sone00614/"
        )
        assert isinstance(scraper, DmmScraper)


class TestGetDefaultScraper:
    def test_returns_javdb(self) -> None:
        scraper = get_default_scraper()
        assert isinstance(scraper, JavdbScraper)


class TestGetEnabledScrapers:
    def test_none_returns_all(self) -> None:
        scrapers = get_enabled_scrapers(None)
        assert len(scrapers) == len(SCRAPERS)

    def test_filters_by_name(self) -> None:
        scrapers = get_enabled_scrapers({"javdb"})
        assert len(scrapers) == 1
        assert scrapers[0].name == "javdb"

    def test_multiple_names(self) -> None:
        scrapers = get_enabled_scrapers({"javdb", "javhoo"})
        assert len(scrapers) == 2
        names = {s.name for s in scrapers}
        assert names == {"javdb", "javhoo"}

    def test_get_scraper_with_enabled_filters(self) -> None:
        with pytest.raises(NoSupportedScraperError):
            get_scraper("https://www.javhoo.com/en/ABF-360", enabled_names={"javdb"})

    def test_get_scraper_skips_disabled(self) -> None:
        s = get_scraper(
            "https://en.jav321.com/video/sone00614", enabled_names={"jav321"}
        )
        assert s.name == "jav321"
