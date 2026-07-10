from __future__ import annotations

from xml.etree.ElementTree import fromstring

from app.services.nfo_service import build_movie_nfo


def _parse_nfo(nfo_text: str):
    return fromstring(nfo_text)


class TestBuildMovieNfo:
    def test_root_element(self, sample_movie_metadata):
        nfo = build_movie_nfo(sample_movie_metadata)
        root = _parse_nfo(nfo)
        assert root.tag == "movie"

    def test_title(self, sample_movie_metadata):
        nfo = build_movie_nfo(sample_movie_metadata)
        root = _parse_nfo(nfo)
        assert root.findtext("title") == "ABP-123 我的女友"

    def test_original_title(self, sample_movie_metadata):
        nfo = build_movie_nfo(sample_movie_metadata)
        root = _parse_nfo(nfo)
        assert root.findtext("originaltitle") == "ABP-123 俺の彼女"

    def test_sorttitle_is_number(self, sample_movie_metadata):
        nfo = build_movie_nfo(sample_movie_metadata)
        root = _parse_nfo(nfo)
        assert root.findtext("sorttitle") == "ABP-123"

    def test_sorttitle_fallback_to_title(self, minimal_metadata):
        nfo = build_movie_nfo(minimal_metadata)
        root = _parse_nfo(nfo)
        assert root.findtext("sorttitle") == "Unknown Title"

    def test_plot(self, sample_movie_metadata):
        nfo = build_movie_nfo(sample_movie_metadata)
        root = _parse_nfo(nfo)
        assert root.findtext("plot") == "这是一个测试剧情。"

    def test_year(self, sample_movie_metadata):
        nfo = build_movie_nfo(sample_movie_metadata)
        root = _parse_nfo(nfo)
        assert root.findtext("year") == "2024"

    def test_premiered_and_releasedate(self, sample_movie_metadata):
        nfo = build_movie_nfo(sample_movie_metadata)
        root = _parse_nfo(nfo)
        assert root.findtext("premiered") == "2024-03-15"
        assert root.findtext("releasedate") == "2024-03-15"

    def test_runtime(self, sample_movie_metadata):
        nfo = build_movie_nfo(sample_movie_metadata)
        root = _parse_nfo(nfo)
        assert root.findtext("runtime") == "120"

    def test_id_and_uniqueid(self, sample_movie_metadata):
        nfo = build_movie_nfo(sample_movie_metadata)
        root = _parse_nfo(nfo)
        assert root.findtext("id") == "ABP-123"
        uid = root.find("uniqueid")
        assert uid is not None
        assert uid.text == "ABP-123"
        assert uid.get("type") == "nfofetch"
        assert uid.get("default") == "true"

    def test_uniqueid_fallback_when_no_number(self, minimal_metadata):
        """number 为空时不应生成 <uniqueid>。"""
        nfo = build_movie_nfo(minimal_metadata)
        root = _parse_nfo(nfo)
        assert root.find("uniqueid") is None

    def test_studio_label_set(self, sample_movie_metadata):
        nfo = build_movie_nfo(sample_movie_metadata)
        root = _parse_nfo(nfo)
        assert root.findtext("studio") == "Prestige"
        assert root.findtext("label") == "Premium"
        # <series> 已改为 <set><name>
        assert root.find("series") is None
        set_name = root.findtext("set/name")
        assert set_name == "Premium Beautiful"

    def test_rating(self, sample_movie_metadata):
        nfo = build_movie_nfo(sample_movie_metadata)
        root = _parse_nfo(nfo)
        assert root.findtext("rating") == "7.5"

    def test_genres(self, sample_movie_metadata):
        nfo = build_movie_nfo(sample_movie_metadata)
        root = _parse_nfo(nfo)
        genres = [el.text for el in root.findall("genre")]
        assert "爱情" in genres
        assert "喜剧" in genres

    def test_tags(self, sample_movie_metadata):
        nfo = build_movie_nfo(sample_movie_metadata)
        root = _parse_nfo(nfo)
        tags = [el.text for el in root.findall("tag")]
        assert "HD" in tags

    def test_actors(self, sample_movie_metadata):
        nfo = build_movie_nfo(sample_movie_metadata)
        root = _parse_nfo(nfo)
        actors = root.findall("actor")
        assert len(actors) == 2
        assert actors[0].findtext("name") == "田中丽奈"
        assert actors[0].findtext("role") == "主演"
        assert actors[1].findtext("name") == "佐藤健"

    def test_directors(self, sample_movie_metadata):
        nfo = build_movie_nfo(sample_movie_metadata)
        root = _parse_nfo(nfo)
        directors = [el.text for el in root.findall("director")]
        assert "山田太郎" in directors

    def test_thumb_first_poster(self, sample_movie_metadata):
        nfo = build_movie_nfo(sample_movie_metadata)
        root = _parse_nfo(nfo)
        assert root.findtext("thumb") == "https://example.com/poster1.jpg"

    def test_original_title_fallback(self, minimal_metadata):
        """original_title 为空时回退到 title"""
        nfo = build_movie_nfo(minimal_metadata)
        root = _parse_nfo(nfo)
        assert root.findtext("originaltitle") == "Unknown Title"

    def test_minimal_metadata(self, minimal_metadata):
        nfo = build_movie_nfo(minimal_metadata)
        root = _parse_nfo(nfo)
        assert root.findtext("title") == "Unknown Title"
        assert root.find("year") is None
        assert root.find("rating") is None
