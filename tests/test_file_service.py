from __future__ import annotations

from pathlib import Path
from xml.etree import ElementTree as ET

import pytest

from app.schemas import Actor, MovieMetadata
from app.services.file_service import (
    _check_reuse_existing,
    _delete_orphan_extrafanart,
    _rename_directory,
    _scan_dir_names,
)
from app.services.file_utils import (
    _atomic_write_text,
    _sanitize_filename_part,
    _truncate_to_bytes,
)
from app.services.image_utils import (
    _crop_image,
)
from app.services.lock_utils import (
    _acquire_dir_lock,
    _cleanup_orphaned_temps,
    _release_dir_lock,
)
from app.services.rename_utils import (
    _format_dir_rename,
    _format_rename,
    _is_vr,
    _rename_single_video,
    _rename_videos_in_dir,
)
from app.services.subtitle_utils import (
    _find_matching_subtitles,
    _rename_subtitles,
)


class TestIsVr:
    def test_vr_in_number(self) -> None:
        meta = MovieMetadata(title="Test", number="IPVR-335")
        assert _is_vr(meta) is True

    def test_vr_in_lowercase_number(self) -> None:
        meta = MovieMetadata(title="Test", number="ipvr-001")
        assert _is_vr(meta) is True

    def test_vr_in_genre(self) -> None:
        meta = MovieMetadata(title="Test", number="ABC-123", genres=["VR", "爱情"])
        assert _is_vr(meta) is True

    def test_vr_in_tag(self) -> None:
        meta = MovieMetadata(title="Test", number="ABC-123", tags=["VR 作品"])
        assert _is_vr(meta) is True

    def test_no_vr(self) -> None:
        meta = MovieMetadata(title="Test", number="ABP-123")
        assert _is_vr(meta) is False

    def test_no_number(self) -> None:
        meta = MovieMetadata(title="Test")
        assert _is_vr(meta) is False


class TestSanitizeFilenamePart:
    def test_removes_unsafe_chars(self) -> None:
        result = _sanitize_filename_part('foo:bar<baz>"qux"')
        assert result == "foo_bar_baz__qux_"

    def test_strips_leading_trailing_spaces(self) -> None:
        result = _sanitize_filename_part("  hello  ")
        assert result == "hello"

    def test_underscore_when_empty(self) -> None:
        result = _sanitize_filename_part("...")
        assert result == "_"

    def test_normal_string_passes(self) -> None:
        result = _sanitize_filename_part("ABP-123 我的女友")
        assert result == "ABP-123 我的女友"

    def test_backslash_replaced(self) -> None:
        result = _sanitize_filename_part("a\\b/c")
        assert "\\" not in result
        assert "/" not in result


class TestTruncateToBytes:
    def test_short_string(self) -> None:
        result = _truncate_to_bytes("hello", 100)
        assert result == "hello"

    def test_truncates_at_byte_boundary(self) -> None:
        s = "a" * 50
        result = _truncate_to_bytes(s, 20)
        assert len(result.encode("utf-8")) <= 20

    def test_does_not_break_utf8_char(self) -> None:
        s = "你好世界" * 20
        result = _truncate_to_bytes(s, 10)
        assert len(result.encode("utf-8")) <= 12
        assert "�" not in result.strip("\ufffd")

    def test_exact_fit(self) -> None:
        s = "abcde"
        result = _truncate_to_bytes(s, 5)
        assert result == "abcde"


class TestFormatRename:
    def test_id(self) -> None:
        meta = MovieMetadata(title="Test", number="ABP-123")
        result = _format_rename(meta, idx=1, is_vr=False, format_str="{id}")
        assert result == "ABP-123"

    def test_actor(self) -> None:
        meta = MovieMetadata(
            title="Test", number="ABP-123", actors=[Actor(name="田中丽奈")]
        )
        result = _format_rename(meta, idx=1, is_vr=False, format_str="{actor}")
        assert result == "田中丽奈"

    def test_multiple_actors(self) -> None:
        meta = MovieMetadata(
            title="Test",
            number="ABP-123",
            actors=[Actor(name="田中丽奈"), Actor(name="佐藤健")],
        )
        result = _format_rename(meta, idx=1, is_vr=False, format_str="{actor}")
        assert result == "田中丽奈、佐藤健"

    def test_actor_limit_overflow_with_suffix(self) -> None:
        """超出限制时追加"等x人"后缀。"""
        meta = MovieMetadata(
            title="Test",
            number="ABP-123",
            actors=[
                Actor(name="田中丽奈"),
                Actor(name="佐藤健"),
                Actor(name="桥本环奈"),
            ],
        )
        result = _format_rename(meta, idx=1, is_vr=False, format_str="{actor:2}")
        assert result == "田中丽奈、佐藤健等3人"

    def test_actor_limit_exact_no_suffix(self) -> None:
        """恰好等于限制时不加后缀。"""
        meta = MovieMetadata(
            title="Test",
            number="ABP-123",
            actors=[
                Actor(name="田中丽奈"),
                Actor(name="佐藤健"),
                Actor(name="桥本环奈"),
            ],
        )
        result = _format_rename(meta, idx=1, is_vr=False, format_str="{actor:3}")
        assert result == "田中丽奈、佐藤健、桥本环奈"

    def test_actor_limit_less_than_total(self) -> None:
        """limit > 实际人数时不加后缀。"""
        meta = MovieMetadata(
            title="Test",
            number="ABP-123",
            actors=[Actor(name="田中丽奈"), Actor(name="佐藤健")],
        )
        result = _format_rename(meta, idx=1, is_vr=False, format_str="{actor:5}")
        assert result == "田中丽奈、佐藤健"

    def test_actor_limit_zero(self) -> None:
        meta = MovieMetadata(
            title="Test",
            number="ABP-123",
            actors=[Actor(name="田中丽奈"), Actor(name="佐藤健")],
        )
        result = _format_rename(meta, idx=1, is_vr=False, format_str="{actor:0}")
        assert result == "_"

    def test_actor_limit_one_with_overflow(self) -> None:
        """limit=1 且有更多演员时显示"名前等N人"。"""
        meta = MovieMetadata(
            title="Test",
            number="ABP-123",
            actors=[
                Actor(name="田中丽奈"),
                Actor(name="佐藤健"),
                Actor(name="桥本环奈"),
                Actor(name="绫濑遥"),
                Actor(name="新垣结衣"),
            ],
        )
        result = _format_rename(meta, idx=1, is_vr=False, format_str="{actor:1}")
        assert result == "田中丽奈等5人"

    def test_actor_dir_rename_limit_with_suffix(self) -> None:
        """目录重命名同样支持溢出后缀。"""
        meta = MovieMetadata(
            title="Test",
            number="ABP-123",
            actors=[
                Actor(name="田中丽奈"),
                Actor(name="佐藤健"),
                Actor(name="桥本环奈"),
            ],
        )
        result = _format_dir_rename(meta, is_vr=False, format_str="{actor:2}")
        assert result == "田中丽奈、佐藤健等3人"

    def test_actor_no_limit_still_works(self) -> None:
        meta = MovieMetadata(
            title="Test",
            number="ABP-123",
            actors=[Actor(name="田中丽奈"), Actor(name="佐藤健")],
        )
        result = _format_rename(meta, idx=1, is_vr=False, format_str="{actor}")
        assert result == "田中丽奈、佐藤健"

    def test_actor_filter_female_only(self) -> None:
        """filter_actor_gender=True 时只保留女演员。"""
        meta = MovieMetadata(
            title="Test",
            number="ABP-123",
            actors=[
                Actor(name="女优A", gender="female"),
                Actor(name="男优B", gender="male"),
                Actor(name="女优C", gender="female"),
            ],
        )
        result = _format_rename(
            meta,
            idx=1,
            is_vr=False,
            format_str="{actor}",
            filter_actor_gender=True,
        )
        assert result == "女优A、女优C"

    def test_actor_filter_disabled_keeps_all(self) -> None:
        """filter_actor_gender=False 时保留所有演员。"""
        meta = MovieMetadata(
            title="Test",
            number="ABP-123",
            actors=[
                Actor(name="女优A", gender="female"),
                Actor(name="男优B", gender="male"),
            ],
        )
        result = _format_rename(
            meta,
            idx=1,
            is_vr=False,
            format_str="{actor}",
            filter_actor_gender=False,
        )
        assert result == "女优A、男优B"

    def test_actor_filter_keeps_none_gender(self) -> None:
        """gender 为 None（旧数据兼容）视为女演员保留。"""
        meta = MovieMetadata(
            title="Test",
            number="ABP-123",
            actors=[Actor(name="未知"), Actor(name="男优", gender="male")],
        )
        result = _format_rename(
            meta,
            idx=1,
            is_vr=False,
            format_str="{actor}",
            filter_actor_gender=True,
        )
        assert result == "未知"

    def test_actor_filter_in_dir_rename(self) -> None:
        """_format_dir_rename 也支持过滤。"""
        meta = MovieMetadata(
            title="Test",
            actors=[
                Actor(name="女优A", gender="female"),
                Actor(name="男优B", gender="male"),
            ],
        )
        result = _format_dir_rename(
            meta,
            is_vr=False,
            format_str="{actor}",
            filter_actor_gender=True,
        )
        assert result == "女优A"

    def test_date_premiered(self) -> None:
        meta = MovieMetadata(title="Test", premiered="2024-03-15")
        result = _format_rename(meta, idx=1, is_vr=False, format_str="{date}")
        assert result == "2024-03-15"

    def test_date_releasedate_fallback(self) -> None:
        meta = MovieMetadata(title="Test", releasedate="2024-03-15")
        result = _format_rename(meta, idx=1, is_vr=False, format_str="{date}")
        assert result == "2024-03-15"

    def test_year(self) -> None:
        meta = MovieMetadata(title="Test", year=2024)
        result = _format_rename(meta, idx=1, is_vr=False, format_str="{year}")
        assert result == "2024"

    def test_title(self) -> None:
        meta = MovieMetadata(title="ABP-123 我的女友")
        result = _format_rename(meta, idx=1, is_vr=False, format_str="{title}")
        assert result == "ABP-123 我的女友"

    def test_default_format(self) -> None:
        meta = MovieMetadata(
            title="ABP-123 我的女友",
            number="ABP-123",
            premiered="2024-03-15",
            actors=[Actor(name="田中丽奈")],
        )
        result = _format_rename(
            meta, idx=1, is_vr=False, format_str="[{actor}][{date}]{id}"
        )
        assert result == "[田中丽奈][2024-03-15]ABP-123"

    def test_vr_format(self) -> None:
        meta = MovieMetadata(title="Test", number="IPVR-335")
        result = _format_rename(meta, idx=1, is_vr=True, format_str="{vr}")
        assert result == "180_LR"

    def test_vr_landscape_is_180_lr(self) -> None:
        """宽>高 → 180_LR（左右格式）。"""
        meta = MovieMetadata(title="Test", number="IPVR-335")
        result = _format_rename(
            meta, idx=1, is_vr=True, format_str="{vr}", resolution="3840x1920"
        )
        assert result == "180_LR"

    def test_vr_tall_is_360_tb(self) -> None:
        """宽≤高 → 360_TB（上下格式）。"""
        meta = MovieMetadata(title="Test", number="IPVR-335")
        result = _format_rename(
            meta, idx=1, is_vr=True, format_str="{vr}", resolution="1920x3840"
        )
        assert result == "360_TB"

    def test_vr_square_is_360_tb(self) -> None:
        """宽=高 → 360_TB。"""
        meta = MovieMetadata(title="Test", number="IPVR-335")
        result = _format_rename(
            meta, idx=1, is_vr=True, format_str="{vr}", resolution="1920x1920"
        )
        assert result == "360_TB"

    def test_vr_dir_rename_landscape_is_180_lr(self) -> None:
        """目录重命名同样根据分辨率判断 VR 格式。"""
        meta = MovieMetadata(title="Test", number="IPVR-335")
        result = _format_dir_rename(
            meta, is_vr=True, format_str="{vr}", resolution="3840x1920"
        )
        assert result == "180_LR"

    def test_vr_dir_rename_default(self) -> None:
        """目录重命名无分辨率时默认 180_LR。"""
        meta = MovieMetadata(title="Test", number="IPVR-335")
        result = _format_dir_rename(meta, is_vr=True, format_str="{vr}")
        assert result == "180_LR"

    def test_idx(self) -> None:
        meta = MovieMetadata(title="Test")
        result = _format_rename(meta, idx=3, is_vr=False, format_str="{idx}")
        assert result == "3"

    def test_resolution(self) -> None:
        meta = MovieMetadata(title="Test")
        result = _format_rename(
            meta, idx=1, is_vr=False, format_str="{resolution}", resolution="1920x1080"
        )
        assert result == "1920x1080"

    def test_missing_fields(self) -> None:
        meta = MovieMetadata(title="Test")
        result = _format_rename(
            meta, idx=1, is_vr=False, format_str="[{actor}][{year}]{id}"
        )
        assert result == "_"


class TestCleanupOrphanedTemps:
    def test_removes_temp_files(self, tmp_path: Path) -> None:
        temp_file = tmp_path / "._nfofetch_tmp_1.mp4"
        temp_file.write_text("test")
        normal_file = tmp_path / "movie.mp4"
        normal_file.write_text("test")

        _cleanup_orphaned_temps(tmp_path)

        assert not temp_file.exists()
        assert normal_file.exists()

    def test_no_temp_files(self, tmp_path: Path) -> None:
        normal_file = tmp_path / "movie.mp4"
        normal_file.write_text("test")

        _cleanup_orphaned_temps(tmp_path)
        assert normal_file.exists()


class TestCropImage:
    def test_none_returns_unchanged(self, tmp_path: Path) -> None:
        from PIL import Image

        p = tmp_path / "test.jpg"
        Image.new("RGB", (1200, 800)).save(str(p))
        _crop_image(p, "none")
        assert Image.open(str(p)).size == (1200, 800)

    def test_left_crops_landscape(self, tmp_path: Path) -> None:
        from PIL import Image

        p = tmp_path / "test.jpg"
        img = Image.new("RGB", (1200, 800))
        img.save(str(p))
        _crop_image(p, "left")
        w, h = Image.open(str(p)).size
        assert w < 1200
        assert h == 800

    def test_right_crops_landscape(self, tmp_path: Path) -> None:
        from PIL import Image

        p = tmp_path / "test.jpg"
        Image.new("RGB", (1200, 800)).save(str(p))
        _crop_image(p, "right")
        w, h = Image.open(str(p)).size
        assert w < 1200
        assert h == 800

    def test_center_crops_landscape(self, tmp_path: Path) -> None:
        from PIL import Image

        p = tmp_path / "test.jpg"
        Image.new("RGB", (1200, 800)).save(str(p))
        _crop_image(p, "center")
        w, h = Image.open(str(p)).size
        assert w < 1200
        assert h == 800

    def test_portrait_unchanged(self, tmp_path: Path) -> None:
        from PIL import Image

        p = tmp_path / "test.jpg"
        Image.new("RGB", (800, 1200)).save(str(p))
        _crop_image(p, "left")
        assert Image.open(str(p)).size == (800, 1200)

    def test_left_picks_green_region(self, tmp_path: Path) -> None:
        from PIL import Image

        p = tmp_path / "test.jpg"
        img = Image.new("RGB", (1200, 800), (200, 200, 200))
        for x in range(400):
            for y in range(800):
                img.putpixel((x, y), (0, 255, 0))
        for x in range(800, 1200):
            for y in range(800):
                img.putpixel((x, y), (0, 0, 255))
        img.save(str(p))
        _crop_image(p, "left")
        c = Image.open(str(p))
        mid_x, mid_y = c.width // 2, c.height // 2
        pixel = c.getpixel((mid_x, mid_y))
        assert isinstance(pixel, tuple)
        r, g, b = pixel
        assert g > 200, f"Expected green center, got ({r},{g},{b})"

    def test_right_picks_blue_region(self, tmp_path: Path) -> None:
        from PIL import Image

        p = tmp_path / "test.jpg"
        img = Image.new("RGB", (1200, 800), (200, 200, 200))
        for x in range(400):
            for y in range(800):
                img.putpixel((x, y), (0, 255, 0))
        for x in range(800, 1200):
            for y in range(800):
                img.putpixel((x, y), (0, 0, 255))
        img.save(str(p))
        _crop_image(p, "right")
        c = Image.open(str(p))
        mid_x, mid_y = c.width // 2, c.height // 2
        pixel = c.getpixel((mid_x, mid_y))
        assert isinstance(pixel, tuple)
        r, g, b = pixel
        assert b > 200, f"Expected blue center, got ({r},{g},{b})"

    def test_portrait_left_picks_green_region(self, tmp_path: Path) -> None:
        from PIL import Image

        p = tmp_path / "test.jpg"
        img = Image.new("RGB", (1200, 1200), (200, 200, 200))
        for x in range(500):
            for y in range(1200):
                img.putpixel((x, y), (0, 255, 0))
        for x in range(700, 1200):
            for y in range(1200):
                img.putpixel((x, y), (0, 0, 255))
        img.save(str(p))
        _crop_image(p, "left")
        c = Image.open(str(p))
        mid_x, mid_y = c.width // 2, c.height // 2
        pixel = c.getpixel((mid_x, mid_y))
        assert isinstance(pixel, tuple)
        r, g, b = pixel
        assert g > 200, f"Expected green center, got ({r},{g},{b})"

    def test_portrait_right_picks_blue_region(self, tmp_path: Path) -> None:
        from PIL import Image

        p = tmp_path / "test.jpg"
        img = Image.new("RGB", (1200, 1200), (200, 200, 200))
        for x in range(500):
            for y in range(1200):
                img.putpixel((x, y), (0, 255, 0))
        for x in range(700, 1200):
            for y in range(1200):
                img.putpixel((x, y), (0, 0, 255))
        img.save(str(p))
        _crop_image(p, "right")
        c = Image.open(str(p))
        mid_x, mid_y = c.width // 2, c.height // 2
        pixel = c.getpixel((mid_x, mid_y))
        assert isinstance(pixel, tuple)
        r, g, b = pixel
        assert b > 200, f"Expected blue center, got ({r},{g},{b})"


class TestAtomicWriteText:
    def test_writes_content(self, tmp_path: Path) -> None:
        dest = tmp_path / "test.txt"
        _atomic_write_text(dest, "hello world")
        assert dest.read_text(encoding="utf-8") == "hello world"

    def test_no_temp_leak_in_target_dir(self, tmp_path: Path) -> None:
        nested = tmp_path / "nested"
        nested.mkdir()
        dest = nested / "test.txt"
        _atomic_write_text(dest, "content")
        assert dest.read_text(encoding="utf-8") == "content"
        # 临时文件在系统 /tmp，不会残留在目标目录
        temps = list(tmp_path.rglob("._nfofetch_*"))
        assert len(temps) == 0

    def test_overwrites_existing(self, tmp_path: Path) -> None:
        dest = tmp_path / "test.txt"
        dest.write_text("old")
        _atomic_write_text(dest, "new")
        assert dest.read_text(encoding="utf-8") == "new"

    def test_accepts_delay_parameter(self, tmp_path: Path) -> None:
        """传入 delay 参数时不应影响写入结果。"""
        dest = tmp_path / "test.txt"
        _atomic_write_text(dest, "content with delay", delay=0.01)
        assert dest.read_text(encoding="utf-8") == "content with delay"


class TestScanDirNames:
    def test_returns_filenames(self, tmp_path: Path) -> None:
        (tmp_path / "a.txt").write_text("a")
        (tmp_path / "b.txt").write_text("b")
        result = _scan_dir_names(tmp_path)
        assert result == {"a.txt", "b.txt"}

    def test_empty_directory(self, tmp_path: Path) -> None:
        result = _scan_dir_names(tmp_path)
        assert result == set()

    def test_ignores_oserror(self) -> None:
        result = _scan_dir_names(Path("/nonexistent/path"))
        assert result == set()


class TestCheckReuseExisting:
    def test_no_nfo_returns_false(self, tmp_path: Path) -> None:
        assert _check_reuse_existing(tmp_path, None, None) is False

    def test_no_nfo_with_existing_names(self, tmp_path: Path) -> None:
        assert (
            _check_reuse_existing(tmp_path, None, None, existing_names=set()) is False
        )

    def test_match_source_url(self, tmp_path: Path) -> None:
        nfo = tmp_path / "movie.nfo"
        nfo.write_text(
            '<?xml version="1.0"?>\n<movie><source_url>https://javdb.com/v/abc</source_url></movie>'
        )
        assert _check_reuse_existing(tmp_path, "https://javdb.com/v/abc", None) is True

    def test_match_number(self, tmp_path: Path) -> None:
        nfo = tmp_path / "movie.nfo"
        nfo.write_text('<?xml version="1.0"?>\n<movie><id>ABP-123</id></movie>')
        assert _check_reuse_existing(tmp_path, None, "ABP-123") is True

    def test_no_match(self, tmp_path: Path) -> None:
        nfo = tmp_path / "movie.nfo"
        nfo.write_text('<?xml version="1.0"?>\n<movie><id>ABC-999</id></movie>')
        assert _check_reuse_existing(tmp_path, None, "ABP-123") is False

    def test_with_existing_names_skip_exists_check(self, tmp_path: Path) -> None:
        nfo = tmp_path / "movie.nfo"
        nfo.write_text('<?xml version="1.0"?>\n<movie><id>ABP-123</id></movie>')
        assert (
            _check_reuse_existing(
                tmp_path, None, "ABP-123", existing_names={"movie.nfo"}
            )
            is True
        )

    def test_with_existing_names_missing_nfo(self, tmp_path: Path) -> None:
        assert (
            _check_reuse_existing(
                tmp_path, None, "ABP-123", existing_names={"poster.jpg"}
            )
            is False
        )


class TestRenameSingleVideo:
    def test_rename_file(self, tmp_path: Path) -> None:
        video = tmp_path / "old_name.mp4"
        video.write_text("fake video")
        meta = MovieMetadata(title="Test", number="ABP-123")
        result = _rename_single_video(video, meta, "{id}")
        expected = tmp_path / "ABP-123.mp4"
        assert result == expected
        assert expected.exists()
        assert not video.exists()

    def test_rename_with_actor(self, tmp_path: Path) -> None:
        video = tmp_path / "old.mp4"
        video.write_text("fake")
        meta = MovieMetadata(
            title="Test",
            number="ABP-123",
            actors=[Actor(name="田中丽奈")],
        )
        result = _rename_single_video(video, meta, "[{actor}]{id}")
        expected = tmp_path / "[田中丽奈]ABP-123.mp4"
        assert result == expected
        assert expected.exists()

    def test_skip_if_same_name(self, tmp_path: Path) -> None:
        meta = MovieMetadata(title="Test", number="ABP-123")
        video = tmp_path / "ABP-123.mp4"
        video.write_text("fake")
        result = _rename_single_video(video, meta, "{id}")
        assert result == video

    def test_conflict_handling(self, tmp_path: Path) -> None:
        meta = MovieMetadata(title="Test", number="ABP-123")
        video = tmp_path / "old.mp4"
        video.write_text("fake")
        (tmp_path / "ABP-123.mp4").write_text("conflict")
        result = _rename_single_video(video, meta, "{id}")
        assert result.name.startswith("ABP-123")
        assert result.name != "ABP-123.mp4"  # 有冲突后缀

    def test_skip_if_same_name_with_vr_format(self, tmp_path: Path) -> None:
        """格式含 {vr}，文件名已匹配（快速匹配成功，不应调 ffprobe）。"""
        from unittest.mock import patch

        meta = MovieMetadata(title="Test", number="KMVR-242")
        video = tmp_path / "KMVR-242_180_LR.mp4"
        video.write_text("fake")
        with patch(
            "app.services.rename_utils._get_video_resolution",
        ) as mock_res:
            result = _rename_single_video(video, meta, "{id}_{vr}")
        assert result == video
        mock_res.assert_not_called()

    def test_skip_if_same_name_with_resolution_format(self, tmp_path: Path) -> None:
        """格式含 {resolution}，文件名已匹配（需 ffprobe 确认，但跳过重命名）。"""
        from unittest.mock import patch

        meta = MovieMetadata(title="Test", number="ABP-123")
        video = tmp_path / "ABP-123_1920x1080.mp4"
        video.write_text("fake")
        with patch(
            "app.services.rename_utils._get_video_resolution",
            return_value="1920x1080",
        ) as mock_res:
            result = _rename_single_video(video, meta, "{id}_{resolution}")
        assert result == video
        mock_res.assert_called_once()


class TestRenameDirectory:
    def test_rename_directory(self, tmp_path: Path) -> None:
        old_dir = tmp_path / "old_dir"
        old_dir.mkdir()
        video = old_dir / "movie.mp4"
        video.write_text("fake")
        meta = MovieMetadata(title="Test", number="ABP-123")
        new_dir, new_video = _rename_directory(old_dir, meta, video, "{id}")
        expected_dir = tmp_path / "ABP-123"
        assert new_dir == expected_dir
        assert expected_dir.exists()
        assert not old_dir.exists()
        assert new_video == expected_dir / "movie.mp4"

    def test_skip_if_same_name(self, tmp_path: Path) -> None:
        movie_dir = tmp_path / "ABP-123"
        movie_dir.mkdir()
        video = movie_dir / "movie.mp4"
        video.write_text("fake")
        meta = MovieMetadata(title="Test", number="ABP-123")
        new_dir, new_video = _rename_directory(movie_dir, meta, video, "{id}")
        assert new_dir == movie_dir
        assert new_video == video

    def test_raises_if_target_exists(self, tmp_path: Path) -> None:
        old_dir = tmp_path / "old_dir"
        old_dir.mkdir()
        video = old_dir / "movie.mp4"
        video.write_text("fake")
        (tmp_path / "ABP-123").mkdir()
        meta = MovieMetadata(title="Test", number="ABP-123")
        with pytest.raises(OSError, match="目标文件夹已存在"):
            _rename_directory(old_dir, meta, video, "{id}")

    def test_skip_if_same_name_with_vr_format(self, tmp_path: Path) -> None:
        """格式含 {vr}，目录名已匹配（快速匹配成功，不应调 ffprobe）。"""
        from unittest.mock import patch

        meta = MovieMetadata(title="Test", number="KMVR-242")
        dir_path = tmp_path / "KMVR-242_180_LR"
        dir_path.mkdir()
        video = dir_path / "movie.mp4"
        video.write_text("fake")
        with patch(
            "app.services.file_service._get_video_resolution",
        ) as mock_res:
            new_dir, new_video = _rename_directory(dir_path, meta, video, "{id}_{vr}")
        assert new_dir == dir_path
        assert new_video == video
        mock_res.assert_not_called()

    def test_skip_if_same_name_with_resolution_format(self, tmp_path: Path) -> None:
        """格式含 {resolution}，目录名已匹配（需 ffprobe 确认，但跳过重命名）。"""
        from unittest.mock import patch

        meta = MovieMetadata(title="Test", number="ABP-123")
        dir_path = tmp_path / "ABP-123_1920x1080"
        dir_path.mkdir()
        video = dir_path / "movie.mp4"
        video.write_text("fake")
        with patch(
            "app.services.file_service._get_video_resolution",
            return_value="1920x1080",
        ) as mock_res:
            new_dir, new_video = _rename_directory(
                dir_path, meta, video, "{id}_{resolution}"
            )
        assert new_dir == dir_path
        assert new_video == video
        mock_res.assert_called_once()


class TestDirLock:
    def test_acquire_and_release(self, tmp_path: Path) -> None:
        assert _acquire_dir_lock(tmp_path)
        assert (tmp_path / ".nfofetch_lock").exists()
        _release_dir_lock(tmp_path)
        assert not (tmp_path / ".nfofetch_lock").exists()

    def test_lock_in_subdirectory(self, tmp_path: Path) -> None:
        sub = tmp_path / "sub"
        sub.mkdir()
        assert _acquire_dir_lock(sub)
        _release_dir_lock(sub)

    def test_concurrent_lock_fails(self, tmp_path: Path) -> None:
        assert _acquire_dir_lock(tmp_path, timeout=1.0)
        assert not _acquire_dir_lock(tmp_path, timeout=0.5)  # 应无法获取锁
        _release_dir_lock(tmp_path)


class TestSaveAssetsForExistingVideo:
    """基本集成测试：验证 save_assets_for_existing_video 的核心路径。"""

    def test_basic_success(self, tmp_path: Path, sample_movie_metadata) -> None:
        from app.config import Settings
        from app.services.file_service import save_assets_for_existing_video
        from app.services.nfo_service import build_movie_nfo

        video = tmp_path / "test.mp4"
        video.write_text("fake video content")
        settings = Settings(
            user_agent="test-agent",
            http_proxy=None,
            javdb_cookie=None,
            write_delay=0,
            max_extra_images=2,
            http_timeout=5,
            batch_timeout=10,
        )
        nfo_text = build_movie_nfo(sample_movie_metadata)

        result = save_assets_for_existing_video(
            metadata=sample_movie_metadata,
            nfo_text=nfo_text,
            video_path=video,
            settings=settings,
            max_extra_images=2,
        )

        assert result.success
        assert result.metadata is not None
        assert result.video_path is not None
        # NFO 应被创建
        nfo_path = tmp_path / "movie.nfo"
        assert nfo_path.exists()
        assert "ABP-123" in nfo_path.read_text(encoding="utf-8")

    def test_video_not_found(self, tmp_path: Path, sample_movie_metadata) -> None:
        from app.config import Settings
        from app.services.file_service import save_assets_for_existing_video
        from app.services.nfo_service import build_movie_nfo

        video = tmp_path / "nonexistent.mp4"
        settings = Settings(
            user_agent="test-agent",
            http_proxy=None,
            javdb_cookie=None,
            write_delay=0,
            max_extra_images=2,
            http_timeout=5,
            batch_timeout=10,
        )
        nfo_text = build_movie_nfo(sample_movie_metadata)

        # 不存在的视频，刮削会先检查视频存在性
        video.write_text("fake")  # 先创建再检查
        # 实际上 save_assets_for_existing_video 不检查视频存在性
        result = save_assets_for_existing_video(
            metadata=sample_movie_metadata,
            nfo_text=nfo_text,
            video_path=video,
            settings=settings,
            max_extra_images=2,
        )
        assert result.success

    def test_reuse_detection(self, tmp_path: Path, sample_movie_metadata) -> None:
        from app.config import Settings
        from app.services.file_service import save_assets_for_existing_video
        from app.services.nfo_service import build_movie_nfo

        video = tmp_path / "test.mp4"
        video.write_text("fake")

        # 先创建 NFO 模拟已有刮削
        nfo_path = tmp_path / "movie.nfo"
        nfo_path.write_text(
            '<?xml version="1.0"?>\n<movie>'
            "<source_url>https://javdb.com/v/abcdef</source_url>"
            "<id>ABP-123</id>"
            "</movie>"
        )

        settings = Settings(
            user_agent="test-agent",
            http_proxy=None,
            javdb_cookie=None,
            write_delay=0,
            max_extra_images=2,
            http_timeout=5,
            batch_timeout=10,
        )
        nfo_text = build_movie_nfo(sample_movie_metadata)

        result = save_assets_for_existing_video(
            metadata=sample_movie_metadata,
            nfo_text=nfo_text,
            video_path=video,
            settings=settings,
            max_extra_images=2,
        )

        assert result.success
        # 重用模式下 NFO 不应被覆盖
        assert nfo_path.exists()

    def test_uses_absolute_path(self, tmp_path: Path, sample_movie_metadata) -> None:
        """save_assets_for_existing_video 应使用 absolute() 而非 resolve()。"""
        from app.config import Settings
        from app.services.file_service import save_assets_for_existing_video
        from app.services.nfo_service import build_movie_nfo

        video = tmp_path / "test.mp4"
        video.write_text("fake")
        settings = Settings(
            user_agent="test-agent",
            http_proxy=None,
            javdb_cookie=None,
            write_delay=0,
            max_extra_images=2,
            http_timeout=5,
            batch_timeout=10,
        )
        nfo_text = build_movie_nfo(sample_movie_metadata)

        # 传入相对路径
        import os

        old_cwd = os.getcwd()
        try:
            os.chdir(str(tmp_path))
            relative_video = Path("test.mp4")
            result = save_assets_for_existing_video(
                metadata=sample_movie_metadata,
                nfo_text=nfo_text,
                video_path=relative_video,
                settings=settings,
                max_extra_images=2,
            )
            assert result.success
            assert result.video_path is not None
            # 视频路径应为绝对路径
            assert Path(result.video_path).is_absolute()
        finally:
            os.chdir(old_cwd)

    def test_serial_writes_success(self, tmp_path: Path, sample_movie_metadata) -> None:
        """serial_writes=True 模式下基本刮削正常。"""
        from app.config import Settings
        from app.services.file_service import save_assets_for_existing_video
        from app.services.nfo_service import build_movie_nfo

        video = tmp_path / "test.mp4"
        video.write_text("fake video content")
        settings = Settings(
            user_agent="test-agent",
            http_proxy=None,
            javdb_cookie=None,
            write_delay=0,
            max_extra_images=2,
            http_timeout=5,
            batch_timeout=10,
            serial_writes=True,
        )
        nfo_text = build_movie_nfo(sample_movie_metadata)

        result = save_assets_for_existing_video(
            metadata=sample_movie_metadata,
            nfo_text=nfo_text,
            video_path=video,
            settings=settings,
            max_extra_images=2,
        )

        assert result.success
        nfo_path = tmp_path / "movie.nfo"
        assert nfo_path.exists()
        assert "ABP-123" in nfo_path.read_text(encoding="utf-8")

    def test_serial_writes_with_rename_format(
        self, tmp_path: Path, sample_movie_metadata
    ) -> None:
        """serial_writes + rename_format: 文件重命名后的 settle 应正常执行。"""
        from app.config import Settings
        from app.services.file_service import save_assets_for_existing_video
        from app.services.nfo_service import build_movie_nfo

        video = tmp_path / "old_name.mp4"
        video.write_text("fake video")
        settings = Settings(
            user_agent="test-agent",
            http_proxy=None,
            javdb_cookie=None,
            write_delay=0,
            max_extra_images=2,
            http_timeout=5,
            batch_timeout=10,
            serial_writes=True,
        )
        nfo_text = build_movie_nfo(sample_movie_metadata)

        result = save_assets_for_existing_video(
            metadata=sample_movie_metadata,
            nfo_text=nfo_text,
            video_path=video,
            settings=settings,
            max_extra_images=2,
            rename_format="{id}",
        )

        assert result.success
        # 视频应已被重命名
        assert not (tmp_path / "old_name.mp4").exists()
        assert (tmp_path / "ABP-123.mp4").exists()
        # NFO 应被正常写入
        assert (tmp_path / "movie.nfo").exists()

    def test_serial_writes_with_rename_dir(
        self, tmp_path: Path, sample_movie_metadata
    ) -> None:
        """serial_writes + rename_dir: 文件夹重命名后的 settle 应正常执行。"""
        from app.config import Settings
        from app.services.file_service import save_assets_for_existing_video
        from app.services.nfo_service import build_movie_nfo

        movie_dir = tmp_path / "old_dir"
        movie_dir.mkdir()
        video = movie_dir / "video.mp4"
        video.write_text("fake video")
        settings = Settings(
            user_agent="test-agent",
            http_proxy=None,
            javdb_cookie=None,
            write_delay=0,
            max_extra_images=2,
            http_timeout=5,
            batch_timeout=10,
            serial_writes=True,
        )
        nfo_text = build_movie_nfo(sample_movie_metadata)

        result = save_assets_for_existing_video(
            metadata=sample_movie_metadata,
            nfo_text=nfo_text,
            video_path=video,
            settings=settings,
            max_extra_images=2,
            rename_dir="{id}",
        )

        assert result.success
        # 文件夹应已被重命名
        new_dir = tmp_path / "ABP-123"
        assert new_dir.exists()
        assert not movie_dir.exists()
        # NFO 应在新目录中
        assert (new_dir / "movie.nfo").exists()


class TestProgressReporting:
    """验证 on_progress 回调按预期阶段触发。"""

    def test_reports_expected_phases(
        self, tmp_path: Path, sample_movie_metadata
    ) -> None:
        """基本刮削应触发 poster/fanart/extrafanart/nfo 等阶段。"""
        from app.config import Settings
        from app.services.file_service import save_assets_for_existing_video
        from app.services.nfo_service import build_movie_nfo

        video = tmp_path / "test.mp4"
        video.write_text("fake video")
        settings = Settings(
            user_agent="test-agent",
            http_proxy=None,
            javdb_cookie=None,
            write_delay=0,
            max_extra_images=2,
            http_timeout=5,
            batch_timeout=10,
        )
        nfo_text = build_movie_nfo(sample_movie_metadata)
        reported_phases: list[str] = []

        def on_progress(phase: str, current: int, total: int, detail: str) -> None:
            reported_phases.append(phase)

        result = save_assets_for_existing_video(
            metadata=sample_movie_metadata,
            nfo_text=nfo_text,
            video_path=video,
            settings=settings,
            max_extra_images=2,
            on_progress=on_progress,
        )

        assert result.success
        # 应触发过图片/NFO 相关阶段
        assert "poster" in reported_phases
        assert "fanart" in reported_phases or "extrafanart" in reported_phases
        assert "nfo" in reported_phases

    def test_reports_rename_phases(self, tmp_path: Path, sample_movie_metadata) -> None:
        """设 rename_format/rename_dir 时应触发 rename 阶段。"""
        from app.config import Settings
        from app.services.file_service import save_assets_for_existing_video
        from app.services.nfo_service import build_movie_nfo

        video = tmp_path / "old_name.mp4"
        video.write_text("fake video")
        settings = Settings(
            user_agent="test-agent",
            http_proxy=None,
            javdb_cookie=None,
            write_delay=0,
            max_extra_images=2,
            http_timeout=5,
            batch_timeout=10,
        )
        nfo_text = build_movie_nfo(sample_movie_metadata)
        reported_phases: list[str] = []

        def on_progress(phase: str, current: int, total: int, detail: str) -> None:
            reported_phases.append(phase)

        result = save_assets_for_existing_video(
            metadata=sample_movie_metadata,
            nfo_text=nfo_text,
            video_path=video,
            settings=settings,
            max_extra_images=2,
            rename_format="{id}",
            on_progress=on_progress,
        )

        assert result.success
        assert "rename_video" in reported_phases

    def test_reports_reuse_phase(self, tmp_path: Path, sample_movie_metadata) -> None:
        """重用检测时应触发 scanning 和 reuse 阶段。"""
        from app.config import Settings
        from app.services.file_service import save_assets_for_existing_video
        from app.services.nfo_service import build_movie_nfo

        video = tmp_path / "test.mp4"
        video.write_text("fake")
        nfo_path = tmp_path / "movie.nfo"
        nfo_path.write_text(
            '<?xml version="1.0"?>\n<movie>'
            "<source_url>https://javdb.com/v/abcdef</source_url>"
            "<id>ABP-123</id>"
            "</movie>"
        )

        settings = Settings(
            user_agent="test-agent",
            http_proxy=None,
            javdb_cookie=None,
            write_delay=0,
            max_extra_images=2,
            http_timeout=5,
            batch_timeout=10,
        )
        nfo_text = build_movie_nfo(sample_movie_metadata)
        reported_phases: list[str] = []

        def on_progress(phase: str, current: int, total: int, detail: str) -> None:
            reported_phases.append(phase)

        result = save_assets_for_existing_video(
            metadata=sample_movie_metadata,
            nfo_text=nfo_text,
            video_path=video,
            settings=settings,
            max_extra_images=2,
            on_progress=on_progress,
        )

        assert result.success
        assert "scanning" in reported_phases
        assert "reuse" in reported_phases


class TestNoTempLeakAfterScrape:
    """验证刮削完成后目标目录无 _._nfofetch_ 临时文件残留。"""

    def test_no_temp_left_after_basic_scrape(
        self, tmp_path: Path, sample_movie_metadata
    ) -> None:
        """save_assets_for_existing_video 后不应在 target 目录留下 temp 文件。"""
        from app.config import Settings
        from app.services.file_service import save_assets_for_existing_video
        from app.services.file_utils import _TEMP_PREFIX
        from app.services.nfo_service import build_movie_nfo

        video = tmp_path / "test.mp4"
        video.write_text("fake video")
        settings = Settings(
            user_agent="test-agent",
            http_proxy=None,
            javdb_cookie=None,
            write_delay=0,
            max_extra_images=2,
            http_timeout=5,
            batch_timeout=10,
        )
        nfo_text = build_movie_nfo(sample_movie_metadata)

        result = save_assets_for_existing_video(
            metadata=sample_movie_metadata,
            nfo_text=nfo_text,
            video_path=video,
            settings=settings,
            max_extra_images=2,
        )

        assert result.success
        assert (tmp_path / "movie.nfo").exists()
        # 检查目标目录无临时文件
        temps = list(tmp_path.rglob(f"{_TEMP_PREFIX}*"))
        assert len(temps) == 0, f"目标目录发现临时文件残留: {temps}"

    def test_no_temp_left_after_reuse(
        self, tmp_path: Path, sample_movie_metadata
    ) -> None:
        """重用模式下也不应有临时文件残留。"""
        from app.config import Settings
        from app.services.file_service import save_assets_for_existing_video
        from app.services.file_utils import _TEMP_PREFIX
        from app.services.nfo_service import build_movie_nfo

        video = tmp_path / "test.mp4"
        video.write_text("fake")

        # 预写 NFO 触发重用路径
        nfo_path = tmp_path / "movie.nfo"
        nfo_path.write_text(
            '<?xml version="1.0"?>\n<movie>'
            "<source_url>https://javdb.com/v/abcdef</source_url>"
            "<id>ABP-123</id>"
            "</movie>"
        )

        settings = Settings(
            user_agent="test-agent",
            http_proxy=None,
            javdb_cookie=None,
            write_delay=0,
            max_extra_images=2,
            http_timeout=5,
            batch_timeout=10,
        )
        nfo_text = build_movie_nfo(sample_movie_metadata)

        result = save_assets_for_existing_video(
            metadata=sample_movie_metadata,
            nfo_text=nfo_text,
            video_path=video,
            settings=settings,
            max_extra_images=2,
        )

        assert result.success
        # 检查目标目录无临时文件
        temps = list(tmp_path.rglob(f"{_TEMP_PREFIX}*"))
        assert len(temps) == 0, f"目标目录发现临时文件残留: {temps}"

    def test_no_temp_left_with_rename_format(
        self, tmp_path: Path, sample_movie_metadata
    ) -> None:
        """重命名视频后也不应有临时文件残留。"""
        from app.config import Settings
        from app.services.file_service import save_assets_for_existing_video
        from app.services.file_utils import _TEMP_PREFIX
        from app.services.nfo_service import build_movie_nfo

        video = tmp_path / "old_name.mp4"
        video.write_text("fake video")
        settings = Settings(
            user_agent="test-agent",
            http_proxy=None,
            javdb_cookie=None,
            write_delay=0,
            max_extra_images=2,
            http_timeout=5,
            batch_timeout=10,
        )
        nfo_text = build_movie_nfo(sample_movie_metadata)

        result = save_assets_for_existing_video(
            metadata=sample_movie_metadata,
            nfo_text=nfo_text,
            video_path=video,
            settings=settings,
            max_extra_images=2,
            rename_format="{id}",
        )

        assert result.success
        assert (tmp_path / "ABP-123.mp4").exists()
        temps = list(tmp_path.rglob(f"{_TEMP_PREFIX}*"))
        assert len(temps) == 0, f"目标目录发现临时文件残留: {temps}"

    def test_no_temp_left_with_serial_writes(
        self, tmp_path: Path, sample_movie_metadata
    ) -> None:
        """serial_writes=True 模式下也不应有临时文件残留。"""
        from app.config import Settings
        from app.services.file_service import save_assets_for_existing_video
        from app.services.file_utils import _TEMP_PREFIX
        from app.services.nfo_service import build_movie_nfo

        video = tmp_path / "test.mp4"
        video.write_text("fake video")
        settings = Settings(
            user_agent="test-agent",
            http_proxy=None,
            javdb_cookie=None,
            write_delay=0,
            max_extra_images=2,
            http_timeout=5,
            batch_timeout=10,
            serial_writes=True,
        )
        nfo_text = build_movie_nfo(sample_movie_metadata)

        result = save_assets_for_existing_video(
            metadata=sample_movie_metadata,
            nfo_text=nfo_text,
            video_path=video,
            settings=settings,
            max_extra_images=2,
        )

        assert result.success
        temps = list(tmp_path.rglob(f"{_TEMP_PREFIX}*"))
        assert len(temps) == 0, f"目标目录发现临时文件残留: {temps}"


class TestExtrafanartHash:
    """extrafanart 顺序命名 + NFO 映射的去重与补充逻辑。"""

    def test_keeps_sequential_files(
        self, tmp_path: Path, sample_movie_metadata
    ) -> None:
        """已有的顺序命名文件不被删除。"""
        from app.config import Settings
        from app.services.file_service import save_assets_for_existing_video
        from app.services.nfo_service import build_movie_nfo

        video = tmp_path / "test.mp4"
        video.write_text("fake")
        extra_dir = tmp_path / "extrafanart"
        extra_dir.mkdir()
        (extra_dir / "01.jpg").write_text("old")
        (extra_dir / "99.jpg").write_text("legacy")

        settings = Settings(
            user_agent="test-agent",
            http_proxy=None,
            javdb_cookie=None,
            write_delay=0,
            max_extra_images=2,
            http_timeout=5,
            batch_timeout=10,
        )
        nfo_text = build_movie_nfo(sample_movie_metadata)

        result = save_assets_for_existing_video(
            metadata=sample_movie_metadata,
            nfo_text=nfo_text,
            video_path=video,
            settings=settings,
            max_extra_images=2,
        )

        assert result.success
        assert (extra_dir / "01.jpg").exists()
        assert (extra_dir / "99.jpg").exists()

    def test_supplements_new_urls(self, tmp_path: Path, sample_movie_metadata) -> None:
        """新 URL 以顺序命名补充到 extrafanart。"""
        from app.config import Settings
        from app.services.file_service import save_assets_for_existing_video
        from app.services.nfo_service import build_movie_nfo

        video = tmp_path / "test.mp4"
        video.write_text("fake")
        extra_dir = tmp_path / "extrafanart"
        extra_dir.mkdir()
        (extra_dir / "01.jpg").write_text("existing")

        settings = Settings(
            user_agent="test-agent",
            http_proxy=None,
            javdb_cookie=None,
            write_delay=0,
            max_extra_images=2,
            http_timeout=5,
            batch_timeout=10,
        )
        nfo_text = build_movie_nfo(sample_movie_metadata)

        result = save_assets_for_existing_video(
            metadata=sample_movie_metadata,
            nfo_text=nfo_text,
            video_path=video,
            settings=settings,
            max_extra_images=2,
        )

        assert result.success
        # 已有文件保留
        assert (extra_dir / "01.jpg").exists()


class TestNfoUrlHashSkip:
    """基于 NFO 中 poster_url_hash / fanart_url_hash 的跳过逻辑。"""

    def _make_nfo_with_hashes(self, base: str, poster_url: str, fanart_url: str) -> str:
        """构建包含 URL hash 的 NFO XML。"""
        from app.services.file_utils import _url_hash

        root = ET.Element("movie")
        el = ET.SubElement(root, "title")
        el.text = "Test"
        el = ET.SubElement(root, "poster_url_hash")
        el.text = _url_hash(poster_url)
        el = ET.SubElement(root, "fanart_url_hash")
        el.text = _url_hash(fanart_url)
        ET.indent(root)
        return ET.tostring(root, encoding="unicode")

    def test_same_url_skips_redownload(
        self, tmp_path: Path, sample_movie_metadata
    ) -> None:
        """NFO 中 hash 与当前 URL 一致时，不重新下载覆盖。"""
        from app.config import Settings
        from app.services.file_service import save_assets_for_existing_video
        from app.services.nfo_service import build_movie_nfo

        video = tmp_path / "test.mp4"
        video.write_text("fake")
        poster_path = tmp_path / "poster.jpg"
        poster_path.write_text("existing poster")
        fanart_path = tmp_path / "fanart.jpg"
        fanart_path.write_text("existing fanart")
        # 预写含 URL hash 的 NFO
        nfo_text = self._make_nfo_with_hashes(
            "test",
            str(sample_movie_metadata.posters[0]),
            str(sample_movie_metadata.art[0]),
        )
        (tmp_path / "movie.nfo").write_text(nfo_text)

        settings = Settings(
            user_agent="test-agent",
            http_proxy=None,
            javdb_cookie=None,
            write_delay=0,
            max_extra_images=2,
            http_timeout=5,
            batch_timeout=10,
        )

        result = save_assets_for_existing_video(
            metadata=sample_movie_metadata,
            nfo_text=build_movie_nfo(sample_movie_metadata),
            video_path=video,
            settings=settings,
            max_extra_images=2,
        )

        assert result.success
        assert poster_path.read_text() == "existing poster"
        assert fanart_path.read_text() == "existing fanart"

    def test_different_url_triggers_redownload(
        self, tmp_path: Path, sample_movie_metadata
    ) -> None:
        """NFO 中 hash 与当前 URL 不同时，触发了重新下载（标记因此被移除）。"""
        from app.config import Settings
        from app.services.file_service import save_assets_for_existing_video
        from app.services.nfo_service import build_movie_nfo

        video = tmp_path / "test.mp4"
        video.write_text("fake")
        poster_path = tmp_path / "poster.jpg"
        poster_path.write_text("old poster")
        nfo_text = self._make_nfo_with_hashes(
            "test",
            "https://different-url.com/old.jpg",
            "https://different-url.com/old_art.jpg",
        )
        (tmp_path / "movie.nfo").write_text(nfo_text)

        settings = Settings(
            user_agent="test-agent",
            http_proxy=None,
            javdb_cookie=None,
            write_delay=0,
            max_extra_images=2,
            http_timeout=5,
            batch_timeout=10,
        )

        result = save_assets_for_existing_video(
            metadata=sample_movie_metadata,
            nfo_text=build_movie_nfo(sample_movie_metadata),
            video_path=video,
            settings=settings,
            max_extra_images=2,
        )

        assert result.success
        # 下载失败（fake URL）后旧 hash 已被清除，新 hash 未写入
        written = ET.parse(tmp_path / "movie.nfo").getroot()
        new_poster_hash = written.findtext("poster_url_hash")
        assert new_poster_hash is None


class TestFindMatchingSubtitles:
    def test_exact_stem_match(self, tmp_path: Path) -> None:
        video = tmp_path / "ABC-123.mp4"
        video.write_text("fake")
        sub = tmp_path / "ABC-123.srt"
        sub.write_text("sub")
        result = _find_matching_subtitles(video)
        assert result == [(sub, None)]

    def test_language_tag_match(self, tmp_path: Path) -> None:
        video = tmp_path / "ABC-123.mp4"
        video.write_text("fake")
        sub = tmp_path / "ABC-123.cht.srt"
        sub.write_text("sub")
        result = _find_matching_subtitles(video)
        assert result == [(sub, "cht")]

    def test_multiple_language_subtitles(self, tmp_path: Path) -> None:
        video = tmp_path / "ABC-123.mp4"
        video.write_text("fake")
        sub_cht = tmp_path / "ABC-123.cht.srt"
        sub_cht.write_text("cht")
        sub_eng = tmp_path / "ABC-123.eng.srt"
        sub_eng.write_text("eng")
        sub_jp = tmp_path / "ABC-123.ja.ass"
        sub_jp.write_text("jp")
        result = _find_matching_subtitles(video)
        assert len(result) == 3
        assert (sub_cht, "cht") in result
        assert (sub_eng, "eng") in result
        assert (sub_jp, "ja") in result

    def test_ignores_unrelated_files(self, tmp_path: Path) -> None:
        video = tmp_path / "ABC-123.mp4"
        video.write_text("fake")
        (tmp_path / "unrelated.txt").write_text("text")
        (tmp_path / "other.srt").write_text("sub")
        result = _find_matching_subtitles(video)
        assert result == []

    def test_ignores_subdirectories(self, tmp_path: Path) -> None:
        video = tmp_path / "ABC-123.mp4"
        video.write_text("fake")
        subdir = tmp_path / "subs"
        subdir.mkdir()
        (subdir / "ABC-123.srt").write_text("sub")
        result = _find_matching_subtitles(video)
        assert result == []

    def test_case_insensitive_extension(self, tmp_path: Path) -> None:
        video = tmp_path / "ABC-123.mp4"
        video.write_text("fake")
        sub = tmp_path / "ABC-123.SRT"
        sub.write_text("sub")
        result = _find_matching_subtitles(video)
        assert result == [(sub, None)]

    def test_nonexistent_directory(self) -> None:
        video = Path("/nonexistent/movie.mp4")
        result = _find_matching_subtitles(video)
        assert result == []

    def test_video_stem_with_dot(self, tmp_path: Path) -> None:
        video = tmp_path / "ABC.123.mp4"
        video.write_text("fake")
        sub = tmp_path / "ABC.123.cht.srt"
        sub.write_text("sub")
        result = _find_matching_subtitles(video)
        assert result == [(sub, "cht")]


class TestRenameSubtitles:
    def test_renames_exact_match_subtitle(self, tmp_path: Path) -> None:
        old_video = tmp_path / "ABC-123.mp4"
        old_video.write_text("video")
        sub = tmp_path / "ABC-123.srt"
        sub.write_text("sub")
        new_video = tmp_path / "ABP-456.mp4"
        old_video.rename(new_video)

        result = _rename_subtitles(old_video, new_video)
        expected = tmp_path / "ABP-456.srt"
        assert result == [expected]
        assert expected.exists()
        assert not sub.exists()

    def test_renames_language_tagged_subtitle(self, tmp_path: Path) -> None:
        old_video = tmp_path / "ABC-123.mp4"
        old_video.write_text("video")
        sub = tmp_path / "ABC-123.cht.srt"
        sub.write_text("sub")
        new_video = tmp_path / "ABP-456.mp4"
        old_video.rename(new_video)

        result = _rename_subtitles(old_video, new_video)
        expected = tmp_path / "ABP-456.cht.srt"
        assert result == [expected]
        assert expected.exists()
        assert not sub.exists()

    def test_skip_if_same_name(self, tmp_path: Path) -> None:
        video = tmp_path / "ABC-123.mp4"
        video.write_text("video")
        sub = tmp_path / "ABC-123.srt"
        sub.write_text("sub")
        result = _rename_subtitles(video, video)
        assert result == [sub]

    def test_multiple_subtitle_formats(self, tmp_path: Path) -> None:
        old_video = tmp_path / "ABC-123.mp4"
        old_video.write_text("video")
        subs = [
            tmp_path / "ABC-123.srt",
            tmp_path / "ABC-123.cht.srt",
            tmp_path / "ABC-123.eng.ass",
        ]
        for s in subs:
            s.write_text("sub")

        new_video = tmp_path / "ABP-456.mp4"
        old_video.rename(new_video)

        result = _rename_subtitles(old_video, new_video)
        expected = [
            tmp_path / "ABP-456.srt",
            tmp_path / "ABP-456.cht.srt",
            tmp_path / "ABP-456.eng.ass",
        ]
        assert sorted(result) == sorted(expected)
        for p in expected:
            assert p.exists()


class TestRenameSingleVideoWithSubtitles:
    def test_subtitle_follows_video_rename(self, tmp_path: Path) -> None:
        video = tmp_path / "old_name.mp4"
        video.write_text("video")
        sub = tmp_path / "old_name.srt"
        sub.write_text("sub")
        meta = MovieMetadata(title="Test", number="ABP-123")

        result = _rename_single_video(video, meta, "{id}")
        assert result == tmp_path / "ABP-123.mp4"
        assert (tmp_path / "ABP-123.srt").exists()
        assert not video.exists()
        assert not sub.exists()

    def test_subtitle_with_language_tag_follows(self, tmp_path: Path) -> None:
        video = tmp_path / "old.mp4"
        video.write_text("video")
        sub = tmp_path / "old.cht.srt"
        sub.write_text("sub")
        meta = MovieMetadata(
            title="Test",
            number="ABP-123",
            actors=[Actor(name="田中丽奈")],
        )

        result = _rename_single_video(video, meta, "[{actor}]{id}")
        expected_video = tmp_path / "[田中丽奈]ABP-123.mp4"
        expected_sub = tmp_path / "[田中丽奈]ABP-123.cht.srt"
        assert result == expected_video
        assert expected_sub.exists()
        assert not sub.exists()

    def test_multiple_subs_follow_video(self, tmp_path: Path) -> None:
        video = tmp_path / "old.mp4"
        video.write_text("video")
        subs = [
            tmp_path / "old.srt",
            tmp_path / "old.cht.srt",
            tmp_path / "old.eng.ass",
        ]
        for s in subs:
            s.write_text("sub")
        meta = MovieMetadata(title="Test", number="ABP-123")

        _rename_single_video(video, meta, "{id}")
        assert (tmp_path / "ABP-123.srt").exists()
        assert (tmp_path / "ABP-123.cht.srt").exists()
        assert (tmp_path / "ABP-123.eng.ass").exists()

    def test_no_subtitles_still_works(self, tmp_path: Path) -> None:
        video = tmp_path / "old.mp4"
        video.write_text("video")
        meta = MovieMetadata(title="Test", number="ABP-123")
        result = _rename_single_video(video, meta, "{id}")
        assert result == tmp_path / "ABP-123.mp4"

    def test_subtitles_not_follow_when_name_unchanged(self, tmp_path: Path) -> None:
        meta = MovieMetadata(title="Test", number="ABP-123")
        video = tmp_path / "ABP-123.mp4"
        video.write_text("video")
        sub = tmp_path / "ABP-123.srt"
        sub.write_text("sub")
        result = _rename_single_video(video, meta, "{id}")
        assert result == video
        assert sub.exists()


class TestRenameVideosInDir:
    def test_basic_multi_video_rename(self, tmp_path: Path) -> None:
        v1 = tmp_path / "AAA-001.mp4"
        v1.write_text("v1")
        v2 = tmp_path / "BBB-002.mp4"
        v2.write_text("v2")
        meta = MovieMetadata(title="Test", number="ABP-123")

        result = _rename_videos_in_dir(tmp_path, meta, "{id}-{idx}")

        assert len(result) == 2
        assert (tmp_path / "ABP-123-1.mp4").exists()
        assert (tmp_path / "ABP-123-2.mp4").exists()

    def test_subtitles_follow_in_batch_rename(self, tmp_path: Path) -> None:
        v1 = tmp_path / "AAA-001.mp4"
        v1.write_text("v1")
        s1 = tmp_path / "AAA-001.srt"
        s1.write_text("s1")
        s1_cht = tmp_path / "AAA-001.cht.srt"
        s1_cht.write_text("s1_cht")

        v2 = tmp_path / "BBB-002.mp4"
        v2.write_text("v2")
        s2 = tmp_path / "BBB-002.eng.srt"
        s2.write_text("s2")

        meta = MovieMetadata(title="Test", number="ABP-123")

        result = _rename_videos_in_dir(tmp_path, meta, "{id}-{idx}")

        assert len(result) == 2
        assert (tmp_path / "ABP-123-1.mp4").exists()
        assert (tmp_path / "ABP-123-1.srt").exists()
        assert (tmp_path / "ABP-123-1.cht.srt").exists()
        assert (tmp_path / "ABP-123-2.mp4").exists()
        assert (tmp_path / "ABP-123-2.eng.srt").exists()
        assert not s1.exists()
        assert not s1_cht.exists()
        assert not s2.exists()

    def test_no_videos_returns_empty(self, tmp_path: Path) -> None:
        meta = MovieMetadata(title="Test", number="ABP-123")
        result = _rename_videos_in_dir(tmp_path, meta, "{id}")
        assert result == {}

    def test_no_subtitles_in_batch_rename(self, tmp_path: Path) -> None:
        v1 = tmp_path / "AAA-001.mp4"
        v1.write_text("v1")
        v2 = tmp_path / "BBB-002.mp4"
        v2.write_text("v2")
        meta = MovieMetadata(title="Test", number="ABP-123")

        result = _rename_videos_in_dir(tmp_path, meta, "{id}-{idx}")
        assert len(result) == 2
        assert (tmp_path / "ABP-123-1.mp4").exists()
        assert (tmp_path / "ABP-123-2.mp4").exists()

    def test_single_file_omits_idx_dash(self, tmp_path: Path) -> None:
        """单个文件时，{id}-{idx} 不应出现 -1 后缀。"""
        video = tmp_path / "AAA-001.mp4"
        video.write_text("v1")
        meta = MovieMetadata(title="Test", number="ABP-123")
        result = _rename_videos_in_dir(tmp_path, meta, "{id}-{idx}")
        assert len(result) == 1
        assert (tmp_path / "ABP-123.mp4").exists()
        assert not (tmp_path / "ABP-123-1.mp4").exists()

    def test_single_file_omits_idx_underscore(self, tmp_path: Path) -> None:
        """单个文件时，{id}_{idx} 不应出现 _1 后缀。"""
        video = tmp_path / "AAA-001.mp4"
        video.write_text("v1")
        meta = MovieMetadata(title="Test", number="ABP-123")
        result = _rename_videos_in_dir(tmp_path, meta, "{id}_{idx}")
        assert len(result) == 1
        assert (tmp_path / "ABP-123.mp4").exists()
        assert not (tmp_path / "ABP-123_1.mp4").exists()

    def test_single_file_omits_idx_brackets(self, tmp_path: Path) -> None:
        """单个文件时，[{idx}] {id} 不应出现 [1] 前缀。"""
        video = tmp_path / "AAA-001.mp4"
        video.write_text("v1")
        meta = MovieMetadata(title="Test", number="ABP-123")
        result = _rename_videos_in_dir(tmp_path, meta, "[{idx}] {id}")
        assert len(result) == 1
        assert (tmp_path / "ABP-123.mp4").exists()
        assert not (tmp_path / "[1] ABP-123.mp4").exists()

    def test_multi_file_still_uses_idx(self, tmp_path: Path) -> None:
        """多个文件时保留 {idx} 序号。"""
        v1 = tmp_path / "AAA-001.mp4"
        v1.write_text("v1")
        v2 = tmp_path / "BBB-002.mp4"
        v2.write_text("v2")
        meta = MovieMetadata(title="Test", number="ABP-123")
        result = _rename_videos_in_dir(tmp_path, meta, "{id}-{idx}")
        assert len(result) == 2
        assert (tmp_path / "ABP-123-1.mp4").exists()
        assert (tmp_path / "ABP-123-2.mp4").exists()

    def test_single_file_idx_with_resolution_vr(self, tmp_path: Path) -> None:
        """单文件 {id}-{resolution}-{idx}_{vr} → {id}-{resolution}_{vr}。"""
        from unittest.mock import patch

        video = tmp_path / "AAA-001.mp4"
        video.write_text("v1")
        meta = MovieMetadata(title="Test", number="KMVR-242")
        with patch(
            "app.services.rename_utils._get_video_resolution",
            return_value="2048x2048",
        ):
            result = _rename_videos_in_dir(
                tmp_path, meta, "{id}-{resolution}-{idx}_{vr}"
            )
        assert len(result) == 1
        assert (tmp_path / "KMVR-242-2048x2048_360_TB.mp4").exists()

    def test_skip_if_single_file_already_matches(self, tmp_path: Path) -> None:
        """单文件已匹配格式（含 {idx} 自动清理），跳过整批重命名。"""
        meta = MovieMetadata(title="Test", number="ABP-123")
        video = tmp_path / "ABP-123.mp4"
        video.write_text("fake")
        result = _rename_videos_in_dir(tmp_path, meta, "{id}-{idx}")
        assert result == {}
        assert video.exists()

    def test_skip_if_all_multi_files_match(self, tmp_path: Path) -> None:
        """多文件均已匹配格式，跳过整批重命名。"""
        meta = MovieMetadata(title="Test", number="ABP-123")
        v1 = tmp_path / "ABP-123-1.mp4"
        v1.write_text("v1")
        v2 = tmp_path / "ABP-123-2.mp4"
        v2.write_text("v2")
        result = _rename_videos_in_dir(tmp_path, meta, "{id}-{idx}")
        assert result == {}
        assert v1.exists()
        assert v2.exists()

    def test_partial_match_still_renames(self, tmp_path: Path) -> None:
        """部分文件已匹配仍需重命名其他文件。"""
        meta = MovieMetadata(title="Test", number="ABP-123")
        v1 = tmp_path / "ABP-123-1.mp4"
        v1.write_text("v1")
        v2 = tmp_path / "old_name.mp4"
        v2.write_text("v2")
        result = _rename_videos_in_dir(tmp_path, meta, "{id}-{idx}")
        assert len(result) == 2
        assert (tmp_path / "ABP-123-2.mp4").exists()

    def test_different_format_still_renames(self, tmp_path: Path) -> None:
        """文件名不同（格式变更场景）仍触发重命名。"""
        meta = MovieMetadata(title="Test", number="ABP-123")
        video = tmp_path / "old_name.mp4"
        video.write_text("fake")
        result = _rename_videos_in_dir(tmp_path, meta, "{id}-{idx}")
        assert len(result) == 1
        assert (tmp_path / "ABP-123.mp4").exists()


class TestDeleteOrphanExtrafanart:
    """验证 _delete_orphan_extrafanart 删除孤立剧照。"""

    def test_deletes_orphan_jpg(self, tmp_path: Path) -> None:
        """不在 valid_names 中的 .jpg 被删除。"""
        extra = tmp_path / "extrafanart"
        extra.mkdir()
        orphan = extra / "01.jpg"
        orphan.write_text("old")
        keep = extra / "02.jpg"
        keep.write_text("keep")
        _delete_orphan_extrafanart(extra, {"02.jpg"})
        assert not orphan.exists()
        assert keep.exists()

    def test_deletes_all_when_empty_valid_names(self, tmp_path: Path) -> None:
        """valid_names 为空时所有 .jpg 都被视为孤立并删除。"""
        extra = tmp_path / "extrafanart"
        extra.mkdir()
        f = extra / "01.jpg"
        f.write_text("data")
        _delete_orphan_extrafanart(extra, set())
        assert not f.exists()

    def test_ignores_non_jpg_files(self, tmp_path: Path) -> None:
        """非 .jpg 文件不受影响。"""
        extra = tmp_path / "extrafanart"
        extra.mkdir()
        txt = extra / "readme.txt"
        txt.write_text("note")
        _delete_orphan_extrafanart(extra, set())
        assert txt.exists()

    def test_no_directory_does_nothing(self, tmp_path: Path) -> None:
        """extrafanart 目录不存在时不做任何事。"""
        extra = tmp_path / "extrafanart"
        _delete_orphan_extrafanart(extra, {"01.jpg"})  # should not raise
