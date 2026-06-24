from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from app.main import _cleanup_uploaded, app


def _make_test_image() -> bytes:
    """生成一个 1x1 红色 PNG 用于测试上传。"""
    img = Image.new("RGB", (1, 1), color=(255, 0, 0))
    buf = __import__("io").BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


TEST_PNG = _make_test_image()


class TestCleanupUploaded:
    def test_cleanup_single_file(self, tmp_path: Path) -> None:
        f = tmp_path / "test.jpg"
        f.write_bytes(b"test")
        _cleanup_uploaded(str(f))
        assert not f.exists()

    def test_cleanup_multiple_files(self, tmp_path: Path) -> None:
        f1 = tmp_path / "a.jpg"
        f2 = tmp_path / "b.jpg"
        f1.write_bytes(b"a")
        f2.write_bytes(b"b")
        _cleanup_uploaded(str(f1), str(f2))
        assert not f1.exists()
        assert not f2.exists()

    def test_cleanup_none_values(self) -> None:
        _cleanup_uploaded(None, "", None)

    def test_cleanup_nonexistent_file(self) -> None:
        _cleanup_uploaded("/tmp/nonexistent_12345.jpg")

    def test_cleanup_mixed(self, tmp_path: Path) -> None:
        f = tmp_path / "keep.jpg"
        f.write_bytes(b"keep")
        _cleanup_uploaded(None, str(f), "")
        assert not f.exists()


class TestUploadImageAPI:
    @pytest.fixture(autouse=True)
    def _setup(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        self.browse_root = tmp_path / "browse"
        self.browse_root.mkdir()
        monkeypatch.setenv("NFOFETCH_BROWSE_ROOT", str(self.browse_root))

    @pytest.fixture
    def client(self) -> TestClient:
        return TestClient(app)

    def test_upload_png(self, client: TestClient) -> None:
        resp = client.post(
            "/api/upload-image",
            files={"file": ("test.png", TEST_PNG, "image/png")},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "path" in data
        assert "serve_url" in data
        path = Path(data["path"])
        assert path.exists()
        assert path.read_bytes() == TEST_PNG

    def test_serve_url_format(self, client: TestClient) -> None:
        resp = client.post(
            "/api/upload-image",
            files={"file": ("test.png", TEST_PNG, "image/png")},
        )
        assert resp.status_code == 200
        data = resp.json()
        import tempfile

        tmp_dir = Path(tempfile.gettempdir()).resolve()
        expected_prefix = f"/api/uploaded-image?path={tmp_dir}/._nfofetch_upload_"
        assert data["serve_url"].startswith(expected_prefix)

    def test_upload_jpg(self, client: TestClient) -> None:
        img = Image.new("RGB", (1, 1), color=(0, 255, 0))
        buf = __import__("io").BytesIO()
        img.save(buf, format="JPEG")
        jpg_bytes = buf.getvalue()
        resp = client.post(
            "/api/upload-image",
            files={"file": ("test.jpg", jpg_bytes, "image/jpeg")},
        )
        assert resp.status_code == 200
        path = Path(resp.json()["path"])
        assert path.exists()

    def test_upload_webp(self, client: TestClient) -> None:
        img = Image.new("RGB", (2, 2), color=(0, 0, 255))
        buf = __import__("io").BytesIO()
        img.save(buf, format="WEBP")
        webp_bytes = buf.getvalue()
        resp = client.post(
            "/api/upload-image",
            files={"file": ("test.webp", webp_bytes, "image/webp")},
        )
        assert resp.status_code == 200

    def test_reject_non_image(self, client: TestClient) -> None:
        resp = client.post(
            "/api/upload-image",
            files={"file": ("test.txt", b"not an image", "text/plain")},
        )
        assert resp.status_code == 400

    def test_reject_wrong_extension(self, client: TestClient) -> None:
        resp = client.post(
            "/api/upload-image",
            files={"file": ("test.gif", b"fakegif", "image/gif")},
        )
        assert resp.status_code == 400

    def test_reject_oversized(self, client: TestClient) -> None:
        from app.main import MAX_UPLOAD_SIZE

        huge = b"x" * (MAX_UPLOAD_SIZE + 1)
        resp = client.post(
            "/api/upload-image",
            files={"file": ("huge.png", huge, "image/png")},
        )
        assert resp.status_code == 400

    def test_backward_compat_old_endpoint(self, client: TestClient) -> None:
        resp = client.post(
            "/api/upload-poster",
            files={"file": ("test.png", TEST_PNG, "image/png")},
        )
        assert resp.status_code == 200
        assert "path" in resp.json()

    def test_upload_to_system_tmp(self, client: TestClient) -> None:
        resp = client.post(
            "/api/upload-image",
            files={"file": ("test.png", TEST_PNG, "image/png")},
        )
        assert resp.status_code == 200
        path = Path(resp.json()["path"])
        import tempfile

        tmp_dir = Path(tempfile.gettempdir()).resolve()
        assert str(path).startswith(str(tmp_dir))
        assert "._nfofetch_upload_" in path.name

    def test_upload_then_file_is_readable(self, client: TestClient) -> None:
        resp = client.post(
            "/api/upload-image",
            files={"file": ("test.png", TEST_PNG, "image/png")},
        )
        assert resp.status_code == 200
        data = resp.json()
        serve_url = data["serve_url"]
        # serve_url 应能被 /api/uploaded-image 端点服务
        resp2 = client.get(serve_url)
        assert resp2.status_code == 200, f"serve failed: {resp2.text}"
        assert resp2.content == TEST_PNG
