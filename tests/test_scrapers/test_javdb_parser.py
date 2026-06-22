from __future__ import annotations

import pytest
from selectolax.parser import HTMLParser

from app.schemas import Actor
from app.scrapers.javdb import JavdbScraper


class TestParseTitle:
    def setup_method(self) -> None:
        self.scraper = JavdbScraper()

    def test_normal_title(self) -> None:
        html = """
        <div class="video-detail">
          <h2 class="title is-4">
            <strong>IPVR-335</strong>
            <strong class="current-title">日文タイトル</strong>
          </h2>
        </div>
        """
        tree = HTMLParser(html)
        assert self.scraper._parse_title(tree) == "日文タイトル"

    def test_fallback_h2_title(self) -> None:
        html = '<h2 class="title">Fallback Title</h2>'
        tree = HTMLParser(html)
        assert self.scraper._parse_title(tree) == "Fallback Title"

    def test_fallback_video_title(self) -> None:
        html = '<h2 class="video-title">Video Title</h2>'
        tree = HTMLParser(html)
        assert self.scraper._parse_title(tree) == "Video Title"

    def test_fallback_div_video_title_h2(self) -> None:
        html = '<div class="video-title"><h2>Div Video Title</h2></div>'
        tree = HTMLParser(html)
        assert self.scraper._parse_title(tree) == "Div Video Title"

    def test_fallback_main_h2(self) -> None:
        html = "<main><h2>Main H2 Title</h2></main>"
        tree = HTMLParser(html)
        assert self.scraper._parse_title(tree) == "Main H2 Title"

    def test_fallback_first_h2(self) -> None:
        html = "<h2>First H2</h2><h2>Second H2</h2>"
        tree = HTMLParser(html)
        assert self.scraper._parse_title(tree) == "First H2"

    def test_empty_html(self) -> None:
        tree = HTMLParser("")
        assert self.scraper._parse_title(tree) is None

    def test_whitespace_only(self) -> None:
        html = """
        <div class="video-detail">
          <h2 class="title is-4">
            <strong class="current-title">   </strong>
          </h2>
        </div>
        """
        tree = HTMLParser(html)
        # strong.current-title text() is truthy ("   "), returns strip() => ""
        assert self.scraper._parse_title(tree) == ""

    def test_title_with_special_chars(self) -> None:
        html = """
        <div class="video-detail">
          <h2 class="title is-4">
            <strong class="current-title">ABC-123 テスト!! 【完全版】</strong>
          </h2>
        </div>
        """
        tree = HTMLParser(html)
        assert self.scraper._parse_title(tree) == "ABC-123 テスト!! 【完全版】"

    def test_fallback_h1(self) -> None:
        html = "<h1>H1 Title Fallback</h1>"
        tree = HTMLParser(html)
        assert self.scraper._parse_title(tree) == "H1 Title Fallback"


class TestValidateVideoPage:
    def setup_method(self) -> None:
        self.scraper = JavdbScraper()

    def test_valid_page_passes(self) -> None:
        html = """
        <div class="video-detail">
          <h2 class="title is-4"><strong class="current-title">Title</strong></h2>
        </div>
        <nav class="movie-panel-info"><div class="panel-block first-block">
          <strong>番號:</strong><span class="value">ABC-123</span>
        </div></nav>
        """
        tree = HTMLParser(html)
        # 不应抛出异常
        self.scraper._validate_video_page(tree)

    def test_minimal_valid_page_passes(self) -> None:
        """只有 video-detail 没有 nav.movie-panel-info 也应通过。"""
        html = """
        <div class="video-detail">
          <h2 class="title is-4"><strong class="current-title">Title</strong></h2>
        </div>
        """
        tree = HTMLParser(html)
        self.scraper._validate_video_page(tree)

    def test_over18_page_raises(self) -> None:
        html = """
        <div class="modal is-active over18-modal">
          <div class="modal-background"></div>
          <div class="modal-card">
            <header class="modal-card-head"><p class="modal-card-title">請注意</p></header>
            <section class="modal-card-body">您必須已達您當地的法定年齡</section>
          </div>
        </div>
        """
        tree = HTMLParser(html)
        with pytest.raises(ValueError, match="年龄验证"):
            self.scraper._validate_video_page(tree)

    def test_login_page_raises(self) -> None:
        html = """
        <form id="new_user" action="/login">
          <input name="user[login]">
          <input name="user[password]" type="password">
        </form>
        <a href="/users/new">注册</a>
        """
        tree = HTMLParser(html)
        with pytest.raises(ValueError, match="需要登录"):
            self.scraper._validate_video_page(tree)

    def test_login_with_over18_raises_login(self) -> None:
        """同时有登录表单和 over18 弹窗时优先报告登录问题。"""
        html = """
        <form id="new_user" action="/login">
          <input name="user[login]">
        </form>
        <div class="modal is-active over18-modal">
          <div class="modal-card">
            <section class="modal-card-body">年龄验证</section>
          </div>
        </div>
        <a href="/users/new">注册</a>
        """
        tree = HTMLParser(html)
        with pytest.raises(ValueError, match="需要登录"):
            self.scraper._validate_video_page(tree)

    def test_missing_video_detail_raises(self) -> None:
        html = "<html><body><p>Some random content</p></body></html>"
        tree = HTMLParser(html)
        with pytest.raises(ValueError, match="无法获取影片信息"):
            self.scraper._validate_video_page(tree)

    def test_empty_html_raises(self) -> None:
        tree = HTMLParser("")
        with pytest.raises(ValueError, match="无法获取影片信息"):
            self.scraper._validate_video_page(tree)


class TestParseNumber:
    def setup_method(self) -> None:
        self.scraper = JavdbScraper()

    def test_via_clipboard_text(self) -> None:
        html = """
        <nav class="movie-panel-info">
          <div class="panel-block first-block">
            <strong>番號:</strong>
            <span class="value"><a>IPVR</a>-335</span>
            <a class="button copy-to-clipboard" data-clipboard-text="IPVR-335">Copy</a>
          </div>
        </nav>
        """
        tree = HTMLParser(html)
        assert self.scraper._parse_number(tree) == "IPVR-335"

    def test_via_span_value(self) -> None:
        html = """
        <nav class="movie-panel-info">
          <div class="panel-block first-block">
            <strong>番號:</strong>
            <span class="value">ABP-123</span>
          </div>
        </nav>
        """
        tree = HTMLParser(html)
        assert self.scraper._parse_number(tree) == "ABP-123"

    def test_via_span_value_with_alternative_label(self) -> None:
        html = """
        <nav class="movie-panel-info">
          <div class="panel-block">
            <strong>番号:</strong>
            <span class="value">XYZ-999</span>
          </div>
        </nav>
        """
        tree = HTMLParser(html)
        assert self.scraper._parse_number(tree) == "XYZ-999"

    def test_english_label_id_with_clipboard(self) -> None:
        """英文标签 ID:，含 data-clipboard-text。"""
        html = """
        <nav class="movie-panel-info">
          <div class="panel-block first-block">
            <strong>ID:</strong>
            <span class="value"><a>101413</a>-455</span>
            <a class="button copy-to-clipboard" data-clipboard-text="101413-455">Copy</a>
          </div>
        </nav>
        """
        tree = HTMLParser(html)
        assert self.scraper._parse_number(tree) == "101413-455"

    def test_english_label_id_via_span(self) -> None:
        """英文标签 ID:，无 clipboard，从 span.value 提取。"""
        html = """
        <nav class="movie-panel-info">
          <div class="panel-block first-block">
            <strong>ID:</strong>
            <span class="value">101413-455</span>
          </div>
        </nav>
        """
        tree = HTMLParser(html)
        assert self.scraper._parse_number(tree) == "101413-455"

    def test_numeric_id_via_clipboard(self) -> None:
        """纯数字番号如 101413-455，从 clipboard 提取。"""
        html = """
        <nav class="movie-panel-info">
          <div class="panel-block first-block">
            <strong>番號:</strong>
            <span class="value"><a>101413</a>-455</span>
            <a class="button copy-to-clipboard" data-clipboard-text="101413-455">Copy</a>
          </div>
        </nav>
        """
        tree = HTMLParser(html)
        assert self.scraper._parse_number(tree) == "101413-455"

    def test_fallback_regex_from_title(self) -> None:
        html = """
        <div class="video-detail">
          <h2 class="title is-4">
            <strong class="current-title">ABC-123 Some Title</strong>
          </h2>
        </div>
        """
        tree = HTMLParser(html)
        assert self.scraper._parse_number(tree) == "ABC-123"

    def test_fallback_regex_with_underscore(self) -> None:
        html = """
        <div class="video-detail">
          <h2 class="title is-4">
            <strong class="current-title">ABC_123 Some Title</strong>
          </h2>
        </div>
        """
        tree = HTMLParser(html)
        assert self.scraper._parse_number(tree) == "ABC-123"

    def test_fallback_regex_pads_trailing_digits(self) -> None:
        html = "<h2>ABC-01</h2>"
        tree = HTMLParser(html)
        assert self.scraper._parse_number(tree) == "ABC-001"

    def test_fallback_numeric_regex_from_title(self) -> None:
        """兜底：纯数字番号如 101413-455 从标题中提取。"""
        html = """
        <div class="video-detail">
          <h2 class="title is-4">
            <strong class="current-title">101413-455 スーパーアイドル野外露出浴衣生姦</strong>
          </h2>
        </div>
        """
        tree = HTMLParser(html)
        assert self.scraper._parse_number(tree) == "101413-455"

    def test_no_number_found(self) -> None:
        html = "<html><body><p>No number here</p></body></html>"
        tree = HTMLParser(html)
        assert self.scraper._parse_number(tree) is None

    def test_empty_html(self) -> None:
        tree = HTMLParser("")
        assert self.scraper._parse_number(tree) is None

    def test_clipboard_text_takes_precedence(self) -> None:
        html = """
        <nav class="movie-panel-info">
          <div class="panel-block first-block">
            <strong>番號:</strong>
            <span class="value">DIFFERENT-999</span>
            <a class="button copy-to-clipboard" data-clipboard-text="IPVR-335">Copy</a>
          </div>
        </nav>
        """
        tree = HTMLParser(html)
        assert self.scraper._parse_number(tree) == "IPVR-335"


class TestParsePlot:
    def setup_method(self) -> None:
        self.scraper = JavdbScraper()

    def test_div_description(self) -> None:
        html = '<div class="description">A beautiful story about love.</div>'
        tree = HTMLParser(html)
        assert self.scraper._parse_plot(tree) == "A beautiful story about love."

    def test_div_synopsis(self) -> None:
        html = '<div class="synopsis">A great synopsis here.</div>'
        tree = HTMLParser(html)
        assert self.scraper._parse_plot(tree) == "A great synopsis here."

    def test_section_introduction(self) -> None:
        html = '<section id="introduction">Introduction content.</section>'
        tree = HTMLParser(html)
        assert self.scraper._parse_plot(tree) == "Introduction content."

    def test_p_description(self) -> None:
        html = '<p class="description">A short description.</p>'
        tree = HTMLParser(html)
        assert self.scraper._parse_plot(tree) == "A short description."

    def test_prefer_div_description_over_fallback(self) -> None:
        html = """
        <div class="description">Primary description.</div>
        <section id="introduction">Fallback intro.</section>
        """
        tree = HTMLParser(html)
        assert self.scraper._parse_plot(tree) == "Primary description."

    def test_empty_html(self) -> None:
        tree = HTMLParser("")
        assert self.scraper._parse_plot(tree) is None

    def test_plot_with_html_tags(self) -> None:
        html = '<div class="description">Line 1<br>Line 2<br>Line 3</div>'
        tree = HTMLParser(html)
        assert self.scraper._parse_plot(tree) == "Line 1Line 2Line 3"


class TestParseDates:
    def setup_method(self) -> None:
        self.scraper = JavdbScraper()

    def test_standard_date_label(self) -> None:
        html = """
        <div class="panel-block">
          <strong>日期:</strong>
          <span class="value">2025-10-23</span>
        </div>
        """
        tree = HTMLParser(html)
        assert self.scraper._parse_dates(tree) == (2025, "2025-10-23")

    def test_chinese_release_label(self) -> None:
        html = """
        <div class="panel-block">
          <strong>發行日期:</strong>
          <span class="value">2024-03-15</span>
        </div>
        """
        tree = HTMLParser(html)
        assert self.scraper._parse_dates(tree) == (2024, "2024-03-15")

    def test_simplified_chinese_release_label(self) -> None:
        html = """
        <div class="panel-block">
          <strong>发行日期:</strong>
          <span class="value">2024-03-15</span>
        </div>
        """
        tree = HTMLParser(html)
        assert self.scraper._parse_dates(tree) == (2024, "2024-03-15")

    def test_listing_date_label(self) -> None:
        html = """
        <div class="panel-block">
          <strong>上市日期:</strong>
          <span class="value">2023-12-01</span>
        </div>
        """
        tree = HTMLParser(html)
        assert self.scraper._parse_dates(tree) == (2023, "2023-12-01")

    def test_no_date(self) -> None:
        html = """
        <div class="panel-block">
          <strong>Some Other Field:</strong>
          <span class="value">Some Value</span>
        </div>
        """
        tree = HTMLParser(html)
        assert self.scraper._parse_dates(tree) == (None, None)

    def test_empty_html(self) -> None:
        tree = HTMLParser("")
        assert self.scraper._parse_dates(tree) == (None, None)

    def test_date_with_no_year_block(self) -> None:
        html = """
        <div class="panel-block">
          <strong>日期:</strong>
          <span class="value"></span>
        </div>
        """
        tree = HTMLParser(html)
        assert self.scraper._parse_dates(tree) == (None, None)


class TestParseRuntime:
    def setup_method(self) -> None:
        self.scraper = JavdbScraper()

    def test_with_minutes_traditional(self) -> None:
        html = """
        <div class="panel-block">
          <strong>片長:</strong>
          <span class="value">120分鐘</span>
        </div>
        """
        tree = HTMLParser(html)
        assert self.scraper._parse_runtime(tree) == 120

    def test_with_min_simplified(self) -> None:
        html = """
        <div class="panel-block">
          <strong>时长:</strong>
          <span class="value">95分</span>
        </div>
        """
        tree = HTMLParser(html)
        assert self.scraper._parse_runtime(tree) == 95

    def test_with_min_english(self) -> None:
        html = """
        <div class="panel-block">
          <strong>Duration:</strong>
          <span class="value">135 min</span>
        </div>
        """
        tree = HTMLParser(html)
        assert self.scraper._parse_runtime(tree) == 135

    def test_no_runtime(self) -> None:
        html = """
        <div class="panel-block">
          <strong>Some Other Field:</strong>
          <span class="value">Some Value</span>
        </div>
        """
        tree = HTMLParser(html)
        assert self.scraper._parse_runtime(tree) is None

    def test_empty_html(self) -> None:
        tree = HTMLParser("")
        assert self.scraper._parse_runtime(tree) is None

    def test_multiple_numbers_only_first_extracted(self) -> None:
        html = """
        <div class="panel-block">
          <strong>片長:</strong>
          <span class="value">60分鐘 1時間</span>
        </div>
        """
        tree = HTMLParser(html)
        assert self.scraper._parse_runtime(tree) == 60


class TestParseGenres:
    def setup_method(self) -> None:
        self.scraper = JavdbScraper()

    def test_from_category_panel(self) -> None:
        html = """
        <nav class="movie-panel-info">
          <div class="panel-block">
            <strong>類別:</strong>
            <span class="value">
              <a>情侶</a>,
              <a>校園</a>,
              <a>純愛</a>
            </span>
          </div>
        </nav>
        """
        tree = HTMLParser(html)
        assert self.scraper._parse_genres(tree) == ["情侶", "校園", "純愛"]

    def test_simplified_chinese_label(self) -> None:
        html = """
        <nav class="movie-panel-info">
          <div class="panel-block">
            <strong>类别:</strong>
            <span class="value"><a>喜剧</a>, <a>动作</a></span>
          </div>
        </nav>
        """
        tree = HTMLParser(html)
        assert self.scraper._parse_genres(tree) == ["喜剧", "动作"]

    def test_fallback_category_tags(self) -> None:
        html = '<a class="category" href="/tag/1">Action</a><a class="tag" href="/tag/2">Drama</a>'
        tree = HTMLParser(html)
        result = self.scraper._parse_genres(tree)
        assert "Action" in result
        assert "Drama" in result

    def test_fallback_span_category(self) -> None:
        html = '<span class="category"><a>Romance</a></span>'
        tree = HTMLParser(html)
        assert self.scraper._parse_genres(tree) == ["Romance"]

    def test_fallback_div_tags(self) -> None:
        html = '<div class="tags"><a>Horror</a><a>Thriller</a></div>'
        tree = HTMLParser(html)
        assert self.scraper._parse_genres(tree) == ["Horror", "Thriller"]

    def test_no_duplicates(self) -> None:
        html = """
        <nav class="movie-panel-info">
          <div class="panel-block">
            <strong>類別:</strong>
            <span class="value">
              <a>情侶</a>,
              <a>情侶</a>
            </span>
          </div>
        </nav>
        """
        tree = HTMLParser(html)
        assert self.scraper._parse_genres(tree) == ["情侶"]

    def test_empty_html(self) -> None:
        tree = HTMLParser("")
        assert self.scraper._parse_genres(tree) == []

    def test_no_genres(self) -> None:
        html = "<html><body><p>No genres here</p></body></html>"
        tree = HTMLParser(html)
        assert self.scraper._parse_genres(tree) == []


class TestParseActors:
    def setup_method(self) -> None:
        self.scraper = JavdbScraper()

    def test_actors_with_female_symbol(self) -> None:
        html = """
        <nav class="movie-panel-info">
          <div class="panel-block">
            <strong>演員:</strong>
            <span class="value">
              <a href="/actors/123">藤咲舞</a><strong class="symbol female">♀</strong>
              <a href="/actors/456">葵つかさ</a><strong class="symbol female">♀</strong>
            </span>
          </div>
        </nav>
        """
        tree = HTMLParser(html)
        result = self.scraper._parse_actors(tree)
        assert len(result) == 2
        assert result[0] == Actor(name="藤咲舞", role=None, thumb=None)
        assert result[1] == Actor(name="葵つかさ", role=None, thumb=None)

    def test_simplified_chinese_label(self) -> None:
        html = """
        <nav class="movie-panel-info">
          <div class="panel-block">
            <strong>演员:</strong>
            <span class="value"><a href="/actors/789">田中丽奈</a></span>
          </div>
        </nav>
        """
        tree = HTMLParser(html)
        result = self.scraper._parse_actors(tree)
        assert result == [Actor(name="田中丽奈", role=None, thumb=None)]

    def test_no_actors_panel(self) -> None:
        html = """<nav class="movie-panel-info">
          <div class="panel-block">
            <strong>類別:</strong>
            <span class="value"><a>Action</a></span>
          </div>
        </nav>"""
        tree = HTMLParser(html)
        assert self.scraper._parse_actors(tree) == []

    def test_empty_html(self) -> None:
        tree = HTMLParser("")
        assert self.scraper._parse_actors(tree) == []

    def test_actors_with_empty_name_skipped(self) -> None:
        html = """
        <nav class="movie-panel-info">
          <div class="panel-block">
            <strong>演員:</strong>
            <span class="value">
              <a href="/actors/1">有用</a>
              <a href="/actors/2">  </a>
              <a href="/actors/3">也有用</a>
            </span>
          </div>
        </nav>
        """
        tree = HTMLParser(html)
        result = self.scraper._parse_actors(tree)
        assert len(result) == 2
        assert result[0].name == "有用"
        assert result[1].name == "也有用"


class TestParseCompanies:
    def setup_method(self) -> None:
        self.scraper = JavdbScraper()

    def test_all_three(self) -> None:
        html = """
        <nav class="movie-panel-info">
          <div class="panel-block">
            <strong>片商:</strong>
            <span class="value"><a>IDEA POCKET</a></span>
          </div>
          <div class="panel-block">
            <strong>發行:</strong>
            <span class="value"><a>IP-released</a></span>
          </div>
          <div class="panel-block">
            <strong>系列:</strong>
            <span class="value"><a>アイポケ8KVR</a></span>
          </div>
        </nav>
        """
        tree = HTMLParser(html)
        result = self.scraper._parse_companies(tree)
        assert result == ("IDEA POCKET", "IP-released", "アイポケ8KVR")

    def test_only_studio(self) -> None:
        html = """
        <nav class="movie-panel-info">
          <div class="panel-block">
            <strong>片商:</strong>
            <span class="value"><a>SOD Create</a></span>
          </div>
        </nav>
        """
        tree = HTMLParser(html)
        result = self.scraper._parse_companies(tree)
        assert result == ("SOD Create", None, None)

    def test_english_labels(self) -> None:
        html = """
        <nav class="movie-panel-info">
          <div class="panel-block">
            <strong>Studio:</strong>
            <span class="value"><a>Prestige</a></span>
          </div>
          <div class="panel-block">
            <strong>Label:</strong>
            <span class="value"><a>Premium</a></span>
          </div>
          <div class="panel-block">
            <strong>Series:</strong>
            <span class="value"><a>Premium Beautiful</a></span>
          </div>
        </nav>
        """
        tree = HTMLParser(html)
        result = self.scraper._parse_companies(tree)
        assert result == ("Prestige", "Premium", "Premium Beautiful")

    def test_simplified_chinese(self) -> None:
        html = """
        <nav class="movie-panel-info">
          <div class="panel-block">
            <strong>发行:</strong>
            <span class="value"><a>发行商</a></span>
          </div>
        </nav>
        """
        tree = HTMLParser(html)
        result = self.scraper._parse_companies(tree)
        assert result == (None, "发行商", None)

    def test_none_present(self) -> None:
        html = """<nav class="movie-panel-info">
          <div class="panel-block">
            <strong>類別:</strong>
            <span class="value"><a>Action</a></span>
          </div>
        </nav>"""
        tree = HTMLParser(html)
        result = self.scraper._parse_companies(tree)
        assert result == (None, None, None)

    def test_empty_html(self) -> None:
        tree = HTMLParser("")
        result = self.scraper._parse_companies(tree)
        assert result == (None, None, None)

    def test_empty_value_text_skipped(self) -> None:
        html = """
        <nav class="movie-panel-info">
          <div class="panel-block">
            <strong>片商:</strong>
            <span class="value"></span>
          </div>
        </nav>
        """
        tree = HTMLParser(html)
        result = self.scraper._parse_companies(tree)
        assert result == (None, None, None)


class TestParseDirectorsAndRating:
    def setup_method(self) -> None:
        self.scraper = JavdbScraper()

    def test_both_director_and_rating(self) -> None:
        html = """
        <nav class="movie-panel-info">
          <div class="panel-block">
            <strong>導演:</strong>
            <span class="value"><a>山田太郎</a></span>
          </div>
          <div class="panel-block">
            <strong>評分:</strong>
            <span class="value">7.5</span>
          </div>
        </nav>
        """
        tree = HTMLParser(html)
        directors, rating = self.scraper._parse_directors_and_rating(tree)
        assert directors == ["山田太郎"]
        assert rating == 7.5

    def test_director_only(self) -> None:
        html = """
        <nav class="movie-panel-info">
          <div class="panel-block">
            <strong>导演:</strong>
            <span class="value"><a>李导演</a></span>
          </div>
        </nav>
        """
        tree = HTMLParser(html)
        directors, rating = self.scraper._parse_directors_and_rating(tree)
        assert directors == ["李导演"]
        assert rating is None

    def test_rating_only(self) -> None:
        html = """
        <nav class="movie-panel-info">
          <div class="panel-block">
            <strong>評分:</strong>
            <span class="value">8</span>
          </div>
        </nav>
        """
        tree = HTMLParser(html)
        directors, rating = self.scraper._parse_directors_and_rating(tree)
        assert directors == []
        assert rating == 8.0

    def test_english_director_label(self) -> None:
        html = """
        <nav class="movie-panel-info">
          <div class="panel-block">
            <strong>Director:</strong>
            <span class="value"><a>Jane Smith</a><a>John Doe</a></span>
          </div>
        </nav>
        """
        tree = HTMLParser(html)
        directors, rating = self.scraper._parse_directors_and_rating(tree)
        assert directors == ["Jane Smith", "John Doe"]
        assert rating is None

    def test_rating_with_decimal_in_nested_div(self) -> None:
        html = """
        <div class="panel-block">
          <strong>评分:</strong>
          <span class="value">9.3</span>
        </div>
        """
        tree = HTMLParser(html)
        directors, rating = self.scraper._parse_directors_and_rating(tree)
        assert directors == []
        assert rating == 9.3

    def test_missing_both(self) -> None:
        html = "<html><body><p>No data here</p></body></html>"
        tree = HTMLParser(html)
        directors, rating = self.scraper._parse_directors_and_rating(tree)
        assert directors == []
        assert rating is None

    def test_empty_html(self) -> None:
        tree = HTMLParser("")
        directors, rating = self.scraper._parse_directors_and_rating(tree)
        assert directors == []
        assert rating is None

    def test_no_duplicate_directors(self) -> None:
        html = """
        <nav class="movie-panel-info">
          <div class="panel-block">
            <strong>導演:</strong>
            <span class="value"><a>山田太郎</a><a>山田太郎</a></span>
          </div>
        </nav>
        """
        tree = HTMLParser(html)
        directors, rating = self.scraper._parse_directors_and_rating(tree)
        assert directors == ["山田太郎"]

    def test_rating_english_label(self) -> None:
        html = """
        <div class="panel-block">
          <strong>Rating:</strong>
          <span class="value">6.8</span>
        </div>
        """
        tree = HTMLParser(html)
        directors, rating = self.scraper._parse_directors_and_rating(tree)
        assert directors == []
        assert rating == 6.8


class TestParseImages:
    def setup_method(self) -> None:
        self.scraper = JavdbScraper()

    def test_modern_structure(self) -> None:
        html = """
        <div class="column column-video-cover">
          <a href="https://example.com/covers/poster.jpg"><img src="https://example.com/covers/poster.jpg" class="video-cover"></a>
        </div>
        <div class="tile-images preview-images">
          <a class="tile-item" href="https://example.com/samples/_l_0.jpg"><img src="https://example.com/samples/_s_0.jpg"></a>
          <a class="tile-item" href="https://example.com/samples/_l_1.jpg"><img src="https://example.com/samples/_s_1.jpg"></a>
        </div>
        """
        tree = HTMLParser(html)
        posters, art = self.scraper._parse_images(tree, base_url="https://javdb.com")
        assert posters == ["https://example.com/covers/poster.jpg"]
        assert art == [
            "https://example.com/samples/_l_0.jpg",
            "https://example.com/samples/_l_1.jpg",
        ]

    def test_legacy_fallback_images(self) -> None:
        html = """
        <div class="column-video-cover">
          <a href="https://example.com/cover.jpg"><img src="https://example.com/cover.jpg"></a>
        </div>
        <div class="sample-images">
          <img data-src="https://example.com/samples/001.jpg">
          <img data-src="https://example.com/samples/002.jpg">
        </div>
        """
        tree = HTMLParser(html)
        posters, art = self.scraper._parse_images(tree, base_url="https://javdb.com")
        assert posters == ["https://example.com/cover.jpg"]
        assert art == [
            "https://example.com/samples/001.jpg",
            "https://example.com/samples/002.jpg",
        ]

    def test_no_cover_or_images(self) -> None:
        html = "<html><body><p>No images</p></body></html>"
        tree = HTMLParser(html)
        posters, art = self.scraper._parse_images(tree, base_url="https://javdb.com")
        assert posters == []
        assert art == []

    def test_cover_with_relative_urls(self) -> None:
        html = """
        <div class="column column-video-cover">
          <a href="/covers/poster.jpg"><img src="/covers/poster.jpg"></a>
        </div>
        """
        tree = HTMLParser(html)
        posters, art = self.scraper._parse_images(
            tree, base_url="https://javdb.com/v/abc"
        )
        assert posters == ["https://javdb.com/covers/poster.jpg"]

    def test_empty_html(self) -> None:
        tree = HTMLParser("")
        posters, art = self.scraper._parse_images(tree, base_url="https://javdb.com")
        assert posters == []
        assert art == []

    def test_cover_fallback_selectors(self) -> None:
        html = '<img class="video-cover" src="https://example.com/cover.jpg">'
        tree = HTMLParser(html)
        posters, art = self.scraper._parse_images(tree, base_url="https://javdb.com")
        assert posters == ["https://example.com/cover.jpg"]
        assert art == []

    def test_no_duplicate_art(self) -> None:
        html = """
        <div class="tile-images preview-images">
          <a class="tile-item" href="https://example.com/same.jpg"><img src="https://example.com/same.jpg"></a>
          <a class="tile-item" href="https://example.com/same.jpg"><img src="https://example.com/same.jpg"></a>
        </div>
        """
        tree = HTMLParser(html)
        posters, art = self.scraper._parse_images(tree, base_url="https://javdb.com")
        assert art == ["https://example.com/same.jpg"]


class TestAbspathUrl:
    def setup_method(self) -> None:
        self.scraper = JavdbScraper()

    def test_absolute_url_stays(self) -> None:
        result = self.scraper._abspath_url(
            "https://example.com/image.jpg", "https://javdb.com/v/abc"
        )
        assert result == "https://example.com/image.jpg"

    def test_relative_url_resolved(self) -> None:
        result = self.scraper._abspath_url(
            "/covers/poster.jpg", "https://javdb.com/v/abc"
        )
        assert result == "https://javdb.com/covers/poster.jpg"

    def test_protocol_relative_url(self) -> None:
        result = self.scraper._abspath_url(
            "//cdn.example.com/image.jpg", "https://javdb.com/v/abc"
        )
        assert result == "https://cdn.example.com/image.jpg"

    def test_protocol_relative_with_http_base(self) -> None:
        result = self.scraper._abspath_url(
            "//cdn.example.com/image.jpg", "http://javdb.com/v/abc"
        )
        assert result == "http://cdn.example.com/image.jpg"

    def test_relative_with_query_params(self) -> None:
        result = self.scraper._abspath_url(
            "/image.jpg?w=800", "https://javdb.com/v/abc"
        )
        assert result == "https://javdb.com/image.jpg?w=800"


class TestGetImgUrl:
    def setup_method(self) -> None:
        self.scraper = JavdbScraper()

    def test_data_src(self) -> None:
        html = '<img data-src="https://example.com/image.jpg">'
        tree = HTMLParser(html)
        node = tree.css_first("img")
        assert node is not None
        result = self.scraper._get_img_url(node, base_url="https://javdb.com")
        assert result == "https://example.com/image.jpg"

    def test_src_fallback(self) -> None:
        html = '<img src="https://example.com/image.jpg">'
        tree = HTMLParser(html)
        node = tree.css_first("img")
        assert node is not None
        result = self.scraper._get_img_url(node, base_url="https://javdb.com")
        assert result == "https://example.com/image.jpg"

    def test_data_src_preferred_over_src(self) -> None:
        html = '<img data-src="https://example.com/highres.jpg" src="https://example.com/thumb.jpg">'
        tree = HTMLParser(html)
        node = tree.css_first("img")
        assert node is not None
        result = self.scraper._get_img_url(node, base_url="https://javdb.com")
        assert result == "https://example.com/highres.jpg"

    def test_no_attrs(self) -> None:
        html = "<img>"
        tree = HTMLParser(html)
        node = tree.css_first("img")
        assert node is not None
        result = self.scraper._get_img_url(node, base_url="https://javdb.com")
        assert result is None

    def test_relative_data_src(self) -> None:
        html = '<img data-src="/images/photo.jpg">'
        tree = HTMLParser(html)
        node = tree.css_first("img")
        assert node is not None
        result = self.scraper._get_img_url(node, base_url="https://javdb.com")
        assert result == "https://javdb.com/images/photo.jpg"


class TestParseSearchResults:
    def setup_method(self) -> None:
        self.scraper = JavdbScraper()

    def test_normal_search_result(self) -> None:
        html = """
        <div class="movie-list">
          <div class="item">
            <a class="box" href="/v/abc123">
              <div class="video-title"><strong>IPVR-335</strong> 日文タイトル</div>
              <div class="meta">10/23/2024</div>
              <img src="https://example.com/posters/001.jpg">
            </a>
          </div>
        </div>
        """
        results = self.scraper._parse_search_results(
            html, base_url="https://javdb.com/search?q=test"
        )
        assert len(results) == 1
        r = results[0]
        assert r.title == "IPVR-335日文タイトル"
        assert r.number == "IPVR-335"
        assert r.url == "https://javdb.com/v/abc123"
        assert r.poster_url == "https://example.com/posters/001.jpg"
        assert r.date == "2024-10-23"

    def test_multiple_results(self) -> None:
        html = """
        <div class="movie-list">
          <div class="item">
            <a class="box" href="/v/abc123">
              <div class="video-title"><strong>IPVR-335</strong> Title A</div>
              <div class="meta">01/15/2024</div>
              <img src="https://example.com/a.jpg">
            </a>
          </div>
          <div class="item">
            <a class="box" href="/v/def456">
              <div class="video-title"><strong>ABP-999</strong> Title B</div>
              <div class="meta">02/20/2024</div>
              <img src="https://example.com/b.jpg">
            </a>
          </div>
        </div>
        """
        results = self.scraper._parse_search_results(html, base_url="https://javdb.com")
        assert len(results) == 2
        assert results[0].number == "IPVR-335"
        assert results[1].number == "ABP-999"

    def test_missing_fields(self) -> None:
        html = """
        <div class="movie-list">
          <div class="item">
            <a class="box" href="/v/abc123">
              <div class="video-title"><strong>IPVR-335</strong> Title</div>
            </a>
          </div>
        </div>
        """
        results = self.scraper._parse_search_results(html, base_url="https://javdb.com")
        assert len(results) == 1
        r = results[0]
        assert r.title == "IPVR-335Title"
        assert r.number == "IPVR-335"
        assert r.date is None
        assert r.poster_url is None

    def test_no_link_in_item_skipped(self) -> None:
        html = """
        <div class="movie-list">
          <div class="item">
            <div class="video-title"><strong>IPVR-335</strong> Title</div>
          </div>
        </div>
        """
        results = self.scraper._parse_search_results(html, base_url="https://javdb.com")
        assert len(results) == 0

    def test_href_not_starting_with_v_skipped(self) -> None:
        html = """
        <div class="movie-list">
          <div class="item">
            <a class="box" href="/search?q=test">
              <div class="video-title"><strong>IPVR-335</strong> Title</div>
            </a>
          </div>
        </div>
        """
        results = self.scraper._parse_search_results(html, base_url="https://javdb.com")
        assert len(results) == 0

    def test_empty_html(self) -> None:
        results = self.scraper._parse_search_results("", base_url="https://javdb.com")
        assert results == []

    def test_no_movie_list_div(self) -> None:
        html = "<html><body><p>Not found</p></body></html>"
        results = self.scraper._parse_search_results(html, base_url="https://javdb.com")
        assert results == []

    def test_poster_with_relative_url(self) -> None:
        html = """
        <div class="movie-list">
          <div class="item">
            <a class="box" href="/v/abc123">
              <div class="video-title"><strong>IPVR-335</strong> Title</div>
              <div class="meta">10/23/2024</div>
              <img src="/posters/test.jpg">
            </a>
          </div>
        </div>
        """
        results = self.scraper._parse_search_results(
            html, base_url="https://javdb.com/search?q=test"
        )
        assert len(results) == 1
        assert results[0].poster_url == "https://javdb.com/posters/test.jpg"
