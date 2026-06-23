from __future__ import annotations

import functools
import json
import logging
import os
import re
import subprocess
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from app.schemas import Actor, MovieMetadata
from app.services.lock_utils import _cleanup_orphaned_temps
from app.services.file_utils import (
    VIDEO_EXTENSIONS,
    _TEMP_PREFIX,
    _sanitize_filename_part,
    _truncate_to_bytes,
)
from app.services.subtitle_utils import _rename_subtitles

logger = logging.getLogger(__name__)

DEFAULT_RENAME_FORMAT = "[{actor}][{date}]{id}"

# 常见文件系统单文件名最大字节数（ext4/Windows 等）
MAX_FILENAME_BYTES = 255
# 为重名冲突时追加的 _2、_3 等后缀预留字节
RESERVED_SUFFIX_BYTES = 8


def _is_vr(metadata: MovieMetadata) -> bool:
    """根据元数据判断是否为 VR 视频。"""
    number = (metadata.number or "").upper()
    if "VR" in number:
        return True
    for g in metadata.genres or []:
        if "VR" in g.upper():
            return True
    for t in metadata.tags or []:
        if "VR" in t.upper():
            return True
    return False


def _format_actor_part(actors: list[Actor], limit: int) -> str:
    """格式化演员名：取前 limit 个，超出则加"等x人"后缀。"""
    if limit <= 0:
        return ""
    joined = "、".join(a.name for a in actors[:limit])
    if len(actors) > limit:
        joined += f"等{len(actors)}人"
    return joined


@functools.lru_cache(maxsize=256)
def _get_video_resolution(video_path: Path) -> str:
    """通过 ffprobe 获取视频分辨率（宽x高），失败返回空字符串。

    结果被 LRU 缓存，避免同一文件在重命名过程中重复调用 ffprobe。
    """
    try:
        result = subprocess.run(
            [
                "ffprobe",
                "-v",
                "quiet",
                "-print_format",
                "json",
                "-show_streams",
                str(video_path),
            ],
            capture_output=True,
            text=True,
            timeout=10,
        )
        if result.returncode != 0:
            return ""
        data = json.loads(result.stdout)
        for stream in data.get("streams", []):
            if stream.get("codec_type") == "video":
                w = stream.get("width")
                h = stream.get("height")
                if w and h:
                    return f"{w}x{h}"
        return ""
    except Exception:
        return ""


def _filter_actors_by_gender(
    actors: list[Actor], filter_actor_gender: bool
) -> list[Actor]:
    """若启用过滤，只保留女演员（gender 为 None 时也保留，兼容旧数据）。"""
    if not filter_actor_gender:
        return actors
    return [a for a in actors if a.gender != "male"]


def _format_genre_part(genres: list[str], limit: int) -> str:
    """格式化类别：取前 limit 个，超出则加"等x类"后缀。"""
    if limit <= 0:
        return ""
    joined = "、".join(genres[:limit])
    if len(genres) > limit:
        joined += f"等{len(genres)}类"
    return joined


def _count_files_to_rename(
    video_path: Path,
    rename_format: str | None,
) -> int:
    """计算需要重命名的视频文件数。

    返回 0（无重命名）/ 1（单个文件）/ N（{idx} 模式下目录内视频文件数）。
    """
    fmt = (rename_format or "").strip()
    if not fmt:
        return 0
    if "{idx}" in fmt:
        movie_dir = video_path.absolute().parent
        count = 0
        try:
            with os.scandir(movie_dir) as it:
                for entry in it:
                    if (
                        entry.is_file()
                        and Path(entry.name).suffix.lower() in VIDEO_EXTENSIONS
                    ):
                        count += 1
        except OSError:
            pass
        return count
    return 1


def _format_rename(
    metadata: MovieMetadata,
    idx: int,
    is_vr: bool,
    format_str: str,
    resolution: str = "",
    filter_actor_gender: bool = True,
) -> str:
    """根据格式字符串生成新文件名（不含扩展名）。"""
    id_val = (metadata.number or "").upper()
    year_val = str(metadata.year) if metadata.year else ""
    date_val = metadata.premiered or metadata.releasedate or ""
    actors_for_display = _filter_actors_by_gender(metadata.actors, filter_actor_gender)
    actor_val = "、".join(a.name for a in actors_for_display)
    title_val = metadata.title or ""
    genre_val = "、".join(metadata.genres)
    vr_val = ""
    if is_vr:
        if resolution and "x" in resolution:
            try:
                w_str, h_str = resolution.split("x", 1)
                w, h = int(w_str), int(h_str)
                vr_val = "180_LR" if w > h else "360_TB"
            except (ValueError, IndexError):
                vr_val = "180_LR"
        else:
            vr_val = "180_LR"

    result = format_str
    result = result.replace("{id}", id_val)
    result = result.replace("{year}", year_val)
    result = result.replace("{date}", date_val)
    actors_all = actors_for_display
    result = re.sub(
        r"\{actor(?::(\d+))?\}",
        lambda m: (
            _format_actor_part(actors_all, int(m.group(1))) if m.group(1) else actor_val
        ),
        result,
    )
    genres_all = metadata.genres
    result = re.sub(
        r"\{genre(?::(\d+))?\}",
        lambda m: (
            _format_genre_part(genres_all, int(m.group(1))) if m.group(1) else genre_val
        ),
        result,
    )
    result = result.replace("{title}", title_val)
    result = result.replace("{vr}", vr_val)
    result = result.replace("{resolution}", resolution)
    result = result.replace("{idx}", str(idx))

    return _sanitize_filename_part(result)


def _format_dir_rename(
    metadata: MovieMetadata,
    is_vr: bool,
    format_str: str,
    resolution: str = "",
    filter_actor_gender: bool = True,
) -> str:
    """根据格式字符串生成新文件夹名。"""
    id_val = (metadata.number or "").upper()
    year_val = str(metadata.year) if metadata.year else ""
    date_val = metadata.premiered or metadata.releasedate or ""
    actors_for_display = _filter_actors_by_gender(metadata.actors, filter_actor_gender)
    actor_val = "、".join(a.name for a in actors_for_display)
    title_val = metadata.title or ""
    genre_val = "、".join(metadata.genres)
    vr_val = ""
    if is_vr:
        if resolution and "x" in resolution:
            try:
                w_str, h_str = resolution.split("x", 1)
                w, h = int(w_str), int(h_str)
                vr_val = "180_LR" if w > h else "360_TB"
            except (ValueError, IndexError):
                vr_val = "180_LR"
        else:
            vr_val = "180_LR"

    result = format_str
    result = result.replace("{id}", id_val)
    result = result.replace("{year}", year_val)
    result = result.replace("{date}", date_val)
    actors_all = actors_for_display
    result = re.sub(
        r"\{actor(?::(\d+))?\}",
        lambda m: (
            _format_actor_part(actors_all, int(m.group(1))) if m.group(1) else actor_val
        ),
        result,
    )
    genres_all = metadata.genres
    result = re.sub(
        r"\{genre(?::(\d+))?\}",
        lambda m: (
            _format_genre_part(genres_all, int(m.group(1))) if m.group(1) else genre_val
        ),
        result,
    )
    result = result.replace("{title}", title_val)
    result = result.replace("{vr}", vr_val)
    result = result.replace("{resolution}", resolution)

    return _sanitize_filename_part(result)


def _rename_single_video(
    video_path: Path,
    metadata: MovieMetadata,
    format_str: str,
    filter_actor_gender: bool = True,
) -> Path:
    """仅重命名指定的单个视频文件，返回新路径。

    快速匹配：先用空分辨率生成预期名，若文件已匹配则跳过 ffprobe 和重命名。
    """
    movie_dir = video_path.parent
    ext = video_path.suffix
    is_vr = _is_vr(metadata)

    # 快速匹配：用空分辨率生成预期名，若文件名已匹配则直接返回（省 ffprobe）
    resolution = ""
    base_name = _format_rename(
        metadata,
        1,
        is_vr,
        format_str,
        resolution=resolution,
        filter_actor_gender=filter_actor_gender,
    )
    ext_bytes = len(ext.encode("utf-8"))
    max_base_bytes = max(1, MAX_FILENAME_BYTES - ext_bytes - RESERVED_SUFFIX_BYTES)
    base_name = _truncate_to_bytes(base_name, max_base_bytes)
    if movie_dir / (base_name + ext) == video_path:
        return video_path

    # 需要分辨率信息时再调 ffprobe
    if "{resolution}" in format_str or "{vr}" in format_str:
        resolution = _get_video_resolution(video_path)
    base_name = _format_rename(
        metadata,
        1,
        is_vr,
        format_str,
        resolution=resolution,
        filter_actor_gender=filter_actor_gender,
    )
    base_name = _truncate_to_bytes(base_name, max_base_bytes)
    new_path = movie_dir / (base_name + ext)
    n = 1
    while new_path.exists() and new_path != video_path:
        n += 1
        new_path = movie_dir / f"{base_name}_{n}{ext}"
    if new_path != video_path:
        video_path.rename(new_path)
        _rename_subtitles(video_path, new_path)
    return new_path


def _rename_videos_in_dir(
    movie_dir: Path,
    metadata: MovieMetadata,
    format_str: str,
    filter_actor_gender: bool = True,
) -> dict[Path, Path]:
    """重命名目录下所有视频文件，返回 旧路径 -> 新路径 映射。"""
    video_files: list[Path] = []
    try:
        with os.scandir(movie_dir) as it:
            for entry in sorted(it, key=lambda e: e.name.lower()):
                if (
                    entry.is_file()
                    and Path(entry.name).suffix.lower() in VIDEO_EXTENSIONS
                ):
                    video_files.append(movie_dir / entry.name)
    except OSError:
        pass
    if not video_files:
        return {}

    is_vr = _is_vr(metadata)
    # 清理上次崩溃遗留的临时文件
    _cleanup_orphaned_temps(movie_dir)

    n_files = len(video_files)
    # 单个文件时去掉 {idx}，避免产生 ABP-123-1 这样的多余序号
    if n_files == 1 and "{idx}" in format_str:
        format_str = format_str.replace("{idx}", "")
        # 清理残留的重复分隔符（如 -{idx}_ 变成 -_ 后合并为 _）
        format_str = re.sub(r"[-_]{2,}", lambda m: m.group(0)[-1], format_str)
        format_str = format_str.strip(" -_")

    # 快速匹配：所有文件已有符合格式的名称时跳过整批重命名
    needs_resolution = "{resolution}" in format_str or "{vr}" in format_str
    if not needs_resolution:
        all_match = True
        for i, old_path in enumerate(video_files, start=1):
            ext = old_path.suffix
            base = _format_rename(
                metadata,
                i,
                is_vr,
                format_str,
                resolution="",
                filter_actor_gender=filter_actor_gender,
            )
            ext_bytes = len(ext.encode("utf-8"))
            max_base = max(1, MAX_FILENAME_BYTES - ext_bytes - RESERVED_SUFFIX_BYTES)
            base = _truncate_to_bytes(base, max_base)
            if old_path != movie_dir / (base + ext):
                all_match = False
                break
        if all_match:
            return {}

    resolutions: list[str] = []
    if n_files > 0 and needs_resolution:
        # 仅在格式用到分辨率时运行 ffprobe，避免 FUSE 上不必要的网络 I/O
        with ThreadPoolExecutor(max_workers=min(n_files, 4)) as executor:
            resolutions = list(executor.map(_get_video_resolution, video_files))

    # 两阶段重命名：先到临时名，再到最终名，避免冲突
    temp_renames: list[tuple[Path, Path]] = []
    for i, old_path in enumerate(video_files, start=1):
        resolution = resolutions[i - 1] if resolutions else ""
        base_name = _format_rename(
            metadata,
            i,
            is_vr,
            format_str,
            resolution=resolution,
            filter_actor_gender=filter_actor_gender,
        )
        ext = old_path.suffix
        ext_bytes = len(ext.encode("utf-8"))
        max_base_bytes = max(1, MAX_FILENAME_BYTES - ext_bytes - RESERVED_SUFFIX_BYTES)
        base_name = _truncate_to_bytes(base_name, max_base_bytes)
        temp_path = movie_dir / f"{_TEMP_PREFIX}{i}{ext}"
        temp_renames.append((old_path, temp_path))

    # 执行临时重命名（视频 + 字幕同步）
    for old_p, temp_p in temp_renames:
        old_p.rename(temp_p)
        _rename_subtitles(old_p, temp_p)

    # 最终重命名
    result: dict[Path, Path] = {}
    for i, (_, temp_p) in enumerate(temp_renames, start=1):
        base_name = _format_rename(
            metadata,
            i,
            is_vr,
            format_str,
            resolution=resolutions[i - 1] if resolutions else "",
            filter_actor_gender=filter_actor_gender,
        )
        ext = temp_p.suffix
        ext_bytes = len(ext.encode("utf-8"))
        max_base_bytes = max(1, MAX_FILENAME_BYTES - ext_bytes - RESERVED_SUFFIX_BYTES)
        base_name = _truncate_to_bytes(base_name, max_base_bytes)
        new_path = movie_dir / (base_name + ext)
        # 避免重名冲突，若已存在则追加 _2, _3 等
        final_path = new_path
        n = 1
        while final_path.exists():
            n += 1
            final_path = movie_dir / f"{base_name}_{n}{ext}"
        temp_p.rename(final_path)
        _rename_subtitles(temp_p, final_path)
        result[temp_renames[i - 1][0]] = final_path

    return result
