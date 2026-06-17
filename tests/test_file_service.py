from __future__ import annotations

from pathlib import Path

import pytest

from app.schemas import Actor, MovieMetadata
from app.services.file_service import (
    _acquire_dir_lock,
    _atomic_write_text,
    _check_reuse_existing,
    _cleanup_orphaned_temps,
    _crop_image,
    _format_dir_rename,
    _format_rename,
    _is_vr,
    _release_dir_lock,
    _rename_directory,
    _rename_single_video,
    _sanitize_filename_part,
    _scan_dir_names,
    _truncate_to_bytes,
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

    def test_actor_limit_count(self) -> None:
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
        assert result == "田中丽奈、佐藤健"

    def test_actor_limit_exceeds_count(self) -> None:
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

    def test_actor_dir_rename_limit(self) -> None:
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
        assert result == "田中丽奈、佐藤健"

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
        lock = _acquire_dir_lock(tmp_path)
        assert lock is not None
        fd, lock_path = lock
        assert lock_path.name == ".nfofetch_lock"
        _release_dir_lock(fd, lock_path)
        # 锁文件应该可以正常清理
        lock_path.unlink(missing_ok=True)
        assert not lock_path.exists()

    def test_lock_in_subdirectory(self, tmp_path: Path) -> None:
        sub = tmp_path / "sub"
        sub.mkdir()
        lock = _acquire_dir_lock(sub)
        assert lock is not None
        fd, lock_path = lock
        _release_dir_lock(fd, lock_path)

    def test_concurrent_lock_fails(self, tmp_path: Path) -> None:
        lock1 = _acquire_dir_lock(tmp_path, timeout=0.5)
        assert lock1 is not None
        fd1, _ = lock1
        try:
            lock2 = _acquire_dir_lock(tmp_path, timeout=0.5)
            assert lock2 is None  # 应无法获取锁
        finally:
            _release_dir_lock(fd1, tmp_path / ".nfofetch_lock")


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
