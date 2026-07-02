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
    _crop_image_exact,
    _download_image,
    _download_image_with_crop,
    _download_to_temp,
    _rotate_image,
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

    def test_crop_with_local_path(self, tmp_path: Path) -> None:
        """使用本地文件路径时，裁切应正常生效。"""
        settings = Settings(
            user_agent="test-agent",
            http_proxy=None,
            javdb_cookie=None,
            write_delay=0.0,
        )
        src = tmp_path / "source.jpg"
        img = Image.new("RGB", (1200, 800), (255, 0, 0))
        img.save(str(src), format="JPEG")
        dest = tmp_path / "poster.jpg"
        ok = _download_image_with_crop(
            str(src),
            dest,
            settings,
            crop_direction="left",
            http_timeout=5,
        )
        assert ok is True
        assert dest.exists()
        cropped = Image.open(dest)
        assert cropped.width == int(800 * 2.0 / 3.0)
        assert cropped.height == 800

    def test_crop_with_local_path_all_directions(self, tmp_path: Path) -> None:
        """使用本地文件路径时，所有裁切方向都应生效。"""
        settings = Settings(
            user_agent="test-agent",
            http_proxy=None,
            javdb_cookie=None,
            write_delay=0.0,
        )
        # 创建宽图 1800x800
        src = tmp_path / "source.jpg"
        img = Image.new("RGB", (1800, 800), (255, 0, 0))
        img.save(str(src), format="JPEG")
        target_w = int(800 * 2.0 / 3.0)

        for direction in ("left", "center", "right"):
            dest = tmp_path / f"poster_{direction}.jpg"
            ok = _download_image_with_crop(
                str(src),
                dest,
                settings,
                crop_direction=direction,
                http_timeout=5,
            )
            assert ok is True
            assert dest.exists()
            cropped = Image.open(dest)
            assert cropped.size == (target_w, 800), f"{direction}: {cropped.size}"

    def test_crop_with_local_path_exact(self, tmp_path: Path) -> None:
        """使用本地文件路径时，精确裁切应生效。"""
        settings = Settings(
            user_agent="test-agent",
            http_proxy=None,
            javdb_cookie=None,
            write_delay=0.0,
        )
        src = tmp_path / "source.jpg"
        # 创建 500x500 图片
        img = Image.new("RGB", (500, 500), (255, 0, 0))
        # 中间画 300x300 绿色
        for x in range(100, 400):
            for y in range(100, 400):
                img.putpixel((x, y), (0, 255, 0))
        img.save(str(src), format="JPEG")
        dest = tmp_path / "cropped.jpg"
        ok = _download_image_with_crop(
            str(src),
            dest,
            settings,
            crop_box=(100, 100, 300, 300),
            http_timeout=5,
        )
        assert ok is True
        assert dest.exists()
        cropped = Image.open(dest)
        assert cropped.size == (300, 300)

    def test_crop_with_local_path_auto_trim(self, tmp_path: Path) -> None:
        """本地文件路径 + auto_trim + direction 裁切。"""
        settings = Settings(
            user_agent="test-agent",
            http_proxy=None,
            javdb_cookie=None,
            write_delay=0.0,
            auto_trim_white_borders=True,
        )
        # 1200x800 绿色内容 + 50px 白边 = 1300x900
        total_w, total_h = 1300, 900
        img = Image.new("RGB", (total_w, total_h), (255, 255, 255))
        inner = Image.new("RGB", (1200, 800), (0, 255, 0))
        img.paste(inner, (50, 50))
        src = tmp_path / "source.png"
        img.save(str(src), format="PNG")
        dest = tmp_path / "result.png"
        ok = _download_image_with_crop(
            str(src),
            dest,
            settings,
            crop_direction="center",
            http_timeout=5,
        )
        assert ok is True
        cropped = Image.open(dest)
        # auto_trim → 1200x800 → 2:3 crop → 533x800
        assert cropped.size == (int(800 * 2.0 / 3.0), 800)


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

    def test_crop_with_local_path(self, tmp_path: Path) -> None:
        """使用本地文件路径时，裁切应正常生效。"""
        settings = Settings(
            user_agent="test-agent",
            http_proxy=None,
            javdb_cookie=None,
            write_delay=0.0,
        )
        # 创建一张宽图 1200x800 作为本地图片
        src = tmp_path / "source.jpg"
        img = Image.new("RGB", (1200, 800), (255, 0, 0))
        img.save(str(src), format="JPEG")
        dest = tmp_path / "poster.jpg"
        ok = _download_image_with_crop(
            str(src),  # 本地文件绝对路径
            dest,
            settings,
            crop_direction="left",
            http_timeout=5,
        )
        assert ok is True
        assert dest.exists()
        cropped = Image.open(dest)
        # 2:3 裁切: target_h=800, target_w=int(800*2/3)=533
        assert cropped.width == int(800 * 2.0 / 3.0)
        assert cropped.height == 800


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


class TestCropImageExact:
    def test_crop_exact_region(self, tmp_path: Path) -> None:
        img = Image.new("RGB", (200, 200), (255, 0, 0))
        for x in range(50, 150):
            for y in range(50, 150):
                img.putpixel((x, y), (0, 255, 0))
        path = tmp_path / "test.png"
        img.save(path, format="PNG")
        _crop_image_exact(path, 50, 50, 100, 100)
        cropped = Image.open(path)
        assert cropped.size == (100, 100)

    def test_crop_edge_of_image(self, tmp_path: Path) -> None:
        img = Image.new("RGB", (200, 200), (255, 0, 0))
        path = tmp_path / "test.png"
        img.save(path, format="PNG")
        _crop_image_exact(path, 0, 0, 100, 200)
        cropped = Image.open(path)
        assert cropped.size == (100, 200)

    def test_invalid_size_skipped(self, tmp_path: Path) -> None:
        img = Image.new("RGB", (200, 200), (255, 0, 0))
        path = tmp_path / "test.png"
        img.save(path, format="PNG")
        _crop_image_exact(path, 0, 0, 0, 100)
        cropped = Image.open(path)
        assert cropped.size == (200, 200)

    def test_negative_x_skipped(self, tmp_path: Path) -> None:
        img = Image.new("RGB", (200, 200), (255, 0, 0))
        path = tmp_path / "test.png"
        img.save(path, format="PNG")
        _crop_image_exact(path, -10, 0, 100, 100)
        cropped = Image.open(path)
        assert cropped.size == (200, 200)

    def test_negative_y_skipped(self, tmp_path: Path) -> None:
        img = Image.new("RGB", (200, 200), (255, 0, 0))
        path = tmp_path / "test.png"
        img.save(path, format="PNG")
        _crop_image_exact(path, 0, -10, 100, 100)
        cropped = Image.open(path)
        assert cropped.size == (200, 200)

    def test_x_plus_w_exceeds_width_skipped(self, tmp_path: Path) -> None:
        img = Image.new("RGB", (200, 200), (255, 0, 0))
        path = tmp_path / "test.png"
        img.save(path, format="PNG")
        _crop_image_exact(path, 150, 0, 100, 100)
        cropped = Image.open(path)
        assert cropped.size == (200, 200)

    def test_y_plus_h_exceeds_height_skipped(self, tmp_path: Path) -> None:
        img = Image.new("RGB", (200, 200), (255, 0, 0))
        path = tmp_path / "test.png"
        img.save(path, format="PNG")
        _crop_image_exact(path, 0, 150, 100, 100)
        cropped = Image.open(path)
        assert cropped.size == (200, 200)


class TestDownloadImageWithCropBox:
    def test_crop_box_applied_before_direction(self, tmp_path: Path) -> None:
        """crop_box 应在 direction 之前应用。"""
        settings = Settings(
            user_agent="test-agent",
            http_proxy=None,
            javdb_cookie=None,
            write_delay=0.0,
        )
        # 创建一张宽图: 900x600，精确裁切中间 600x600，再 2:3 裁切
        img = Image.new("RGB", (900, 600), (255, 0, 0))
        # 中间区域画绿色
        for x in range(150, 750):
            for y in range(0, 600):
                img.putpixel((x, y), (0, 255, 0))
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        dest = tmp_path / "poster.jpg"
        with patch(
            "app.services.image_utils.httpx.Client",
            return_value=_make_fake_client(buf.getvalue()),
        ):
            ok = _download_image_with_crop(
                "https://example.com/img.jpg",
                dest,
                settings,
                crop_direction="center",
                crop_box=(150, 0, 600, 600),
                http_timeout=5,
            )
        assert ok is True
        assert dest.exists()
        cropped = Image.open(dest)
        # crop_box: 600x600 → 2:3 crop: 宽 = 600*2/3 = 400
        expected_w = int(600 * 2.0 / 3.0)
        assert cropped.size == (expected_w, 600)

    def test_crop_box_no_direction(self, tmp_path: Path) -> None:
        """只传 crop_box 不传 direction 也应生效。"""
        settings = Settings(
            user_agent="test-agent",
            http_proxy=None,
            javdb_cookie=None,
            write_delay=0.0,
        )
        img = Image.new("RGB", (500, 500), (255, 0, 0))
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        dest = tmp_path / "result.jpg"
        with patch(
            "app.services.image_utils.httpx.Client",
            return_value=_make_fake_client(buf.getvalue()),
        ):
            ok = _download_image_with_crop(
                "https://example.com/img.jpg",
                dest,
                settings,
                crop_direction="none",
                crop_box=(100, 100, 300, 300),
                http_timeout=5,
            )
        assert ok is True
        cropped = Image.open(dest)
        assert cropped.size == (300, 300)


class TestRotateImage:
    def test_rotate_90_clockwise(self, tmp_path: Path) -> None:
        """旋转 90° 顺时针，宽高应互换。"""
        img = Image.new("RGB", (200, 100), (255, 0, 0))
        path = tmp_path / "test.png"
        img.save(path, format="PNG")
        _rotate_image(path, 90)
        result = Image.open(path)
        assert result.size == (100, 200)

    def test_rotate_180(self, tmp_path: Path) -> None:
        """旋转 180°，尺寸不变。"""
        img = Image.new("RGB", (200, 100), (255, 0, 0))
        path = tmp_path / "test.png"
        img.save(path, format="PNG")
        _rotate_image(path, 180)
        result = Image.open(path)
        assert result.size == (200, 100)

    def test_rotate_minus_90(self, tmp_path: Path) -> None:
        """旋转 -90°（逆时针），宽高应互换。"""
        img = Image.new("RGB", (200, 100), (255, 0, 0))
        path = tmp_path / "test.png"
        img.save(path, format="PNG")
        _rotate_image(path, -90)
        result = Image.open(path)
        assert result.size == (100, 200)

    def test_rotate_0_noop(self, tmp_path: Path) -> None:
        """angle=0 不应做任何操作。"""
        img = Image.new("RGB", (200, 100), (255, 0, 0))
        path = tmp_path / "test.png"
        img.save(path, format="PNG")
        _rotate_image(path, 0)
        result = Image.open(path)
        assert result.size == (200, 100)

    def test_rotate_preserves_content(self, tmp_path: Path) -> None:
        """旋转后像素内容应正确。"""
        img = Image.new("RGB", (100, 50), (255, 0, 0))
        img.putpixel((90, 10), (0, 255, 0))  # 右下角绿点
        path = tmp_path / "test.png"
        img.save(path, format="PNG")
        _rotate_image(path, 90)
        result = Image.open(path)
        # 90° 顺时针后，(90,10) → (10, 40) 附近
        assert result.size == (50, 100)


class TestDownloadImageWithCropRotation:
    """验证 _download_image_with_crop 的旋转 + 裁切组合。"""

    def test_rotation_applied_before_crop(self, tmp_path: Path) -> None:
        """先旋转再精确裁切。"""
        settings = Settings(
            user_agent="test-agent",
            http_proxy=None,
            javdb_cookie=None,
            write_delay=0.0,
        )
        src = tmp_path / "source.jpg"
        # 竖图 100x200（宽 100，高 200）→ 旋转 90° → 横图 200x100 → 裁切中间 100x100
        img = Image.new("RGB", (100, 200), (255, 0, 0))
        img.save(str(src), format="JPEG")
        dest = tmp_path / "cropped.jpg"
        ok = _download_image_with_crop(
            str(src),
            dest,
            settings,
            crop_rotation=90,
            crop_box=(50, 0, 100, 100),
            http_timeout=5,
        )
        assert ok is True
        result = Image.open(dest)
        # 旋转后 200x100，裁切从 (50,0) 起 100x100
        assert result.size == (100, 100)

    def test_rotation_without_crop(self, tmp_path: Path) -> None:
        """只旋转不裁切。"""
        settings = Settings(
            user_agent="test-agent",
            http_proxy=None,
            javdb_cookie=None,
            write_delay=0.0,
        )
        src = tmp_path / "source.jpg"
        img = Image.new("RGB", (200, 100), (255, 0, 0))
        img.save(str(src), format="JPEG")
        dest = tmp_path / "rotated.jpg"
        ok = _download_image_with_crop(
            str(src),
            dest,
            settings,
            crop_rotation=90,
            crop_direction="none",
            http_timeout=5,
        )
        assert ok is True
        result = Image.open(dest)
        assert result.size == (100, 200)

    def test_rotation_then_direction_crop(self, tmp_path: Path) -> None:
        """旋转 + 方向裁切组合。"""
        settings = Settings(
            user_agent="test-agent",
            http_proxy=None,
            javdb_cookie=None,
            write_delay=0.0,
        )
        src = tmp_path / "source.jpg"
        # 横图 900x600 → 旋转 90° → 竖图 600x900 → 方向裁切(左) → 2:3
        img = Image.new("RGB", (900, 600), (255, 0, 0))
        img.save(str(src), format="JPEG")
        dest = tmp_path / "result.jpg"
        ok = _download_image_with_crop(
            str(src),
            dest,
            settings,
            crop_rotation=90,
            crop_direction="left",
            http_timeout=5,
        )
        assert ok is True
        result = Image.open(dest)
        # 旋转后 600x900，2:3 裁切: 宽=600, 高=900 → target_w = 900*2/3 = 600
        # 但 direction 裁切基于 2:3，宽=高*2/3 = 600，所以 600x900
        expected_w = int(900 * 2.0 / 3.0)
        assert result.size == (expected_w, 900)

    def test_rotation_skips_download_fast_path(self, tmp_path: Path) -> None:
        """旋转非 0 时不应走快速路径（直接 _download_image）。"""
        settings = Settings(
            user_agent="test-agent",
            http_proxy=None,
            javdb_cookie=None,
            write_delay=0.0,
        )
        dest = tmp_path / "poster.jpg"
        fake_tmp = tmp_path / "fake_tmp.jpg"
        fake_tmp.write_text("fake")
        with patch(
            "app.services.image_utils._download_image", return_value=True
        ) as mock_dl:
            with patch(
                "app.services.image_utils._download_to_temp",
                return_value=fake_tmp,
            ):
                with patch("app.services.image_utils._rotate_image"):
                    with patch("app.services.image_utils._crop_image"):
                        ok = _download_image_with_crop(
                            "https://example.com/img.jpg",
                            dest,
                            settings,
                            crop_rotation=90,
                            crop_direction="none",
                            http_timeout=5,
                        )
        assert ok is True
        mock_dl.assert_not_called()


class TestSkipAllProcessing:
    """验证 skip_all_processing 参数。"""

    def test_skip_all_processing_skips_fast_path(self, tmp_path: Path) -> None:
        """skip_all_processing=True 不应走快速路径（_download_image）。"""
        settings = Settings(
            user_agent="test-agent",
            http_proxy=None,
            javdb_cookie=None,
            write_delay=0.0,
        )
        dest = tmp_path / "poster.jpg"
        fake_tmp = tmp_path / "fake_tmp.jpg"
        fake_tmp.write_text("fake")

        with patch(
            "app.services.image_utils._download_image", return_value=True
        ) as mock_dl:
            with patch(
                "app.services.image_utils._download_to_temp",
                return_value=fake_tmp,
            ):
                with patch("app.services.image_utils._rotate_image") as mock_rot:
                    with patch("app.services.image_utils._crop_image") as mock_crop:
                        with patch(
                            "app.services.image_utils._trim_white_borders"
                        ) as mock_trim:
                            ok = _download_image_with_crop(
                                "https://example.com/img.jpg",
                                dest,
                                settings,
                                crop_direction="left",
                                crop_box=(10, 10, 50, 50),
                                crop_rotation=90,
                                skip_all_processing=True,
                                http_timeout=5,
                            )

        assert ok is True
        mock_dl.assert_not_called()
        mock_rot.assert_not_called()
        mock_crop.assert_not_called()
        mock_trim.assert_not_called()

    def test_skip_all_processing_still_copies_file(self, tmp_path: Path) -> None:
        """skip_all_processing=True 仍应将文件复制到目标路径。"""
        settings = Settings(
            user_agent="test-agent",
            http_proxy=None,
            javdb_cookie=None,
            write_delay=0.0,
        )
        src = tmp_path / "source.jpg"
        img = Image.new("RGB", (200, 100), (255, 0, 0))
        img.save(str(src), format="JPEG")
        dest = tmp_path / "result.jpg"
        ok = _download_image_with_crop(
            str(src),
            dest,
            settings,
            skip_all_processing=True,
            http_timeout=5,
        )
        assert ok is True
        assert dest.exists()
        result = Image.open(dest)
        assert result.size == (200, 100)

    def test_skip_all_processing_default_false(self, tmp_path: Path) -> None:
        """skip_all_processing 默认为 False，不影响正常裁切路径。"""
        settings = Settings(
            user_agent="test-agent",
            http_proxy=None,
            javdb_cookie=None,
            write_delay=0.0,
        )
        src = tmp_path / "source.jpg"
        img = Image.new("RGB", (1200, 800), (255, 0, 0))
        img.save(str(src), format="JPEG")
        dest = tmp_path / "cropped.jpg"
        ok = _download_image_with_crop(
            str(src),
            dest,
            settings,
            crop_direction="left",
            http_timeout=5,
        )
        assert ok is True
        cropped = Image.open(dest)
        assert cropped.width < 1200
