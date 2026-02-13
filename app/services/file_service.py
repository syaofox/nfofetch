from __future__ import annotations

import os
import re
from pathlib import Path
from typing import List, Optional

import httpx

from app.config import Settings
from app.schemas import MovieMetadata, ScrapeResult

# 支持的视频扩展名
VIDEO_EXTENSIONS = (".mp4", ".mkv", ".avi", ".wmv", ".mov", ".webm", ".m4v", ".flv")

# 文件名中不允许的字符（Windows/Linux 通用）
_FILENAME_UNSAFE = re.compile(r'[<>:"/\\|?*\x00-\x1f]')

# 默认重命名格式
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


def _sanitize_filename_part(s: str) -> str:
    """将字符串清理为安全的文件名片段。"""
    s = _FILENAME_UNSAFE.sub("_", s)
    return s.strip(" .") or "_"


def _truncate_to_bytes(s: str, max_bytes: int) -> str:
    """将字符串截断至不超过 max_bytes 字节，避免在 UTF-8 多字节字符中间切断。"""
    b = s.encode("utf-8")
    if len(b) <= max_bytes:
        return s
    b = b[:max_bytes]
    # 移除可能被切断的 UTF-8 续字节（0x80–0xBF）
    while b and (b[-1] & 0xC0) == 0x80:
        b = b[:-1]
    return b.decode("utf-8", errors="replace")


def _format_rename(
    metadata: MovieMetadata,
    idx: int,
    is_vr: bool,
    format_str: str,
) -> str:
    """根据格式字符串生成新文件名（不含扩展名）。"""
    id_val = metadata.number or ""
    year_val = str(metadata.year) if metadata.year else ""
    date_val = metadata.premiered or metadata.releasedate or ""
    actor_val = ""
    if metadata.actors:
        actor_val = metadata.actors[0].name
    title_val = metadata.title or ""
    vr_val = "180_LR" if is_vr else ""

    result = format_str
    result = result.replace("{id}", id_val)
    result = result.replace("{year}", year_val)
    result = result.replace("{date}", date_val)
    result = result.replace("{actor}", actor_val)
    result = result.replace("{title}", title_val)
    result = result.replace("{vr}", vr_val)
    result = result.replace("{idx}", str(idx))

    return _sanitize_filename_part(result)


def _rename_videos_in_dir(
    movie_dir: Path,
    metadata: MovieMetadata,
    format_str: str,
) -> dict[Path, Path]:
    """重命名目录下所有视频文件，返回 旧路径 -> 新路径 映射。"""
    video_files = sorted(
        [p for p in movie_dir.iterdir() if p.is_file() and p.suffix.lower() in VIDEO_EXTENSIONS],
        key=lambda p: p.name.lower(),
    )
    if not video_files:
        return {}

    is_vr = _is_vr(metadata)
    # 两阶段重命名：先到临时名，再到最终名，避免冲突
    temp_renames: list[tuple[Path, Path]] = []
    for i, old_path in enumerate(video_files, start=1):
        base_name = _format_rename(metadata, i, is_vr, format_str)
        ext = old_path.suffix
        ext_bytes = len(ext.encode("utf-8"))
        max_base_bytes = max(1, MAX_FILENAME_BYTES - ext_bytes - RESERVED_SUFFIX_BYTES)
        base_name = _truncate_to_bytes(base_name, max_base_bytes)
        temp_path = movie_dir / f"__nfofetch_tmp_{i}{ext}"
        temp_renames.append((old_path, temp_path))

    # 执行临时重命名
    for old_p, temp_p in temp_renames:
        old_p.rename(temp_p)

    # 最终重命名
    result: dict[Path, Path] = {}
    for i, (_, temp_p) in enumerate(temp_renames, start=1):
        base_name = _format_rename(metadata, i, is_vr, format_str)
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
        result[temp_renames[i - 1][0]] = final_path

    return result


def _write_nfo_and_images(
    *,
    movie_dir: Path,
    nfo_text: str,
    metadata: MovieMetadata,
    settings: Settings,
    max_extra_images: int,
    poster_url: Optional[str] = None,
    fanart_url: Optional[str] = None,
) -> tuple[Path, Optional[Path], Optional[Path], List[Path]]:
    """写入 movie.nfo 并下载图片资源，返回相关路径。"""

    # 写入 movie.nfo
    nfo_path = movie_dir / "movie.nfo"
    with nfo_path.open("w", encoding="utf-8") as f:
        f.write(nfo_text)

    # 下载图片
    poster_path: Optional[Path] = None
    fanart_path: Optional[Path] = None
    extra_paths: List[Path] = []

    # 构造候选 URL 列表（用户选择优先，其次为元数据中的顺序）
    poster_urls: List[str] = []
    if poster_url:
        poster_urls.append(poster_url)
    for u in metadata.posters:
        s = str(u)
        if s not in poster_urls:
            poster_urls.append(s)

    art_urls: List[str] = []
    for u in metadata.art:
        s = str(u)
        if s not in art_urls:
            art_urls.append(s)

    def download_image(url: str, dest: Path) -> bool:
        try:
            # httpx 1.x 不再支持 proxies 关键字，这里通过环境变量传递代理。
            if settings.http_proxy:
                os.environ.setdefault("HTTP_PROXY", settings.http_proxy)
                os.environ.setdefault("HTTPS_PROXY", settings.http_proxy)

            with httpx.Client(
                headers={"User-Agent": settings.user_agent},
                timeout=20.0,
            ) as client:
                with client.stream("GET", url) as resp:
                    resp.raise_for_status()
                    with dest.open("wb") as f:
                        for chunk in resp.iter_bytes():
                            f.write(chunk)
            return True
        except Exception:
            return False

    # 1. poster.jpg
    if poster_urls:
        poster_path = movie_dir / "poster.jpg"
        if not download_image(str(poster_urls[0]), poster_path):
            poster_path = None

    # 2. fanart.jpg
    fanart_candidates: List[str] = []
    if fanart_url:
        fanart_candidates.append(fanart_url)
    if art_urls:
        fanart_candidates.append(str(art_urls[0]))
    if poster_urls:
        fanart_candidates.append(str(poster_urls[0]))

    # 去重保持顺序
    _seen: set[str] = set()
    fanart_candidates = [
        u for u in fanart_candidates if not (u in _seen or _seen.add(u))
    ]

    for url in fanart_candidates:
        fanart_path_candidate = movie_dir / "fanart.jpg"
        if download_image(url, fanart_path_candidate):
            fanart_path = fanart_path_candidate
            break

    # 3. extrafanart/*
    extra_dir = movie_dir / "extrafanart"
    extra_dir.mkdir(exist_ok=True)
    used_urls: set[str] = set()
    if poster_urls:
        used_urls.add(str(poster_urls[0]))
    if art_urls:
        used_urls.add(str(art_urls[0]))
    if poster_url:
        used_urls.add(poster_url)
    if fanart_url:
        used_urls.add(fanart_url)

    all_extra_sources: List[str] = []
    all_extra_sources.extend(str(u) for u in art_urls)
    all_extra_sources.extend(str(u) for u in poster_urls)

    idx = 1
    for url in all_extra_sources:
        if url in used_urls:
            continue
        if idx > max_extra_images:
            break
        dest = extra_dir / f"{idx:02d}.jpg"
        if download_image(url, dest):
            extra_paths.append(dest)
            idx += 1

    return nfo_path, poster_path, fanart_path, extra_paths


def save_assets_for_existing_video(
    *,
    metadata: MovieMetadata,
    nfo_text: str,
    video_path: Path,
    settings: Settings,
    max_extra_images: int = 8,
    poster_url: Optional[str] = None,
    fanart_url: Optional[str] = None,
    rename_format: Optional[str] = None,
) -> ScrapeResult:
    """针对已存在的视频文件，在同一目录下生成 NFO 和图片，不复制视频。

    - movie_dir 使用现有视频文件的父目录；
    - 若提供 rename_format，则按格式重命名目录下所有视频文件。
    """

    video_path = video_path.resolve()
    movie_dir = video_path.parent
    movie_dir.mkdir(parents=True, exist_ok=True)

    # 重命名视频（若指定格式）
    final_video_path = video_path
    if rename_format and rename_format.strip():
        fmt = rename_format.strip()
        try:
            renames = _rename_videos_in_dir(movie_dir, metadata, fmt)
            final_video_path = renames.get(video_path, video_path)
        except OSError as e:
            return ScrapeResult(
                success=False,
                message=f"重命名失败：{e}",
                metadata=metadata,
            )

    nfo_path, poster_path, fanart_path, extra_paths = _write_nfo_and_images(
        movie_dir=movie_dir,
        nfo_text=nfo_text,
        metadata=metadata,
        settings=settings,
        max_extra_images=max_extra_images,
        poster_url=poster_url,
        fanart_url=fanart_url,
    )

    return ScrapeResult(
        success=True,
        message=None,
        metadata=metadata,
        movie_dir=str(movie_dir),
        nfo_path=str(nfo_path),
        video_path=str(final_video_path),
        poster_path=str(poster_path) if poster_path else None,
        fanart_path=str(fanart_path) if fanart_path else None,
        extra_images=[str(p) for p in extra_paths],
        chosen_poster_url=poster_url,
        chosen_fanart_url=fanart_url,
    )

