from __future__ import annotations

import time

import pytest

from xml.etree import ElementTree as ET

from app.services.file_utils import (
    _read_nfo_art_mapping,
    _read_nfo_url_hash,
    _url_hash,
    run_with_timeout,
)


class TestRunWithTimeout:
    def test_success(self) -> None:
        result = run_with_timeout(lambda: 42, 5.0)
        assert result == 42

    def test_with_args(self) -> None:
        result = run_with_timeout(lambda a, b: a + b, 5.0, 3, 4)
        assert result == 7

    def test_timeout(self) -> None:
        with pytest.raises(TimeoutError):
            run_with_timeout(lambda: time.sleep(10), 0.05)

    def test_exception_propagated(self) -> None:
        def _fail() -> None:
            msg = "something went wrong"
            raise ValueError(msg)

        with pytest.raises(ValueError, match="something went wrong"):
            run_with_timeout(_fail, 5.0)


class TestUrlHash:
    def test_consistent(self) -> None:
        assert _url_hash("https://example.com/img.jpg") == _url_hash(
            "https://example.com/img.jpg"
        )

    def test_different(self) -> None:
        assert _url_hash("https://a.com/1.jpg") != _url_hash("https://b.com/2.jpg")

    def test_length(self) -> None:
        assert len(_url_hash("any-url")) == 12


class TestReadNfoUrlHash:
    def _make_nfo(self, tags: dict[str, str]) -> ET.Element:
        root = ET.Element("movie")
        for k, v in tags.items():
            el = ET.SubElement(root, k)
            el.text = v
        return root

    def test_found(self) -> None:
        root = self._make_nfo({"poster_url_hash": "abc123def456"})
        assert _read_nfo_url_hash(root, "poster_url_hash") == "abc123def456"

    def test_missing_tag(self) -> None:
        root = self._make_nfo({"title": "test"})
        assert _read_nfo_url_hash(root, "poster_url_hash") is None

    def test_empty_text(self) -> None:
        root = self._make_nfo({"poster_url_hash": ""})
        assert _read_nfo_url_hash(root, "poster_url_hash") is None

    def test_none_root(self) -> None:
        assert _read_nfo_url_hash(None, "poster_url_hash") is None

    def test_different_urls_different_hashes(self) -> None:
        root = self._make_nfo({"poster_url_hash": _url_hash("https://a.com/1.jpg")})
        assert _read_nfo_url_hash(root, "poster_url_hash") != _url_hash(
            "https://b.com/2.jpg"
        )


class TestReadNfoArtMapping:
    def _make_nfo(self, pairs: list[tuple[str, str]]) -> ET.Element:
        root = ET.Element("movie")
        for h, fn in pairs:
            el = ET.SubElement(root, "art_url")
            el.set("hash", h)
            el.text = fn
        return root

    def test_empty(self) -> None:
        root = self._make_nfo([])
        assert _read_nfo_art_mapping(root) == {}

    def test_single(self) -> None:
        h = _url_hash("https://example.com/1.jpg")
        root = self._make_nfo([(h, "01.jpg")])
        assert _read_nfo_art_mapping(root) == {h: "01.jpg"}

    def test_multiple(self) -> None:
        h1 = _url_hash("https://example.com/1.jpg")
        h2 = _url_hash("https://example.com/2.jpg")
        root = self._make_nfo([(h1, "01.jpg"), (h2, "02.jpg")])
        assert _read_nfo_art_mapping(root) == {h1: "01.jpg", h2: "02.jpg"}

    def test_dedup_by_hash(self) -> None:
        h = _url_hash("https://example.com/1.jpg")
        root = self._make_nfo([(h, "01.jpg"), (h, "02.jpg")])
        result = _read_nfo_art_mapping(root)
        assert len(result) == 1
        assert result[h] in ("01.jpg", "02.jpg")

    def test_none_root(self) -> None:
        assert _read_nfo_art_mapping(None) == {}
