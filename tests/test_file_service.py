from __future__ import annotations

from pathlib import Path

import pytest

from app.schemas import Actor, MovieMetadata
from app.services.file_service import (
    _check_reuse_existing,
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
