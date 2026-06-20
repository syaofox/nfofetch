from __future__ import annotations

import os
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.main import _natural_sort_key, _sort_browser_entries, app


class TestNaturalSortKey:
    def test_pure_numbers(self) -> None:
        assert _natural_sort_key("10") > _natural_sort_key("2")

    def test_mixed_text_and_numbers(self) -> None:
        keys = ["movie 1", "movie 2", "movie 10"]
        sorted_keys = sorted(keys, key=_natural_sort_key)
        assert sorted_keys == ["movie 1", "movie 2", "movie 10"]

    def test_same_prefix_different_numbers(self) -> None:
        keys = ["file10", "file2", "file1"]
        sorted_keys = sorted(keys, key=_natural_sort_key)
        assert sorted_keys == ["file1", "file2", "file10"]

    def test_no_numbers(self) -> None:
        keys = ["abc", "abd", "ab"]
        sorted_keys = sorted(keys, key=_natural_sort_key)
        assert sorted_keys == ["ab", "abc", "abd"]

    def test_case_insensitive(self) -> None:
        assert _natural_sort_key("ABC") == _natural_sort_key("abc")

    def test_empty_string(self) -> None:
        assert _natural_sort_key("") == _natural_sort_key("")


class TestSortBrowserEntries:
    def test_name_asc(self) -> None:
        entries = [
            {"name": "c", "name_lower": "c", "is_dir": False},
            {"name": "a", "name_lower": "a", "is_dir": False},
            {"name": "b", "name_lower": "b", "is_dir": False},
        ]
        _sort_browser_entries(entries, "name", "asc")
        assert [e["name"] for e in entries] == ["a", "b", "c"]

    def test_name_desc(self) -> None:
        entries = [
            {"name": "a", "name_lower": "a", "is_dir": False},
            {"name": "c", "name_lower": "c", "is_dir": False},
            {"name": "b", "name_lower": "b", "is_dir": False},
        ]
        _sort_browser_entries(entries, "name", "desc")
        assert [e["name"] for e in entries] == ["c", "b", "a"]

    def test_dirs_first_name_asc(self) -> None:
        entries = [
            {"name": "z_dir", "name_lower": "z_dir", "is_dir": True},
            {"name": "a_file", "name_lower": "a_file", "is_dir": False},
            {"name": "m_dir", "name_lower": "m_dir", "is_dir": True},
        ]
        _sort_browser_entries(entries, "name", "asc")
        assert [e["name"] for e in entries] == ["m_dir", "z_dir", "a_file"]

    def test_dirs_first_name_desc(self) -> None:
        entries = [
            {"name": "a_dir", "name_lower": "a_dir", "is_dir": True},
            {"name": "z_file", "name_lower": "z_file", "is_dir": False},
            {"name": "m_dir", "name_lower": "m_dir", "is_dir": True},
        ]
        _sort_browser_entries(entries, "name", "desc")
        assert [e["name"] for e in entries] == ["m_dir", "a_dir", "z_file"]

    def test_mtime_asc(self) -> None:
        entries = [
            {"name": "old", "name_lower": "old", "is_dir": False, "mtime": 100},
            {"name": "new", "name_lower": "new", "is_dir": False, "mtime": 200},
        ]
        _sort_browser_entries(entries, "mtime", "asc")
        assert [e["name"] for e in entries] == ["old", "new"]

    def test_mtime_desc(self) -> None:
        entries = [
            {"name": "old", "name_lower": "old", "is_dir": False, "mtime": 100},
            {"name": "new", "name_lower": "new", "is_dir": False, "mtime": 200},
        ]
        _sort_browser_entries(entries, "mtime", "desc")
        assert [e["name"] for e in entries] == ["new", "old"]

    def test_natural_asc(self) -> None:
        entries = [
            {"name": "movie 10", "name_lower": "movie 10", "is_dir": False},
            {"name": "movie 2", "name_lower": "movie 2", "is_dir": False},
            {"name": "movie 1", "name_lower": "movie 1", "is_dir": False},
        ]
        _sort_browser_entries(entries, "natural", "asc")
        assert [e["name"] for e in entries] == ["movie 1", "movie 2", "movie 10"]

    def test_natural_desc(self) -> None:
        entries = [
            {"name": "movie 1", "name_lower": "movie 1", "is_dir": False},
            {"name": "movie 10", "name_lower": "movie 10", "is_dir": False},
            {"name": "movie 2", "name_lower": "movie 2", "is_dir": False},
        ]
        _sort_browser_entries(entries, "natural", "desc")
        assert [e["name"] for e in entries] == ["movie 10", "movie 2", "movie 1"]

    def test_dirs_first_natural_asc(self) -> None:
        entries = [
            {"name": "dir 10", "name_lower": "dir 10", "is_dir": True},
            {"name": "file 2", "name_lower": "file 2", "is_dir": False},
            {"name": "dir 2", "name_lower": "dir 2", "is_dir": True},
        ]
        _sort_browser_entries(entries, "natural", "asc")
        assert [e["name"] for e in entries] == ["dir 2", "dir 10", "file 2"]

    def test_mtime_dirs_first(self) -> None:
        entries = [
            {"name": "z_dir", "name_lower": "z_dir", "is_dir": True, "mtime": 300},
            {"name": "a_file", "name_lower": "a_file", "is_dir": False, "mtime": 100},
            {"name": "m_dir", "name_lower": "m_dir", "is_dir": True, "mtime": 200},
        ]
        _sort_browser_entries(entries, "mtime", "asc")
        assert [e["name"] for e in entries] == ["m_dir", "z_dir", "a_file"]


class TestBrowseEndpoint:
    @pytest.fixture
    def browse_root(self, tmp_path: Path) -> Path:
        root = tmp_path / "browse_test"
        root.mkdir()
        (root / "movie 1.mp4").touch()
        (root / "movie 2.mp4").touch()
        (root / "movie 10.mp4").touch()
        (root / "a_movie.mp4").touch()
        subdir = root / "subdir"
        subdir.mkdir()
        (subdir / "inner.mp4").touch()
        return root

    @pytest.fixture
    def client(self, browse_root: Path, monkeypatch: pytest.MonkeyPatch) -> TestClient:
        monkeypatch.setenv("NFOFETCH_BROWSE_ROOT", str(browse_root))
        return TestClient(app)

    def test_default_sort(self, client: TestClient) -> None:
        resp = client.get("/browse")
        assert resp.status_code == 200
        html = resp.text
        assert "subdir/" in html
        assert "a_movie" in html
        assert "movie 10" in html

    def test_name_sort_asc(self, client: TestClient) -> None:
        resp = client.get("/browse?sort_by=name&sort_order=asc")
        assert resp.status_code == 200
        html = resp.text
        assert html.index("subdir") < html.index("a_movie")
        assert html.index("a_movie") < html.index("movie 10")

    def test_name_sort_desc(self, client: TestClient) -> None:
        resp = client.get("/browse?sort_by=name&sort_order=desc")
        assert resp.status_code == 200
        html = resp.text
        assert html.index("a_movie") > html.index("movie 2")

    def test_natural_sort_asc(self, client: TestClient) -> None:
        resp = client.get("/browse?sort_by=natural&sort_order=asc")
        assert resp.status_code == 200
        html = resp.text
        m1 = html.index("movie 1.mp4")
        m2 = html.index("movie 2.mp4")
        m10 = html.index("movie 10.mp4")
        assert m1 < m2 < m10

    def test_natural_sort_desc(self, client: TestClient) -> None:
        resp = client.get("/browse?sort_by=natural&sort_order=desc")
        assert resp.status_code == 200
        html = resp.text
        m1 = html.index("movie 1.mp4")
        m2 = html.index("movie 2.mp4")
        m10 = html.index("movie 10.mp4")
        assert m10 < m2 < m1

    def test_mtime_sort_asc(self, client: TestClient, browse_root: Path) -> None:
        old_file = browse_root / "a_movie.mp4"
        new_file = browse_root / "movie 1.mp4"
        os.utime(old_file, (1000000, 1000000))
        os.utime(new_file, (2000000, 2000000))
        resp = client.get("/browse?sort_by=mtime&sort_order=asc")
        assert resp.status_code == 200
        html = resp.text
        assert html.index("a_movie") < html.index("movie 1")

    def test_mtime_sort_desc(self, client: TestClient, browse_root: Path) -> None:
        old_file = browse_root / "a_movie.mp4"
        new_file = browse_root / "movie 1.mp4"
        os.utime(old_file, (1000000, 1000000))
        os.utime(new_file, (2000000, 2000000))
        resp = client.get("/browse?sort_by=mtime&sort_order=desc")
        assert resp.status_code == 200
        html = resp.text
        assert html.index("movie 1") < html.index("a_movie")

    def test_sort_buttons_in_html(self, client: TestClient) -> None:
        resp = client.get("/browse?sort_by=name&sort_order=asc")
        assert resp.status_code == 200
        html = resp.text
        assert "nf-sort-btn-active" in html
        assert "window.nfSetSort('name')" in html
        assert "window.nfSetSort('natural')" in html
        assert "window.nfSetSort('mtime')" in html

    def test_empty_dir(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("NFOFETCH_BROWSE_ROOT", str(tmp_path))
        client = TestClient(app)
        resp = client.get("/browse")
        assert resp.status_code == 200
        html = resp.text
        assert "此目录下没有可显示的文件或子目录" in html

    def test_browse_root_default(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("NFOFETCH_BROWSE_ROOT", str(tmp_path))
        client = TestClient(app)
        resp = client.get("/browse")
        assert resp.status_code == 200


class TestBrowseDeleteEndpoint:
    """文件浏览器删除功能测试"""

    @pytest.fixture
    def browse_root(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
        root = tmp_path / "browse_test"
        root.mkdir()
        monkeypatch.setenv("NFOFETCH_BROWSE_ROOT", str(root))
        return root

    def test_delete_file(self, browse_root: Path) -> None:
        file = browse_root / "test.mp4"
        file.touch()
        client = TestClient(app)
        resp = client.post("/browse/delete", data={"path": str(file)})
        assert resp.status_code == 200
        assert resp.json() == {"ok": True}
        assert not file.exists()

    def test_delete_empty_directory(self, browse_root: Path) -> None:
        dir_path = browse_root / "subdir"
        dir_path.mkdir()
        client = TestClient(app)
        resp = client.post("/browse/delete", data={"path": str(dir_path)})
        assert resp.status_code == 200
        assert resp.json() == {"ok": True}
        assert not dir_path.exists()

    def test_delete_non_empty_directory_succeeds(self, browse_root: Path) -> None:
        dir_path = browse_root / "subdir"
        dir_path.mkdir()
        (dir_path / "file.txt").touch()
        client = TestClient(app)
        resp = client.post("/browse/delete", data={"path": str(dir_path)})
        assert resp.status_code == 200
        assert resp.json() == {"ok": True}
        assert not dir_path.exists()

    def test_delete_outside_root_fails(self, browse_root: Path) -> None:
        outside = browse_root.parent / "outside.txt"
        outside.touch()
        client = TestClient(app)
        resp = client.post("/browse/delete", data={"path": str(outside)})
        assert resp.status_code == 200
        assert resp.json() == {"ok": False}

    def test_delete_nonexistent_fails(self, browse_root: Path) -> None:
        missing = browse_root / "nonexistent.mp4"
        client = TestClient(app)
        resp = client.post("/browse/delete", data={"path": str(missing)})
        assert resp.status_code == 200
        assert resp.json() == {"ok": False}

    def test_delete_button_rendered_in_template(self, browse_root: Path) -> None:
        file = browse_root / "video.mp4"
        file.touch()
        client = TestClient(app)
        resp = client.get("/browse?sort_by=name")
        assert resp.status_code == 200
        assert "nfDeleteItem" in resp.text
        assert "nf-file-browser-delete-btn" in resp.text
