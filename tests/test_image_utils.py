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
    _trim_white_borders,
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
        settings = Settings(
            user_agent="test-agent", http_proxy=None, javdb_cookie=None, write_delay=0.0
        )
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
        settings = Settings(
            user_agent="test-agent", http_proxy=None, javdb_cookie=None, write_delay=0.0
        )

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
        settings = Settings(
            user_agent="test-agent", http_proxy=None, javdb_cookie=None, write_delay=0.0
        )
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
        settings = Settings(
            user_agent="test-agent", http_proxy=None, javdb_cookie=None, write_delay=0.0
        )
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

    def test_respects_write_delay(self, tmp_path: Path) -> None:
        """应调用 _write_delay 并传入 settings.write_delay。"""
        settings = Settings(
            user_agent="test-agent", http_proxy=None, javdb_cookie=None, write_delay=0.0
        )
        dest = tmp_path / "poster.jpg"
        dest.write_text("placeholder")

        with patch("app.services.image_utils._write_delay") as mock_delay:
            with patch(
                "app.services.image_utils._download_to_temp",
                return_value=dest,
            ):
                ok = _download_image(
                    "https://example.com/img.jpg", dest, settings, http_timeout=5
                )

        assert ok is True
        mock_delay.assert_called_once_with(0.0)


class TestDownloadImageWithCrop:
    """验证 _download_image_with_crop 的 /tmp 裁切路径。"""

    def test_crop_in_temp_then_move(self, tmp_path: Path) -> None:
        """需要裁切时，应在 /tmp 裁切后再移动到目标路径。"""
        settings = Settings(
            user_agent="test-agent", http_proxy=None, javdb_cookie=None, write_delay=0.0
        )

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
        settings = Settings(
            user_agent="test-agent", http_proxy=None, javdb_cookie=None, write_delay=0.0
        )
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

    def test_crop_respects_write_delay(self, tmp_path: Path) -> None:
        """crop 模式也应调用 _write_delay 并传入 settings.write_delay。"""
        settings = Settings(
            user_agent="test-agent",
            http_proxy=None,
            javdb_cookie=None,
            write_delay=0.15,
        )
        dest = tmp_path / "poster.jpg"
        fake_tmp = tmp_path / "fake_tmp.jpg"
        fake_tmp.write_text("fake")

        with patch("app.services.image_utils._write_delay") as mock_delay2:
            with patch(
                "app.services.image_utils._download_to_temp",
                return_value=fake_tmp,
            ):
                with patch("app.services.image_utils._crop_image"):
                    ok = _download_image_with_crop(
                        "https://example.com/img.jpg",
                        dest,
                        settings,
                        crop_direction="center",
                        http_timeout=5,
                    )

        assert ok is True
        mock_delay2.assert_called_once_with(0.15)


class TestTrimWhiteBorders:
    def _make_png(self, width: int, height: int, color: tuple[int, int, int]) -> bytes:
        buf = io.BytesIO()
        Image.new("RGB", (width, height), color).save(buf, format="PNG")
        return buf.getvalue()

    def test_trim_removes_white_borders(self, tmp_path: Path) -> None:
        """创建一张图：中间 100x100 红块，周围 50px 白边 → 应裁为 100x100。"""
        total = 200
        img = Image.new("RGB", (total, total), (255, 255, 255))
        for x in range(50, 150):
            for y in range(50, 150):
                img.putpixel((x, y), (255, 0, 0))
        path = tmp_path / "test.png"
        img.save(path, format="PNG")
        _trim_white_borders(path)
        trimmed = Image.open(path)
        assert trimmed.size == (100, 100)

    def test_no_white_borders_unchanged(self, tmp_path: Path) -> None:
        """全红图（无白边）→ 不应裁切。"""
        path = tmp_path / "test.png"
        path.write_bytes(self._make_png(200, 200, (255, 0, 0)))
        _trim_white_borders(path)
        trimmed = Image.open(path)
        assert trimmed.size == (200, 200)

    def test_all_white_unchanged(self, tmp_path: Path) -> None:
        """全白图 → getbbox 返回 None → 不应裁切。"""
        path = tmp_path / "test.png"
        path.write_bytes(self._make_png(200, 200, (255, 255, 255)))
        _trim_white_borders(path)
        trimmed = Image.open(path)
        assert trimmed.size == (200, 200)

    def test_trim_white_borders_then_crop(self, tmp_path: Path) -> None:
        """启用 auto_trim_white_borders 时，应先裁白边再 2:3 裁切。"""
        settings = Settings(
            user_agent="test-agent",
            http_proxy=None,
            javdb_cookie=None,
            write_delay=0.0,
            auto_trim_white_borders=True,
        )
        # 创建一张图：实际内容 1200x800，周围 50px 白边
        total = 1300
        img = Image.new("RGB", (total, 900), (255, 255, 255))
        inner = Image.new("RGB", (1200, 800), (100, 200, 100))
        img.paste(inner, (50, 50))
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        dest = tmp_path / "poster.png"
        with patch(
            "app.services.image_utils.httpx.Client",
            return_value=_make_fake_client(buf.getvalue()),
        ):
            ok = _download_image_with_crop(
                "https://example.com/img.png",
                dest,
                settings,
                crop_direction="center",
                http_timeout=5,
            )
        assert ok is True
        assert dest.exists()
        trimmed = Image.open(dest)
        # 先裁掉 50px 白边 → 1200x800 → 再按 2:3 裁切 → 目标宽 533
        expected_h = 800
        expected_w = int(expected_h * 2.0 / 3.0)
        assert trimmed.width == expected_w
        assert trimmed.height == expected_h

    def test_auto_trim_no_crop_still_downloads(self, tmp_path: Path) -> None:
        """auto_trim_white_borders=True + crop_direction=none 也应下载并去白边。"""
        settings = Settings(
            user_agent="test-agent",
            http_proxy=None,
            javdb_cookie=None,
            write_delay=0.0,
            auto_trim_white_borders=True,
        )
        # 中间 100x100 红块 + 白边
        total = 200
        img = Image.new("RGB", (total, total), (255, 255, 255))
        for x in range(50, 150):
            for y in range(50, 150):
                img.putpixel((x, y), (255, 0, 0))
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        dest = tmp_path / "result.png"
        with patch(
            "app.services.image_utils.httpx.Client",
            return_value=_make_fake_client(buf.getvalue()),
        ):
            ok = _download_image_with_crop(
                "https://example.com/img.png",
                dest,
                settings,
                crop_direction="none",
                http_timeout=5,
            )
        assert ok is True
        assert dest.exists()
        trimmed = Image.open(dest)
        assert trimmed.size == (100, 100)


class TestDownloadImageWithCropAutoTrim:
    """验证 _download_image_with_crop 在 auto_trim_white_borders 开启时的行为。"""

    def test_auto_trim_invokes_trim_white_borders(self, tmp_path: Path) -> None:
        """auto_trim=True 时应调用 _trim_white_borders。"""
        settings = Settings(
            user_agent="test-agent",
            http_proxy=None,
            javdb_cookie=None,
            write_delay=0.0,
            auto_trim_white_borders=True,
        )
        fake_tmp = tmp_path / "fake_tmp.jpg"
        fake_tmp.write_text("fake")
        dest = tmp_path / "poster.jpg"
        with patch("app.services.image_utils._download_to_temp", return_value=fake_tmp):
            with patch("app.services.image_utils._trim_white_borders") as mock_trim:
                with patch("app.services.image_utils._crop_image"):
                    ok = _download_image_with_crop(
                        "https://example.com/img.jpg",
                        dest,
                        settings,
                        crop_direction="center",
                        http_timeout=5,
                    )
        assert ok is True
        mock_trim.assert_called_once_with(fake_tmp)
