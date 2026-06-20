from __future__ import annotations

import io
import tempfile
from pathlib import Path
from typing import Any, Iterator
from unittest.mock import patch

import httpx
from PIL import Image

from app.config import Settings
from app.services.file_utils import _TEMP_PREFIX
from app.services.image_utils import (
    _download_image,
    _download_image_with_crop,
    _download_to_temp,
)


def _make_fake_client(content: bytes) -> Any:
    """创建一个模拟 httpx.Client，stream GET 返回固定内容。"""

    class _FakeResponse:
        def raise_for_status(self) -> None:
            pass

        def iter_bytes(self, chunk_size: int = 4096) -> Iterator[bytes]:
            return iter([content])

        def __enter__(self) -> _FakeResponse:
            return self

        def __exit__(self, *args: Any) -> None:
            pass

    class _FakeClient:
        def __init__(self, **kwargs: Any) -> None:
            pass

        def stream(self, method: str, url: str, **kwargs: Any) -> _FakeResponse:
            return _FakeResponse()

        def __enter__(self) -> _FakeClient:
            return self

        def __exit__(self, *args: Any) -> None:
            pass

    return _FakeClient()


class TestDownloadToTemp:
    """验证 _download_to_temp 临时文件位置和清理。"""

    def test_temp_file_in_system_tmp(self) -> None:
        """下载的临时文件应存放在系统临时目录，而非目标目录。"""
        settings = Settings(user_agent="test-agent", http_proxy=None, javdb_cookie=None)
        _fake_content = b"fake image data"

        with patch(
            "app.services.image_utils.httpx.Client",
            return_value=_make_fake_client(_fake_content),
        ):
            result = _download_to_temp("https://example.com/img.jpg", settings)

        assert result is not None
        assert result.name.startswith(_TEMP_PREFIX)
        assert result.suffix == ".tmp"
        # 文件应在系统临时目录
        system_tmp = Path(tempfile.gettempdir())
        assert str(result).startswith(str(system_tmp))
        # 内容正确
        assert result.read_bytes() == _fake_content
        # 清理
        result.unlink()

    def test_returns_none_on_failure(self) -> None:
        """HTTP 请求失败时返回 None。"""
        settings = Settings(user_agent="test-agent", http_proxy=None, javdb_cookie=None)

        with patch(
            "app.services.image_utils.httpx.Client",
            side_effect=httpx.RequestError("fail"),
        ):
            result = _download_to_temp("https://example.com/img.jpg", settings)

        assert result is None


class TestDownloadImage:
    """验证 _download_image 原子写入路径。"""

    def test_goes_through_temp_then_moves(self, tmp_path: Path) -> None:
        """文件应先写入 /tmp，再移动到目标路径。"""
        settings = Settings(user_agent="test-agent", http_proxy=None, javdb_cookie=None)
        _fake_content = b"fake image data"
        dest = tmp_path / "poster.jpg"

        with patch(
            "app.services.image_utils.httpx.Client",
            return_value=_make_fake_client(_fake_content),
        ):
            ok = _download_image(
                "https://example.com/img.jpg", dest, settings, http_timeout=5
            )

        assert ok is True
        assert dest.exists()
        assert dest.read_bytes() == _fake_content

    def test_returns_false_on_failure(self, tmp_path: Path) -> None:
        """下载失败时返回 False，不写目标文件。"""
        settings = Settings(user_agent="test-agent", http_proxy=None, javdb_cookie=None)
        dest = tmp_path / "poster.jpg"

        with patch(
            "app.services.image_utils.httpx.Client",
            side_effect=httpx.RequestError("fail"),
        ):
            ok = _download_image(
                "https://example.com/img.jpg", dest, settings, http_timeout=5
            )

        assert ok is False
        assert not dest.exists()


class TestDownloadImageWithCrop:
    """验证 _download_image_with_crop 的 /tmp 裁切路径。"""

    def test_crop_in_temp_then_move(self, tmp_path: Path) -> None:
        """需要裁切时，应在 /tmp 裁切后再移动到目标路径。"""
        settings = Settings(user_agent="test-agent", http_proxy=None, javdb_cookie=None)

        # 创建一张宽图用作裁切素材
        img = Image.new("RGB", (1200, 800), (255, 0, 0))
        buf = io.BytesIO()
        img.save(buf, format="JPEG")
        _fake_content = buf.getvalue()

        dest = tmp_path / "poster.jpg"

        with patch(
            "app.services.image_utils.httpx.Client",
            return_value=_make_fake_client(_fake_content),
        ):
            ok = _download_image_with_crop(
                "https://example.com/img.jpg",
                dest,
                settings,
                crop_direction="center",
                http_timeout=5,
            )

        assert ok is True
        assert dest.exists()
        # 裁切后的图片应有不同于原图的尺寸
        cropped = Image.open(dest)
        assert cropped.width < 1200
        assert cropped.height == 800

    def test_no_crop_uses_download_image(self, tmp_path: Path) -> None:
        """crop_direction='none' 时降级到 _download_image。"""
        settings = Settings(user_agent="test-agent", http_proxy=None, javdb_cookie=None)
        dest = tmp_path / "poster.jpg"

        with patch(
            "app.services.image_utils._download_image", return_value=True
        ) as mock_dl:
            ok = _download_image_with_crop(
                "https://example.com/img.jpg",
                dest,
                settings,
                crop_direction="none",
                http_timeout=5,
            )

        assert ok is True
        mock_dl.assert_called_once_with(
            "https://example.com/img.jpg", dest, settings, http_timeout=5
        )
