from __future__ import annotations

from pydantic import HttpUrl

from app.schemas import (
    Actor,
    MovieMetadata,
    Preset,
    ScrapeResult,
    SearchResult,
    UserSettings,
)


def _url(s: str) -> HttpUrl:
    return HttpUrl(s)


class TestActor:
    def test_minimal(self) -> None:
        actor = Actor(name="田中丽奈")
        assert actor.name == "田中丽奈"
        assert actor.role is None
        assert actor.thumb is None

    def test_full(self) -> None:
        actor = Actor(
            name="田中丽奈", role="主演", thumb=_url("https://example.com/thumb.jpg")
        )
        assert actor.role == "主演"


class TestMovieMetadata:
    def test_minimal(self) -> None:
        m = MovieMetadata(title="Test")
        assert m.title == "Test"
        assert m.number is None
        assert m.genres == []
        assert m.actors == []
        assert m.posters == []
        assert m.art == []

    def test_with_posters(self, sample_movie_metadata: MovieMetadata) -> None:
        assert len(sample_movie_metadata.posters) == 2
        assert (
            str(sample_movie_metadata.posters[0]) == "https://example.com/poster1.jpg"
        )

    def test_rating_range(self) -> None:
        m = MovieMetadata(title="Test", rating=9.9)
        assert m.rating == 9.9


class TestSearchResult:
    def test_minimal(self) -> None:
        r = SearchResult(title="Test", url="https://example.com/v/abc")
        assert r.number is None
        assert r.poster_url is None

    def test_full(self) -> None:
        r = SearchResult(
            title="ABP-123 Test",
            number="ABP-123",
            url="https://example.com/v/abc",
            poster_url="https://example.com/poster.jpg",
            date="2024-01-15",
        )
        assert r.number == "ABP-123"


class TestScrapeResult:
    def test_defaults(self) -> None:
        r = ScrapeResult()
        assert r.success is True
        assert r.message is None
        assert r.extra_images == []


class TestPreset:
    def test_defaults(self) -> None:
        p = Preset()
        assert p.rename_format == ""
        assert p.rename_dir == ""

    def test_round_trip(self) -> None:
        p = Preset(rename_format="{id}", rename_dir="{id}")
        d = p.model_dump()
        assert d["rename_format"] == "{id}"
        assert d["rename_dir"] == "{id}"
        restored = Preset.model_validate(d)
        assert restored.rename_format == "{id}"
        assert restored.rename_dir == "{id}"


class TestUserSettings:
    def test_defaults(self) -> None:
        s = UserSettings()
        assert s.rename_format == "[{actor}][{date}]{id}"
        assert s.last_browse_path == ""
        assert s.download_concurrency == 4
        assert s.presets == {}

    def test_with_presets(self) -> None:
        s = UserSettings()
        s.presets["标准"] = Preset(rename_format="{id}", rename_dir="{id}")
        d = s.model_dump()
        restored = UserSettings.model_validate(d)
        assert "标准" in restored.presets
        assert restored.presets["标准"].rename_format == "{id}"

    def test_javdb_cookie_default(self) -> None:
        s = UserSettings()
        assert s.javdb_cookie == ""

    def test_javdb_cookie_round_trip(self) -> None:
        s = UserSettings(javdb_cookie="theme=auto; over18=1; _jdb_session=xxx")
        d = s.model_dump()
        assert d["javdb_cookie"] == "theme=auto; over18=1; _jdb_session=xxx"
        restored = UserSettings.model_validate(d)
        assert restored.javdb_cookie == "theme=auto; over18=1; _jdb_session=xxx"

    def test_serial_writes_default(self) -> None:
        s = UserSettings()
        assert s.serial_writes is None

    def test_lock_enabled_default(self) -> None:
        s = UserSettings()
        assert s.lock_enabled is None

    def test_serial_writes_round_trip(self) -> None:
        s = UserSettings(serial_writes=True)
        d = s.model_dump()
        assert d["serial_writes"] is True
        restored = UserSettings.model_validate(d)
        assert restored.serial_writes is True

    def test_lock_enabled_round_trip(self) -> None:
        s = UserSettings(lock_enabled=True)
        d = s.model_dump()
        assert d["lock_enabled"] is True
        restored = UserSettings.model_validate(d)
        assert restored.lock_enabled is True

    def test_write_delay_default(self) -> None:
        s = UserSettings()
        assert s.write_delay is None

    def test_write_delay_round_trip(self) -> None:
        s = UserSettings(write_delay=0.5)
        d = s.model_dump()
        assert d["write_delay"] == 0.5
        restored = UserSettings.model_validate(d)
        assert restored.write_delay == 0.5

    def test_max_extra_images_default(self) -> None:
        s = UserSettings()
        assert s.max_extra_images is None

    def test_max_extra_images_round_trip(self) -> None:
        s = UserSettings(max_extra_images=16)
        d = s.model_dump()
        assert d["max_extra_images"] == 16
        restored = UserSettings.model_validate(d)
        assert restored.max_extra_images == 16
