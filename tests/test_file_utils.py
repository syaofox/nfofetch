from __future__ import annotations

import time

import pytest

from pathlib import Path
from xml.etree import ElementTree as ET

from app.services.file_utils import (
    _read_nfo_art_mapping,
    _read_nfo_url_hash,
    _settle_rename,
    _url_hash,
    retry_on_oserror,
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


class TestRetryOnOSError:
    def test_success_first_try(self) -> None:
        call_count = [0]

        @retry_on_oserror(max_retries=2, base_delay=0.01)
        def ok() -> str:
            call_count[0] += 1
            return "done"

        assert ok() == "done"
        assert call_count[0] == 1

    def test_retry_then_success(self) -> None:
        call_count = [0]

        @retry_on_oserror(max_retries=2, base_delay=0.01)
        def flaky() -> str:
            call_count[0] += 1
            if call_count[0] < 3:
                raise OSError(5, "fake I/O error")
            return "ok"

        assert flaky() == "ok"
        assert call_count[0] == 3

    def test_exhaust_retries(self) -> None:
        call_count = [0]

        @retry_on_oserror(max_retries=1, base_delay=0.01)
        def always_fail() -> str:
            call_count[0] += 1
            raise OSError(122, "fake timeout")

        with pytest.raises(OSError, match="fake timeout"):
            always_fail()
        assert call_count[0] == 2  # 1 original + 1 retry

    def test_non_retryable_errno(self) -> None:
        @retry_on_oserror(max_retries=2, base_delay=0.01)
        def perm_error() -> str:
            raise OSError(13, "permission denied")

        with pytest.raises(OSError, match="permission denied"):
            perm_error()

    def test_custom_errno_set(self) -> None:
        call_count = [0]

        @retry_on_oserror(max_retries=1, base_delay=0.01, retryable_errnos={99})
        def custom_errno() -> str:
            call_count[0] += 1
            if call_count[0] == 1:
                raise OSError(99, "custom retryable")
            return "ok"

        assert custom_errno() == "ok"
        assert call_count[0] == 2

    def test_non_oserror_passes_through(self) -> None:
        @retry_on_oserror(max_retries=2, base_delay=0.01)
        def non_os() -> str:
            msg = "not an OSError"
            raise RuntimeError(msg)

        with pytest.raises(RuntimeError, match="not an OSError"):
            non_os()

    def test_preserves_function_metadata(self) -> None:
        @retry_on_oserror(max_retries=1, base_delay=0.01)
        def my_func() -> str:
            return "ok"

        assert my_func.__name__ == "my_func"


class TestSettleRename:
    def test_existing_path(self, tmp_path: Path) -> None:
        """存在的路径应正常通过（stat 成功 + settled）。"""
        p = tmp_path / "test.txt"
        p.write_text("hello")
        # 使用极短 settle 避免测试耗时
        _settle_rename(p, settle_secs=0.01, retries=1)

    def test_directory_path(self, tmp_path: Path) -> None:
        """目录路径也应正常通过。"""
        _settle_rename(tmp_path, settle_secs=0.01, retries=1)

    def test_nonexistent_path_raises(self, tmp_path: Path) -> None:
        """不存在的路径应抛出 OSError。"""
        p = tmp_path / "does_not_exist.txt"
        with pytest.raises(OSError, match="rename 后路径仍然不可访问"):
            _settle_rename(p, settle_secs=0.01, retries=1)

    def test_nonexistent_after_retries(self, tmp_path: Path) -> None:
        """持续 stat 失败应在耗尽重试后抛出异常。"""
        p = tmp_path / "gone.txt"
        with pytest.raises(OSError, match="rename 后路径仍然不可访问"):
            _settle_rename(p, settle_secs=0.01, retries=2)


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
