from __future__ import annotations

from selectolax.parser import HTMLParser

from app.scrapers.dmm import DmmScraper

_CONTENT_PAGE = """<!DOCTYPE html>
<html lang="ja">
<head>
<title>【VR】地方局の崖っぷち女子アナ 幸村泉希 森沢かな｜エロ動画・アダルトビデオ｜FANZA動画</title>
</head>
<body>
<main class="p-4">
<div class="flex relative">
<div class="ml-4 grow">
<p>お気に入り登録数</p>
<p>1369</p>
<p>対応デバイス：	PC VR、 iOS VRアプリ</p>
<p>配信開始日：	2026/06/25</p>
<p>商品発売日：	2026/06/25</p>
<p>収録時間：	76分</p>
<p>出演者：</p>
<p>幸村泉希</p>
<p>森沢かな（飯岡かなこ）</p>
<p>依本しおり</p>
<p>シリーズ：	kawaii*VR</p>
<p>メーカー：	kawaii</p>
<p>レーベル：	kawaii* VR</p>
<p>コンテンツタイプ：	3D</p>
<p>ジャンル：</p>
<p>美少女</p>
<p>スレンダー</p>
<p>おもちゃ</p>
<p>独占配信</p>
<p>VR専用</p>
<p>配信品番：	kavr00501</p>
<p>平均評価：	3.50</p>
</div>
</div>
</main>
</body>
</html>
"""

_SEARCH_PAGE = """<!DOCTYPE html>
<html lang="ja">
<head><title>Search</title></head>
<body>
<main>
<div>
<a href="https://www.dmm.co.jp/digital/video/-/detail/=/cid=kavr00501/?i3_ref=search&amp;i3_ord=1">KAVR-501 title</a>
<a href="https://www.dmm.co.jp/rental/ppr/-/detail/=/cid=sone00614/?i3_ref=search">SONE-614 title</a>
<a href="https://www.dmm.co.jp/rental/-/detail/=/cid=ssis00123/">SSIS-123 title</a>
</div>
</main>
</body>
</html>
"""


class TestSupports:
    def setup_method(self) -> None:
        self.scraper = DmmScraper()

    def test_supports_dmm_co_jp(self) -> None:
        assert self.scraper.supports(
            "https://www.dmm.co.jp/digital/video/-/detail/=/cid=sone00614/"
        )

    def test_supports_video_dmm_co_jp(self) -> None:
        assert self.scraper.supports("https://video.dmm.co.jp/av/content/?id=sone00614")

    def test_supports_old_dmm_url(self) -> None:
        assert self.scraper.supports(
            "https://www.dmm.co.jp/digital/video/-/detail/=/cid=ssis00123/"
        )

    def test_not_supports_other_site(self) -> None:
        assert not self.scraper.supports("https://example.com/v/abc")


class TestExtractCid:
    def setup_method(self) -> None:
        self.scraper = DmmScraper()

    def test_extract_cid_from_url(self) -> None:
        assert (
            self.scraper._extract_cid(
                "https://video.dmm.co.jp/av/content/?id=sone00614"
            )
            == "sone00614"
        )

    def test_extract_cid_from_old_url(self) -> None:
        assert (
            self.scraper._extract_cid(
                "https://www.dmm.co.jp/digital/video/-/detail/=/cid=sone00614/"
            )
            == "sone00614"
        )

    def test_extract_cid_no_match(self) -> None:
        assert self.scraper._extract_cid("https://www.dmm.co.jp/top/") is None


class TestParseTitle:
    def setup_method(self) -> None:
        self.scraper = DmmScraper()

    def test_title_from_title_tag(self) -> None:
        tree = HTMLParser(_CONTENT_PAGE)
        title = self.scraper._parse_title(tree, "kavr00501")
        assert title is not None
        assert "地方局" in title
        assert "kavr00501" not in (title or "")

    def test_no_title(self) -> None:
        tree = HTMLParser("<html></html>")
        assert self.scraper._parse_title(tree, None) is None


class TestParseNumber:
    def setup_method(self) -> None:
        self.scraper = DmmScraper()

    def test_distribution_number(self) -> None:
        result = self.scraper._parse_number("配信品番：	kavr00501")
        assert result == "kavr00501"

    def test_maker_number(self) -> None:
        result = self.scraper._parse_number("メーカー品番：	KAVR-501")
        assert result == "KAVR-501"

    def test_no_number(self) -> None:
        assert self.scraper._parse_number("no number here") is None


class TestParsePremiered:
    def setup_method(self) -> None:
        self.scraper = DmmScraper()

    def test_release_date(self) -> None:
        result = self.scraper._parse_premiered("配信開始日：\t2026/06/25")
        assert result == "2026-06-25"

    def test_alternate_label(self) -> None:
        result = self.scraper._parse_premiered("商品発売日：\t2025/01/15")
        assert result == "2025-01-15"

    def test_no_date(self) -> None:
        assert self.scraper._parse_premiered("no date here") is None


class TestParseRuntime:
    def setup_method(self) -> None:
        self.scraper = DmmScraper()

    def test_runtime(self) -> None:
        assert self.scraper._parse_runtime("収録時間：\t76分") == 76

    def test_no_runtime(self) -> None:
        assert self.scraper._parse_runtime("no runtime") is None


class TestParseActors:
    def setup_method(self) -> None:
        self.scraper = DmmScraper()

    def test_actors_from_page_text(self) -> None:
        text = "出演者：\n幸村泉希\n森沢かな（飯岡かなこ）\n依本しおり\n\nシリーズ："
        actors = self.scraper._parse_actors(text)
        assert len(actors) == 3
        assert actors[0].name == "幸村泉希"
        assert actors[1].name == "森沢かな（飯岡かなこ）"
        assert actors[2].name == "依本しおり"

    def test_no_actors(self) -> None:
        assert self.scraper._parse_actors("no actors here") == []


class TestParseCompanies:
    def setup_method(self) -> None:
        self.scraper = DmmScraper()

    def test_studio_label_series(self) -> None:
        text = "メーカー：\tkawaii\nレーベル：\tkawaii* VR\nシリーズ：\tkawaii*VR"
        studio, label, series = self.scraper._parse_companies(text)
        assert studio == "kawaii"
        assert label == "kawaii* VR"
        assert series == "kawaii*VR"

    def test_no_info(self) -> None:
        text = "no company info"
        studio, label, series = self.scraper._parse_companies(text)
        assert studio is None
        assert label is None
        assert series is None


class TestParseRating:
    def setup_method(self) -> None:
        self.scraper = DmmScraper()

    def test_rating(self) -> None:
        assert self.scraper._parse_rating("平均評価：\t3.50") == 3.5

    def test_no_rating(self) -> None:
        assert self.scraper._parse_rating("no rating") is None


class TestParseMetadata:
    def setup_method(self) -> None:
        self.scraper = DmmScraper()

    def test_full_metadata(self) -> None:
        tree = HTMLParser(_CONTENT_PAGE)
        meta = self.scraper._parse_metadata(
            tree, "https://video.dmm.co.jp/av/content/?id=kavr00501"
        )
        assert meta.number == "kavr00501"
        assert meta.premiered == "2026-06-25"
        assert meta.runtime == 76
        assert meta.studio == "kawaii"
        assert meta.label == "kawaii* VR"
        assert meta.series == "kawaii*VR"
        assert len(meta.genres) >= 3
        assert "美少女" in meta.genres
        assert len(meta.actors) >= 1
        assert meta.rating == 3.5

    def test_minimal_metadata(self) -> None:
        tree = HTMLParser(
            "<html><head><title>test</title></head><body><main><p>test</p></main></body></html>"
        )
        meta = self.scraper._parse_metadata(tree, "https://video.dmm.co.jp/")
        assert meta.title == "test"


class TestAbspathUrl:
    def setup_method(self) -> None:
        self.scraper = DmmScraper()

    def test_normal_url(self) -> None:
        result = self.scraper._abspath_url(
            "/av/content/?id=test", "https://video.dmm.co.jp"
        )
        assert result == "https://video.dmm.co.jp/av/content/?id=test"

    def test_protocol_relative(self) -> None:
        result = self.scraper._abspath_url(
            "//pics.dmm.co.jp/img.jpg", "https://video.dmm.co.jp"
        )
        assert result == "https://pics.dmm.co.jp/img.jpg"

    def test_absolute_url(self) -> None:
        result = self.scraper._abspath_url(
            "http://pics.dmm.co.jp/img.jpg", "https://video.dmm.co.jp"
        )
        assert result == "http://pics.dmm.co.jp/img.jpg"


class TestParseSearchResults:
    def setup_method(self) -> None:
        self.scraper = DmmScraper()

    def test_search_results(self) -> None:
        results = self.scraper._parse_search_results(
            _SEARCH_PAGE, "https://video.dmm.co.jp/"
        )
        assert len(results) >= 1
        found = {r.number for r in results if r.number}
        assert "KAVR-501" in found or "SONE-614" in found

    def test_empty_search(self) -> None:
        results = self.scraper._parse_search_results(
            "<html></html>", "https://video.dmm.co.jp/"
        )
        assert results == []
