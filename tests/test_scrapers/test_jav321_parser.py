from __future__ import annotations

from selectolax.parser import HTMLParser

from app.scrapers.jav321 import Jav321Scraper


class TestParseTitle:
    def setup_method(self) -> None:
        self.scraper = Jav321Scraper()

    def test_normal_title_en(self) -> None:
        html = """
        <div class="panel-heading">
          <h3>新人NO.1 STYLE 最強ヒロイン瀬戸環奈AVデビュー <small>sone-614 瀬戸環奈</small></h3>
        </div>
        """
        tree = HTMLParser(html)
        assert (
            self.scraper._parse_title(tree)
            == "新人NO.1 STYLE 最強ヒロイン瀬戸環奈AVデビュー"
        )

    def test_title_no_small(self) -> None:
        html = """
        <div class="panel-heading">
          <h3>Title Only</h3>
        </div>
        """
        tree = HTMLParser(html)
        assert self.scraper._parse_title(tree) == "Title Only"

    def test_no_panel_heading(self) -> None:
        tree = HTMLParser("<html></html>")
        assert self.scraper._parse_title(tree) is None


class TestParseNumber:
    def setup_method(self) -> None:
        self.scraper = Jav321Scraper()

    def test_sn_label_en(self) -> None:
        html = """
        <div class="col-md-9">
          <b>Stars</b>: <a href="/star/1">Name</a><br>
          <b>SN</b>: sone-614<br>
          <b>Release Date</b>: 2025-01-24<br>
        </div>
        """
        tree = HTMLParser(html)
        assert self.scraper._parse_number(tree) == "sone-614"

    def test_sn_label_ja(self) -> None:
        html = """
        <div class="col-md-9">
          <b>出演者</b>: <a href="/star/1">Name</a><br>
          <b>品番</b>: ssis-034<br>
          <b>配信開始日</b>: 2021-04-07<br>
        </div>
        """
        tree = HTMLParser(html)
        assert self.scraper._parse_number(tree) == "ssis-034"

    def test_no_info_div(self) -> None:
        tree = HTMLParser("<html></html>")
        assert self.scraper._parse_number(tree) is None

    def test_sn_with_underscore(self) -> None:
        html = """
        <div class="col-md-9">
          <b>SN</b>: abc_001<br>
        </div>
        """
        tree = HTMLParser(html)
        assert self.scraper._parse_number(tree) == "abc_001"


class TestParsePremiered:
    def setup_method(self) -> None:
        self.scraper = Jav321Scraper()

    def test_release_date_en(self) -> None:
        html = """
        <div class="col-md-9">
          <b>Release Date</b>: 2025-01-24<br>
        </div>
        """
        tree = HTMLParser(html)
        assert self.scraper._parse_premiered(tree) == "2025-01-24"

    def test_release_date_ja(self) -> None:
        html = """
        <div class="col-md-9">
          <b>配信開始日</b>: 2021-04-07<br>
        </div>
        """
        tree = HTMLParser(html)
        assert self.scraper._parse_premiered(tree) == "2021-04-07"

    def test_no_date(self) -> None:
        html = """
        <div class="col-md-9">
          <b>SN</b>: abc-001<br>
        </div>
        """
        tree = HTMLParser(html)
        assert self.scraper._parse_premiered(tree) is None


class TestParseRating:
    def setup_method(self) -> None:
        self.scraper = Jav321Scraper()

    def test_rating_en(self) -> None:
        html = """
        <div class="col-md-9">
          <b>Rating</b>: 4.9<br>
        </div>
        """
        tree = HTMLParser(html)
        assert self.scraper._parse_rating(tree) == 4.9

    def test_rating_ja(self) -> None:
        html = """
        <div class="col-md-9">
          <b>平均評価</b>: 4.5<br>
        </div>
        """
        tree = HTMLParser(html)
        assert self.scraper._parse_rating(tree) == 4.5

    def test_rating_integer(self) -> None:
        html = """
        <div class="col-md-9">
          <b>Rating</b>: 5<br>
        </div>
        """
        tree = HTMLParser(html)
        assert self.scraper._parse_rating(tree) == 5.0

    def test_no_rating(self) -> None:
        html = """
        <div class="col-md-9">
          <b>SN</b>: abc-001<br>
        </div>
        """
        tree = HTMLParser(html)
        assert self.scraper._parse_rating(tree) is None


class TestParseRuntime:
    def setup_method(self) -> None:
        self.scraper = Jav321Scraper()

    def test_runtime_ja(self) -> None:
        html = """
        <div class="col-md-9">
          <b>収録時間</b>: 164 minutes<br>
        </div>
        """
        tree = HTMLParser(html)
        assert self.scraper._parse_runtime(tree) == 164

    def test_no_runtime(self) -> None:
        html = """
        <div class="col-md-9">
          <b>SN</b>: abc-001<br>
        </div>
        """
        tree = HTMLParser(html)
        assert self.scraper._parse_runtime(tree) is None


class TestParseActors:
    def setup_method(self) -> None:
        self.scraper = Jav321Scraper()

    def test_actors_via_link(self) -> None:
        html = """
        <div class="col-md-9">
          <b>Stars</b>: <a href="/star/1099472/1">瀬戸環奈</a><br>
          <b>Studio</b>: <a href="/company/test">Studio Name</a><br>
          <b>SN</b>: sone-614<br>
        </div>
        """
        tree = HTMLParser(html)
        result = self.scraper._parse_actors(tree)
        assert len(result) == 1
        assert result[0].name == "瀬戸環奈"
        assert result[0].gender is None

    def test_multiple_actors_via_link(self) -> None:
        html = """
        <div class="col-md-9">
          <b>Stars</b>:
          <a href="/star/1">Actor One</a>
          <a href="/star/2">Actor Two</a>
          <br>
        </div>
        """
        tree = HTMLParser(html)
        result = self.scraper._parse_actors(tree)
        assert len(result) == 2
        assert result[0].name == "Actor One"
        assert result[1].name == "Actor Two"

    def test_actors_plain_text_fallback(self) -> None:
        html = """
        <div class="col-md-9">
          <b>Stars</b>: 瀬戸環奈 <br>
          <b>Studio</b>: Studio Name<br>
        </div>
        """
        tree = HTMLParser(html)
        result = self.scraper._parse_actors(tree)
        assert len(result) == 1
        assert result[0].name == "瀬戸環奈"

    def test_actors_ja_fallback(self) -> None:
        html = """
        <div class="col-md-9">
          <b>出演者</b>: 有栖花あか <br>
          <b>メーカー</b>: Studio Name<br>
        </div>
        """
        tree = HTMLParser(html)
        result = self.scraper._parse_actors(tree)
        assert len(result) == 1
        assert result[0].name == "有栖花あか"

    def test_no_actors(self) -> None:
        html = """
        <div class="col-md-9">
          <b>SN</b>: abc-001<br>
        </div>
        """
        tree = HTMLParser(html)
        assert self.scraper._parse_actors(tree) == []

    def test_no_info_div(self) -> None:
        tree = HTMLParser("<html></html>")
        assert self.scraper._parse_actors(tree) == []


class TestParseStudio:
    def setup_method(self) -> None:
        self.scraper = Jav321Scraper()

    def test_studio_via_link(self) -> None:
        html = """
        <div class="col-md-9">
          <b>Stars</b>: <a href="/star/1">Name</a><br>
          <b>Studio</b>: <a href="/company/%E3%82%A8%E3%82%B9%E3%83%AF%E3%83%B3">エスワン ナンバーワンスタイル</a><br>
          <b>SN</b>: sone-614<br>
        </div>
        """
        tree = HTMLParser(html)
        assert self.scraper._parse_studio(tree) == "エスワン ナンバーワンスタイル"

    def test_studio_ja(self) -> None:
        html = """
        <div class="col-md-9">
          <b>メーカー</b>: <a href="/company/test">メーカー名</a><br>
          <b>品番</b>: abc-001<br>
        </div>
        """
        tree = HTMLParser(html)
        assert self.scraper._parse_studio(tree) == "メーカー名"

    def test_studio_no_link_fallback(self) -> None:
        html = """
        <div class="col-md-9">
          <b>Studio</b>: Studio Name<br>
          <b>SN</b>: abc-001<br>
        </div>
        """
        tree = HTMLParser(html)
        assert self.scraper._parse_studio(tree) == "Studio Name"

    def test_no_studio(self) -> None:
        html = """
        <div class="col-md-9">
          <b>SN</b>: abc-001<br>
        </div>
        """
        tree = HTMLParser(html)
        assert self.scraper._parse_studio(tree) is None


class TestParsePlot:
    def setup_method(self) -> None:
        self.scraper = Jav321Scraper()

    def test_plot_present(self) -> None:
        html = """
        <div class="panel-body">
          <div class="row">
            <div class="col-md-3"><img src="http://example.com/poster.jpg"></div>
            <div class="col-md-9"><b>Stars</b>: Name<br></div>
          </div>
          <div class="row">
            <div class="col-md-12"><video></video></div>
          </div>
          <div class="row">
            <div class="col-md-12">これはテストのプロットです。テスト用の長い説明文です。</div>
          </div>
        </div>
        """
        tree = HTMLParser(html)
        assert (
            self.scraper._parse_plot(tree)
            == "これはテストのプロットです。テスト用の長い説明文です。"
        )

    def test_plot_too_short(self) -> None:
        html = """
        <div class="panel-body">
          <div class="row">
            <div class="col-md-3"><img src="http://example.com/poster.jpg"></div>
            <div class="col-md-9"><b>Stars</b>: Name<br></div>
          </div>
          <div class="row">
            <div class="col-md-12"><video></video></div>
          </div>
          <div class="row">
            <div class="col-md-12">short</div>
          </div>
        </div>
        """
        tree = HTMLParser(html)
        assert self.scraper._parse_plot(tree) is None

    def test_no_plot(self) -> None:
        html = """
        <div class="panel-body">
          <div class="row">
            <div class="col-md-3"><img src="http://example.com/poster.jpg"></div>
            <div class="col-md-9"><b>Stars</b>: Name<br></div>
          </div>
          <div class="row">
            <div class="col-md-12"><video></video></div>
          </div>
          <div class="row">
            <div class="col-md-12"></div>
          </div>
        </div>
        """
        tree = HTMLParser(html)
        assert self.scraper._parse_plot(tree) is None

    def test_no_panel_body(self) -> None:
        tree = HTMLParser("<html></html>")
        assert self.scraper._parse_plot(tree) is None


class TestParseImages:
    def setup_method(self) -> None:
        self.scraper = Jav321Scraper()

    def test_poster_from_first_col(self) -> None:
        html = """
        <div class="panel-body">
          <div class="row">
            <div class="col-md-3">
              <img src="http://pics.dmm.co.jp/digital/video/sone00614/sone00614ps.jpg">
            </div>
            <div class="col-md-9"><b>Stars</b>: Name<br></div>
          </div>
        </div>
        """
        tree = HTMLParser(html)
        posters, art = self.scraper._parse_images(
            tree, "https://en.jav321.com/video/sone00614"
        )
        assert len(posters) == 1
        assert "sone00614ps.jpg" in posters[0]

    def test_art_from_sidebar(self) -> None:
        html = """
        <div class="row">
          <div class="col-md-7 col-md-offset-1 col-xs-12">
            <div class="panel panel-info"><div class="panel-body"></div></div>
          </div>
          <div class="col-md-3">
            <p><img src="http://pics.dmm.co.jp/digital/video/sone00614/sone00614pl.jpg"></p>
            <p><img src="http://pics.dmm.co.jp/digital/video/sone00614/sone00614jp-1.jpg"></p>
            <p><img src="http://pics.dmm.co.jp/digital/video/sone00614/sone00614jp-2.jpg"></p>
          </div>
        </div>
        """
        tree = HTMLParser(html)
        posters, art = self.scraper._parse_images(
            tree, "https://en.jav321.com/video/sone00614"
        )
        assert len(art) == 3
        assert any("sone00614pl.jpg" in u for u in art)
        assert any("sone00614jp-1.jpg" in u for u in art)
        assert any("sone00614jp-2.jpg" in u for u in art)

    def test_art_fallback_to_poster(self) -> None:
        html = """
        <div class="panel-body">
          <div class="row">
            <div class="col-md-3">
              <img src="http://example.com/poster.jpg">
            </div>
          </div>
        </div>
        """
        tree = HTMLParser(html)
        posters, art = self.scraper._parse_images(
            tree, "https://en.jav321.com/video/test"
        )
        assert len(posters) == 1
        assert len(art) == 1
        assert art[0] == posters[0]

    def test_no_images(self) -> None:
        tree = HTMLParser("<html></html>")
        posters, art = self.scraper._parse_images(tree, "https://en.jav321.com/")
        assert posters == []
        assert art == []


class TestParseMetadata:
    def setup_method(self) -> None:
        self.scraper = Jav321Scraper()

    def test_full_metadata_en(self) -> None:
        html = """
        <div class="panel panel-info">
          <div class="panel-heading">
            <h3>新人NO.1 STYLE 最強ヒロイン瀬戸環奈AVデビュー <small>sone-614 瀬戸環奈</small></h3>
          </div>
          <div class="panel-body">
            <div class="row">
              <div class="col-md-3"><img src="http://pics.dmm.co.jp/digital/video/sone00614/sone00614ps.jpg"></div>
              <div class="col-md-9">
                <b>Stars</b>: <a href="/star/1099472/1">瀬戸環奈</a><br>
                <b>Studio</b>: <a href="/company/test">エスワン ナンバーワンスタイル</a><br>
                <b>SN</b>: sone-614<br>
                <b>Release Date</b>: 2025-01-24<br>
                <b>Rating</b>: 4.9<br>
              </div>
            </div>
            <div class="row">
              <div class="col-md-12">これはテスト用のプロットです。この説明文は20文字以上になるように書いています。</div>
            </div>
          </div>
        </div>
        """
        tree = HTMLParser(html)
        metadata = self.scraper._parse_metadata(
            tree, "https://en.jav321.com/video/sone00614"
        )
        assert (
            metadata.title == "sone-614 新人NO.1 STYLE 最強ヒロイン瀬戸環奈AVデビュー"
        )
        assert metadata.number == "sone-614"
        assert metadata.premiered == "2025-01-24"
        assert metadata.releasedate == "2025-01-24"
        assert metadata.rating == 4.9
        assert len(metadata.actors) == 1
        assert metadata.actors[0].name == "瀬戸環奈"
        assert metadata.studio == "エスワン ナンバーワンスタイル"
        assert "プロット" in (metadata.plot or "")
        assert len(metadata.posters) == 1
        assert "sone00614ps.jpg" in str(metadata.posters[0])
        assert metadata.genres == []
        assert metadata.tags == []
        assert metadata.directors == []

    def test_minimal_metadata(self) -> None:
        html = """
        <div class="panel panel-info">
          <div class="panel-heading">
            <h3>Only Title</h3>
          </div>
          <div class="panel-body">
            <div class="row">
              <div class="col-md-3"></div>
              <div class="col-md-9"></div>
            </div>
          </div>
        </div>
        """
        tree = HTMLParser(html)
        metadata = self.scraper._parse_metadata(tree, "https://en.jav321.com/")
        assert metadata.title == "Only Title"
        assert metadata.number is None

    def test_unknown_title(self) -> None:
        tree = HTMLParser("<html></html>")
        metadata = self.scraper._parse_metadata(tree, "https://en.jav321.com/")
        assert metadata.title == "Unknown Title"


class TestParseGenres:
    def setup_method(self) -> None:
        self.scraper = Jav321Scraper()

    def test_genres_via_link(self) -> None:
        html = """
        <div class="col-md-9">
          <b>ジャンル</b>:
          <a href="/genre/4118/1">アイドル・芸能人</a>
          <a href="/genre/4025/1">単体作品</a>
          <a href="/genre/2001/1">巨乳</a>
        </div>
        """
        tree = HTMLParser(html)
        genres = self.scraper._parse_genres(tree)
        assert "アイドル・芸能人" in genres
        assert "単体作品" in genres
        assert "巨乳" in genres

    def test_no_genres(self) -> None:
        html = """
        <div class="col-md-9">
          <b>Stars</b>: Name<br>
        </div>
        """
        tree = HTMLParser(html)
        assert self.scraper._parse_genres(tree) == []

    def test_no_info_div(self) -> None:
        tree = HTMLParser("<html></html>")
        assert self.scraper._parse_genres(tree) == []


class TestParseSingleVideoResult:
    def setup_method(self) -> None:
        self.scraper = Jav321Scraper()

    def test_single_video_extracted(self) -> None:
        html = """
        <div class="panel panel-info">
          <div class="panel-heading">
            <h3>PRETTYKISS 松島かえで <small>ig-088 松島かえで</small></h3>
          </div>
          <div class="panel-body">
            <div class="row">
              <div class="col-md-3"><img src="http://pics.dmm.co.jp/digital/video/61ig00088/61ig00088ps.jpg"></div>
              <div class="col-md-9"><b>品番</b>: ig-088<br></div>
            </div>
          </div>
        </div>
        """
        tree = HTMLParser(html)
        results = self.scraper._parse_single_video_result(
            tree, "https://en.jav321.com/video/61ig00088"
        )
        assert len(results) == 1
        assert results[0].number == "ig-088"
        assert "ig-088 PRETTYKISS" in results[0].title

    def test_no_h3_returns_empty(self) -> None:
        tree = HTMLParser("<html></html>")
        results = self.scraper._parse_single_video_result(
            tree, "https://en.jav321.com/"
        )
        assert results == []


class TestParseSearchResults:
    def setup_method(self) -> None:
        self.scraper = Jav321Scraper()

    def test_not_found(self) -> None:
        html = '<div class="alert alert-danger">AVが見つかりませんでした。</div>'
        results = self.scraper._parse_search_results(
            html, "https://en.jav321.com/search"
        )
        assert results == []

    def test_video_page_redirect(self) -> None:
        html = """
        <div class="panel panel-info">
          <div class="panel-heading">
            <h3>PRETTYKISS 松島かえで <small>ig-088 松島かえで</small></h3>
          </div>
          <div class="panel-body">
            <div class="row">
              <div class="col-md-3"><img src="http://pics.dmm.co.jp/digital/video/61ig00088/61ig00088ps.jpg"></div>
              <div class="col-md-9"><b>品番</b>: ig-088<br></div>
            </div>
          </div>
        </div>
        """
        results = self.scraper._parse_search_results(
            html, "https://en.jav321.com/video/61ig00088"
        )
        assert len(results) == 1
        assert results[0].number == "ig-088"
        assert "松島かえで" in results[0].title

    def test_search_results_page(self) -> None:
        html = """
        <div class="thumbnail">
          <a href="/video/sone00614">
            <img src="http://pics.dmm.co.jp/digital/video/sone00614/sone00614ps.jpg">
            <br>新人NO.1 STYLE sone-614
          </a>
        </div>
        <div class="thumbnail">
          <a href="/video/sone00615">
            <img src="http://pics.dmm.co.jp/digital/video/sone00615/sone00615ps.jpg">
            <br>最強ヒロインAV初体験3本番 sone-615
          </a>
        </div>
        """
        results = self.scraper._parse_search_results(
            html, "https://en.jav321.com/search"
        )
        assert len(results) == 2
        numbers = {r.number for r in results}
        assert "sone-614" in numbers
        assert "sone-615" in numbers

    def test_empty_html(self) -> None:
        results = self.scraper._parse_search_results("", "https://en.jav321.com/search")
        assert results == []


class TestGetInfoText:
    def setup_method(self) -> None:
        self.scraper = Jav321Scraper()

    def test_info_text(self) -> None:
        html = """
        <div class="col-md-9">
          <b>Stars</b>: Name<br>
          <b>SN</b>: abc-001<br>
        </div>
        """
        tree = HTMLParser(html)
        text = self.scraper._get_info_text(tree)
        assert text is not None
        assert "Stars" in text
        assert "abc-001" in text

    def test_no_info_div(self) -> None:
        tree = HTMLParser("<html></html>")
        assert self.scraper._get_info_text(tree) is None


class TestAbspathUrl:
    def setup_method(self) -> None:
        self.scraper = Jav321Scraper()

    def test_normal_url(self) -> None:
        result = self.scraper._abspath_url("/video/sone00614", "https://en.jav321.com")
        assert result == "https://en.jav321.com/video/sone00614"

    def test_protocol_relative(self) -> None:
        result = self.scraper._abspath_url(
            "//pics.dmm.co.jp/img.jpg", "https://en.jav321.com"
        )
        assert result == "https://pics.dmm.co.jp/img.jpg"

    def test_absolute_url(self) -> None:
        result = self.scraper._abspath_url(
            "http://pics.dmm.co.jp/img.jpg", "https://en.jav321.com"
        )
        assert result == "http://pics.dmm.co.jp/img.jpg"


class TestGetImgUrl:
    def setup_method(self) -> None:
        self.scraper = Jav321Scraper()

    def test_src_attribute(self) -> None:
        html = '<img src="http://example.com/img.jpg">'
        tree = HTMLParser(html)
        node = tree.css_first("img")
        assert node is not None
        url = self.scraper._get_img_url(node, "https://en.jav321.com")
        assert url == "http://example.com/img.jpg"

    def test_data_original_attribute(self) -> None:
        html = '<img data-original="http://example.com/lazy.jpg">'
        tree = HTMLParser(html)
        node = tree.css_first("img")
        assert node is not None
        url = self.scraper._get_img_url(node, "https://en.jav321.com")
        assert url == "http://example.com/lazy.jpg"

    def test_no_attributes(self) -> None:
        html = "<img>"
        tree = HTMLParser(html)
        node = tree.css_first("img")
        assert node is not None
        assert self.scraper._get_img_url(node, "https://en.jav321.com") is None
