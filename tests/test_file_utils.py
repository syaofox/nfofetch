from __future__ import annotations

import time
from pathlib import Path

import pytest

from xml.etree import ElementTree as ET

from app.services.file_utils import (
    _parse_nfo_with_comments,
    _read_nfo_art_mapping,
    _read_nfo_comment_value,
    _read_nfo_url_hash,
    _url_hash,
    _write_delay,
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


class TestReadNfoCommentValue:
    def _make_nfo_with_comments(self, comments: list[str]) -> ET.Element:
        root = ET.Element("movie")
        for c in comments:
            root.append(ET.Comment(f" nfofetch:{c} "))
        return root

    def test_found(self) -> None:
        root = self._make_nfo_with_comments(["source_url=https://example.com"])
        assert _read_nfo_comment_value(root, "source_url") == "https://example.com"

    def test_missing_key(self) -> None:
        root = self._make_nfo_with_comments(["other_key=value"])
        assert _read_nfo_comment_value(root, "source_url") is None

    def test_none_root(self) -> None:
        assert _read_nfo_comment_value(None, "key") is None

    def test_no_comments(self) -> None:
        root = ET.Element("movie")
        assert _read_nfo_comment_value(root, "key") is None


class TestReadNfoUrlHashFromComment:
    """新版 _read_nfo_url_hash 也应能从 XML 注释中读取。"""

    def _make_nfo_from_comment(self, key: str, value: str) -> ET.Element:
        root = ET.Element("movie")
        root.append(ET.Comment(f" nfofetch:{key}={value} "))
        return root

    def test_read_from_comment(self) -> None:
        root = self._make_nfo_from_comment("poster_url_hash", "abc123def456")
        assert _read_nfo_url_hash(root, "poster_url_hash") == "abc123def456"

    def test_comment_preferred_over_element(self) -> None:
        """新版注释优先于旧版元素。"""
        h_comment = "comment_hash"
        root = ET.Element("movie")
        # 旧版元素
        el = ET.SubElement(root, "poster_url_hash")
        el.text = "element_hash"
        # 新版注释
        root.append(ET.Comment(f" nfofetch:poster_url_hash={h_comment} "))
        assert _read_nfo_url_hash(root, "poster_url_hash") == h_comment

    def test_fallback_to_element(self) -> None:
        """无注释时回退到旧版元素。"""
        root = ET.Element("movie")
        el = ET.SubElement(root, "poster_url_hash")
        el.text = "abc123def456"
        assert _read_nfo_url_hash(root, "poster_url_hash") == "abc123def456"


class TestReadNfoArtMappingFromComment:
    """新版 _read_nfo_art_mapping 也应能从 XML 注释中读取。"""

    def _make_nfo_from_comments(self, pairs: list[tuple[str, str]]) -> ET.Element:
        root = ET.Element("movie")
        for h, fn in pairs:
            root.append(ET.Comment(f" nfofetch:art_url {h}={fn} "))
        return root

    def test_read_from_comment_single(self) -> None:
        h = _url_hash("https://example.com/1.jpg")
        root = self._make_nfo_from_comments([(h, "01.jpg")])
        assert _read_nfo_art_mapping(root) == {h: "01.jpg"}

    def test_read_from_comment_multiple(self) -> None:
        h1 = _url_hash("https://example.com/1.jpg")
        h2 = _url_hash("https://example.com/2.jpg")
        root = self._make_nfo_from_comments([(h1, "01.jpg"), (h2, "02.jpg")])
        assert _read_nfo_art_mapping(root) == {h1: "01.jpg", h2: "02.jpg"}

    def test_no_art_comments(self) -> None:
        root = ET.Element("movie")
        root.append(ET.Comment(" nfofetch:other=value "))
        assert _read_nfo_art_mapping(root) == {}


class TestParseNfoWithComments:
    def test_parse_with_comments(self, tmp_path: Path) -> None:
        nfo_path = tmp_path / "movie.nfo"
        nfo_path.write_text(
            '<?xml version="1.0" encoding="utf-8"?>\n'
            "<movie>\n"
            "  <title>Test</title>\n"
            "  <!-- nfofetch:source_url=https://example.com -->\n"
            "</movie>",
            encoding="utf-8",
        )
        root = _parse_nfo_with_comments(nfo_path)
        assert root is not None
        assert root.findtext("title") == "Test"
        assert _read_nfo_comment_value(root, "source_url") == "https://example.com"

    def test_missing_file(self, tmp_path: Path) -> None:
        root = _parse_nfo_with_comments(tmp_path / "nonexistent.nfo")
        assert root is None


class TestWriteDelay:
    def test_zero_delay_does_not_sleep(self) -> None:
        """delay=0 时立即返回，不阻塞。"""
        start = time.monotonic()
        _write_delay(0)
        elapsed = time.monotonic() - start
        assert elapsed < 0.05

    def test_positive_delay_sleeps(self) -> None:
        """delay>0 时阻塞对应时长（误差容忍 0.05s）。"""
        start = time.monotonic()
        _write_delay(0.1)
        elapsed = time.monotonic() - start
        assert elapsed >= 0.05
        assert elapsed < 0.2

    def test_negative_delay_treated_as_zero(self) -> None:
        """负数 delay 不阻塞。"""
        start = time.monotonic()
        _write_delay(-0.1)
        elapsed = time.monotonic() - start
        assert elapsed < 0.05
