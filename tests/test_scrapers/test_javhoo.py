from __future__ import annotations

from selectolax.parser import HTMLParser

from app.scrapers.javhoo import JavhooScraper

_VIDEO_PAGE = """<!DOCTYPE html>
<html>
<head><title>ABF-360 test</title></head>
<body>
<h1 class="article-title">ABF-360 河合あすなの異常な愛情</h1>
<article class="article-content">
<p><a class="dt-single-image" href="https://pics.javhoo.net/2026/06/ABF-360_b.jpg"><img class="alignnone size-full" src="https://pics.javhoo.net/2026/06/ABF-360_b.jpg" width="800"></a></p>
</article>
<div class="sidebar">
<div class="widget pods_widget_field"><h3>識別碼:</h3><span style="color:#CC0000;">ABF-360</span></div>
<div class="widget pods_widget_field"><h3>發行日期:</h3>2026-07-03</div>
<div class="widget pods_widget_field"><h3>長度:</h3>120</div>
<div class="widget pods_widget_field"><h3>製作商:</h3><span><a href="https://www.javhoo.com/en/studio/prestige">プレステージ</a></span></div>
<div class="widget pods_widget_field"><h3>系列:</h3><span class="series"><a href="https://www.javhoo.com/en/series/xxx">異常な愛情</a></span></div>
<div class="widget pods_widget_field"><h3>類別:</h3><p><span><a href="https://www.javhoo.com/en/genre/fhd">フルハイビジョン(FHD)</a></span><span><a href="https://www.javhoo.com/en/genre/乳交">乳交</a></span><span><a href="https://www.javhoo.com/en/genre/巨乳">巨乳</a></span></p></div>
<div class="widget pods_widget_field"><h3>演員:</h3><p><span><a href="https://www.javhoo.com/en/star/kawai-asuna">河合あすな</a></span></p></div>
</div>
<h3>樣品圖像</h3>
<div class="the_excerpt">
<a class="dt-mfp-item" href="https://image.mgstage.com/images/prestige/abf/360/cap_e_0_abf-360.jpg"><div class="photo-frame"><img src="https://pics.javhoo.net/2026/06/s/cbpv_1.jpg"></div></a>
<a class="dt-mfp-item" href="https://image.mgstage.com/images/prestige/abf/360/cap_e_1_abf-360.jpg"><div class="photo-frame"><img src="https://pics.javhoo.net/2026/06/s/cbpv_2.jpg"></div></a>
<a class="dt-mfp-item" href="https://image.mgstage.com/images/prestige/abf/360/cap_e_2_abf-360.jpg"><div class="photo-frame"><img src="https://pics.javhoo.net/2026/06/s/cbpv_3.jpg"></div></a>
</div>
</body>
</html>
"""

_SEARCH_PAGE = """<!DOCTYPE html>
<html>
<head><title>Search Results</title></head>
<body>
<section class="container">
<div class="excerpts-wrapper"><div class="excerpts">
<article class="excerpt excerpt-c5">
<a class="thumbnail" href="https://www.javhoo.com/en/ABF-360"><img src="https://pics.javhoo.net/thumb.png" data-src="https://pics.javhoo.net/2026/06/ABF-360.jpg" class="thumb"></a>
<h2><a href="https://www.javhoo.com/en/ABF-360">ABF-360 河合あすなの異常な愛情</a></h2>
<footer><time>Jun 20,2026</time></footer>
</article>
<article class="excerpt excerpt-c5">
<a class="thumbnail" href="https://www.javhoo.com/en/ABF-361"><img src="https://pics.javhoo.net/thumb.png" data-src="https://pics.javhoo.net/2026/06/ABF-361.jpg" class="thumb"></a>
<h2><a href="https://www.javhoo.com/en/ABF-361">ABF-361 もう一つのタイトル</a></h2>
<footer><time>Jun 21,2026</time></footer>
</article>
</div></div>
</section>
</body>
</html>
"""


class TestSupports:
    def setup_method(self) -> None:
        self.scraper = JavhooScraper()

    def test_supports_video_url(self) -> None:
        assert self.scraper.supports("https://www.javhoo.com/v/ABF-360")

    def test_supports_en_url(self) -> None:
        assert self.scraper.supports("https://www.javhoo.com/en/ABF-360")

    def test_supports_root_url(self) -> None:
        assert self.scraper.supports("https://www.javhoo.com/ABF-360")

    def test_supports_homepage(self) -> None:
        assert self.scraper.supports("https://www.javhoo.com/")

    def test_not_supports_other_site(self) -> None:
        assert not self.scraper.supports("https://example.com/v/abc")


class TestParseTitle:
    def setup_method(self) -> None:
        self.scraper = JavhooScraper()

    def test_extracts_title_without_number(self) -> None:
        tree = HTMLParser(_VIDEO_PAGE)
        assert self.scraper._parse_title(tree) == "河合あすなの異常な愛情"

    def test_no_title_node(self) -> None:
        tree = HTMLParser("<html></html>")
        assert self.scraper._parse_title(tree) is None


class TestParseNumber:
    def setup_method(self) -> None:
        self.scraper = JavhooScraper()

    def test_extracts_number(self) -> None:
        tree = HTMLParser(_VIDEO_PAGE)
        assert self.scraper._parse_number(tree) == "ABF-360"

    def test_no_number_node(self) -> None:
        tree = HTMLParser("<html></html>")
        assert self.scraper._parse_number(tree) is None


class TestParsePremiered:
    def setup_method(self) -> None:
        self.scraper = JavhooScraper()

    def test_extracts_date(self) -> None:
        tree = HTMLParser(_VIDEO_PAGE)
        assert self.scraper._parse_premiered(tree) == "2026-07-03"

    def test_no_date_node(self) -> None:
        tree = HTMLParser("<html></html>")
        assert self.scraper._parse_premiered(tree) is None


class TestParseRuntime:
    def setup_method(self) -> None:
        self.scraper = JavhooScraper()

    def test_extracts_runtime(self) -> None:
        tree = HTMLParser(_VIDEO_PAGE)
        assert self.scraper._parse_runtime(tree) == 120

    def test_no_runtime_node(self) -> None:
        tree = HTMLParser("<html></html>")
        assert self.scraper._parse_runtime(tree) is None


class TestParseGenres:
    def setup_method(self) -> None:
        self.scraper = JavhooScraper()

    def test_extracts_genres(self) -> None:
        tree = HTMLParser(_VIDEO_PAGE)
        genres = self.scraper._parse_genres(tree)
        assert "フルハイビジョン(FHD)" in genres
        assert "乳交" in genres
        assert "巨乳" in genres

    def test_no_genres_node(self) -> None:
        tree = HTMLParser("<html></html>")
        assert self.scraper._parse_genres(tree) == []


class TestParseStudio:
    def setup_method(self) -> None:
        self.scraper = JavhooScraper()

    def test_extracts_studio(self) -> None:
        tree = HTMLParser(_VIDEO_PAGE)
        assert self.scraper._parse_studio(tree) == "プレステージ"

    def test_no_studio_node(self) -> None:
        tree = HTMLParser("<html></html>")
        assert self.scraper._parse_studio(tree) is None


class TestParseSeries:
    def setup_method(self) -> None:
        self.scraper = JavhooScraper()

    def test_extracts_series(self) -> None:
        tree = HTMLParser(_VIDEO_PAGE)
        assert self.scraper._parse_series(tree) == "異常な愛情"

    def test_no_series_node(self) -> None:
        tree = HTMLParser("<html></html>")
        assert self.scraper._parse_series(tree) is None


class TestParseActors:
    def setup_method(self) -> None:
        self.scraper = JavhooScraper()

    def test_extracts_actors(self) -> None:
        tree = HTMLParser(_VIDEO_PAGE)
        actors = self.scraper._parse_actors(tree)
        assert len(actors) == 1
        assert actors[0].name == "河合あすな"

    def test_no_actors_node(self) -> None:
        tree = HTMLParser("<html></html>")
        assert self.scraper._parse_actors(tree) == []

    def test_multiple_actors(self) -> None:
        html = """<html><body><div class="sidebar">
<div class="widget pods_widget_field"><h3>演員:</h3><p><span><a href="/a">松島かえで</a></span><span><a href="/b">二宮和香</a></span></p></div>
</div></body></html>"""
        tree = HTMLParser(html)
        actors = self.scraper._parse_actors(tree)
        assert len(actors) == 2
        assert actors[0].name == "松島かえで"
        assert actors[1].name == "二宮和香"


class TestParseImages:
    def setup_method(self) -> None:
        self.scraper = JavhooScraper()

    def test_extracts_posters_and_art(self) -> None:
        tree = HTMLParser(_VIDEO_PAGE)
        posters, art = self.scraper._parse_images(
            tree, "https://www.javhoo.com/en/ABF-360"
        )
        assert len(posters) == 1
        assert posters[0] == "https://pics.javhoo.net/2026/06/ABF-360_b.jpg"
        assert len(art) == 3
        assert "cap_e_0_abf-360.jpg" in art[0]
        assert "cap_e_2_abf-360.jpg" in art[2]


class TestParseMetadata:
    def setup_method(self) -> None:
        self.scraper = JavhooScraper()

    def test_full_metadata(self) -> None:
        tree = HTMLParser(_VIDEO_PAGE)
        meta = self.scraper._parse_metadata(tree, "https://www.javhoo.com/en/ABF-360")
        assert meta.title == "ABF-360 河合あすなの異常な愛情"
        assert meta.number == "ABF-360"
        assert meta.premiered == "2026-07-03"
        assert meta.runtime == 120
        assert meta.studio == "プレステージ"
        assert meta.series == "異常な愛情"
        assert len(meta.genres) == 3
        assert len(meta.posters) == 1
        assert len(meta.art) == 3
        assert len(meta.actors) == 1
        assert meta.actors[0].name == "河合あすな"


class TestParseSearchResults:
    def setup_method(self) -> None:
        self.scraper = JavhooScraper()

    def test_parse_search_results(self) -> None:
        results = self.scraper._parse_search_results(
            _SEARCH_PAGE, "https://www.javhoo.com/en/"
        )
        assert len(results) == 2
        assert results[0].title == "ABF-360 河合あすなの異常な愛情"
        assert results[0].number == "ABF-360"
        assert results[0].url == "https://www.javhoo.com/en/ABF-360"
        assert results[0].date == "2026-06-20"
        assert results[1].title == "ABF-361 もう一つのタイトル"
        assert results[1].number == "ABF-361"
        assert results[1].date == "2026-06-21"

    def test_empty_search(self) -> None:
        results = self.scraper._parse_search_results(
            "<html></html>", "https://www.javhoo.com/en/"
        )
        assert results == []
