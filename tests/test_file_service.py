from __future__ import annotations

from pathlib import Path

from app.schemas import Actor, MovieMetadata
from app.services.file_service import (
    _cleanup_orphaned_temps,
    _format_rename,
    _is_vr,
    _sanitize_filename_part,
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
        temp_file = tmp_path / "__nfofetch_tmp_1.mp4"
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
