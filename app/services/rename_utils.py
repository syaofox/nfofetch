from __future__ import annotations

import functools
import json
import logging
import os
import re
import subprocess
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from app.schemas import Actor, MovieMetadata
from app.services.lock_utils import _cleanup_orphaned_temps
from app.services.file_utils import (
    VIDEO_EXTENSIONS,
    _TEMP_PREFIX,
    _rename_with_retry,
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


def _format_rename(
    metadata: MovieMetadata,
    idx: int,
    is_vr: bool,
    format_str: str,
    resolution: str = "",
) -> str:
    """根据格式字符串生成新文件名（不含扩展名）。"""
    id_val = metadata.number or ""
    year_val = str(metadata.year) if metadata.year else ""
    date_val = metadata.premiered or metadata.releasedate or ""
    actor_val = "、".join(a.name for a in metadata.actors)
    title_val = metadata.title or ""
    vr_val = ""
    if is_vr:
        if resolution and "x" in resolution:
            try:
                w_str, h_str = resolution.split("x", 1)
                w, h = int(w_str), int(h_str)
                vr_val = "360_TB" if w >= h else "180_LR"
            except (ValueError, IndexError):
                vr_val = "180_LR"
        else:
            vr_val = "180_LR"

    result = format_str
    result = result.replace("{id}", id_val)
    result = result.replace("{year}", year_val)
    result = result.replace("{date}", date_val)
    actors_all = metadata.actors
    result = re.sub(
        r"\{actor(?::(\d+))?\}",
        lambda m: (
            _format_actor_part(actors_all, int(m.group(1))) if m.group(1) else actor_val
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
) -> str:
    """根据格式字符串生成新文件夹名。"""
    id_val = metadata.number or ""
    year_val = str(metadata.year) if metadata.year else ""
    date_val = metadata.premiered or metadata.releasedate or ""
    actor_val = "、".join(a.name for a in metadata.actors)
    title_val = metadata.title or ""
    vr_val = ""
    if is_vr:
        if resolution and "x" in resolution:
            try:
                w_str, h_str = resolution.split("x", 1)
                w, h = int(w_str), int(h_str)
                vr_val = "360_TB" if w >= h else "180_LR"
            except (ValueError, IndexError):
                vr_val = "180_LR"
        else:
            vr_val = "180_LR"

    result = format_str
    result = result.replace("{id}", id_val)
    result = result.replace("{year}", year_val)
    result = result.replace("{date}", date_val)
    actors_all = metadata.actors
    result = re.sub(
        r"\{actor(?::(\d+))?\}",
        lambda m: (
            _format_actor_part(actors_all, int(m.group(1))) if m.group(1) else actor_val
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
) -> Path:
    """仅重命名指定的单个视频文件，返回新路径。"""
    movie_dir = video_path.parent
    ext = video_path.suffix
    is_vr = _is_vr(metadata)
    resolution = _get_video_resolution(video_path)
    base_name = _format_rename(metadata, 1, is_vr, format_str, resolution=resolution)
    ext_bytes = len(ext.encode("utf-8"))
    max_base_bytes = max(1, MAX_FILENAME_BYTES - ext_bytes - RESERVED_SUFFIX_BYTES)
    base_name = _truncate_to_bytes(base_name, max_base_bytes)
    new_path = movie_dir / (base_name + ext)
    n = 1
    while new_path.exists() and new_path != video_path:
        n += 1
        new_path = movie_dir / f"{base_name}_{n}{ext}"
    if new_path != video_path:
        _rename_with_retry(video_path, new_path)
        _rename_subtitles(video_path, new_path)
    return new_path


def _rename_videos_in_dir(
    movie_dir: Path,
    metadata: MovieMetadata,
    format_str: str,
) -> dict[Path, Path]:
    """重命名目录下所有视频文件，返回 旧路径 -> 新路径 映射。"""
    video_files: list[Path] = []
    _scandir_errnos = frozenset({5, 116, 122})
    for _attempt in range(3):
        try:
            with os.scandir(movie_dir) as it:
                for entry in sorted(it, key=lambda e: e.name.lower()):
                    if (
                        entry.is_file()
                        and Path(entry.name).suffix.lower() in VIDEO_EXTENSIONS
                    ):
                        video_files.append(movie_dir / entry.name)
            break
        except OSError as e:
            errno = getattr(e, "errno", None)
            if errno in _scandir_errnos and _attempt < 2:
                time.sleep(1.0)
                continue
            break
    if not video_files:
        return {}

    is_vr = _is_vr(metadata)
    # 清理上次崩溃遗留的临时文件
    _cleanup_orphaned_temps(movie_dir)

    # 并发获取所有视频分辨率（FUSE 文件系统下网络 RTT 并行化）
    n_files = len(video_files)
    resolutions: list[str] = []
    if n_files > 0:
        with ThreadPoolExecutor(max_workers=min(n_files, 4)) as executor:
            resolutions = list(executor.map(_get_video_resolution, video_files))

    # 两阶段重命名：先到临时名，再到最终名，避免冲突
    temp_renames: list[tuple[Path, Path]] = []
    for i, old_path in enumerate(video_files, start=1):
        resolution = resolutions[i - 1] if resolutions else ""
        base_name = _format_rename(
            metadata, i, is_vr, format_str, resolution=resolution
        )
        ext = old_path.suffix
        ext_bytes = len(ext.encode("utf-8"))
        max_base_bytes = max(1, MAX_FILENAME_BYTES - ext_bytes - RESERVED_SUFFIX_BYTES)
        base_name = _truncate_to_bytes(base_name, max_base_bytes)
        temp_path = movie_dir / f"{_TEMP_PREFIX}{i}{ext}"
        temp_renames.append((old_path, temp_path))

    # 执行临时重命名（视频 + 字幕同步）
    for old_p, temp_p in temp_renames:
        _rename_with_retry(old_p, temp_p)
        _rename_subtitles(old_p, temp_p)

    # 最终重命名
    result: dict[Path, Path] = {}
    for i, (_, temp_p) in enumerate(temp_renames, start=1):
        base_name = _format_rename(
            metadata, i, is_vr, format_str, resolution=resolutions[i - 1]
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
        _rename_with_retry(temp_p, final_path)
        _rename_subtitles(temp_p, final_path)
        result[temp_renames[i - 1][0]] = final_path

    return result
