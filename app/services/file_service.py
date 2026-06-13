from __future__ import annotations

import fcntl
import json
import logging
import re
import subprocess
import xml.etree.ElementTree as ET
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor, TimeoutError, as_completed
from pathlib import Path

import httpx

from app.config import Settings
from app.retry import retry_request
from app.schemas import MovieMetadata, ScrapeResult

ProgressCallback = Callable[[str, int, int, str], None]

logger = logging.getLogger(__name__)


def _crop_image(image_path: Path, direction: str) -> None:
    """将图片按 2:3 竖版比例裁切（仅对非 none 方向生效），保留指定水平区域。

    当原图已是竖版（宽高比 ≤ 2:3）时，裁切不改变图像。
    """
    if direction == "none":
        return
    from PIL import Image

    img = Image.open(image_path)
    w, h = img.size

    target_ratio = 2.0 / 3.0
    target_w = w
    target_h = int(target_w / target_ratio)
    if target_h > h:
        target_h = h
        target_w = int(target_h * target_ratio)

    if direction == "left":
        x = 0
    elif direction == "right":
        x = w - target_w
    else:
        x = (w - target_w) // 2

    y = (h - target_h) // 2
    cropped = img.crop((x, y, x + target_w, y + target_h))
    cropped.save(image_path)
    logger.info(
        "裁切 poster: %s -> %dx%d（direction=%s, 原图 %dx%d）",
        image_path.name,
        cropped.width,
        cropped.height,
        direction,
        w,
        h,
    )


# 临时文件前缀，用于两阶段重命名
_TEMP_PREFIX = "__nfofetch_tmp_"


class _DirectoryLock:
    """目录级文件锁，防止并发刮削写入同一目录（Issue 4）。

    使用 POSIX fcntl.flock 实现进程级互斥，对同一目录的并发操作会排队等待。
    """

    def __init__(self, directory: Path) -> None:
        self._lock_file = directory / ".nfofetch.lock"
        self._fd: int | None = None

    def __enter__(self) -> _DirectoryLock:
        self._lock_file.parent.mkdir(parents=True, exist_ok=True)
        self._fd = self._lock_file.open("w")
        fcntl.flock(self._fd.fileno(), fcntl.LOCK_EX)
        return self

    def __exit__(self, *args: object) -> None:
        if self._fd is not None:
            fcntl.flock(self._fd.fileno(), fcntl.LOCK_UN)
            self._fd.close()
            self._fd = None


def _cleanup_orphaned_temps(movie_dir: Path) -> None:
    """清理指定目录下残留的 __nfofetch_tmp_ 临时文件。"""
    try:
        for p in movie_dir.rglob(f"{_TEMP_PREFIX}*"):
            try:
                p.unlink()
                logger.warning("清理残留临时文件: %s", p)
            except OSError:
                pass
    except PermissionError:
        logger.warning("无法扫描 %s（权限不足），跳过临时文件清理", movie_dir)


# 支持的视频扩展名
VIDEO_EXTENSIONS = (
    ".mp4",
    ".mkv",
    ".avi",
    ".wmv",
    ".mov",
    ".webm",
    ".m4v",
    ".flv",
    ".ts",
    ".m2ts",
    ".mpg",
    ".mpeg",
    ".vob",
    ".3gp",
    ".ogm",
    ".divx",
    ".f4v",
)

# 文件名中不允许的字符（Windows/Linux 通用）
_FILENAME_UNSAFE = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
# 空括号对（占位符为空时留下）
_EMPTY_BRACKETS = re.compile(r"\[\s*\]")

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
    # 反复清除占位符为空后留下的空括号对，如 []、[  ]
    while True:
        new_s = _EMPTY_BRACKETS.sub("", s)
        if new_s == s:
            break
        s = new_s
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


def _get_video_resolution(video_path: Path) -> str:
    """通过 ffprobe 获取视频分辨率（宽x高），失败返回空字符串。"""
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
            timeout=30,
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
                vr_val = "180_LR" if w >= h else "360_TB"
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
            "、".join(a.name for a in actors_all[: int(m.group(1))])
            if m.group(1)
            else actor_val
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
        vr_val = "180_LR"

    result = format_str
    result = result.replace("{id}", id_val)
    result = result.replace("{year}", year_val)
    result = result.replace("{date}", date_val)
    actors_all = metadata.actors
    result = re.sub(
        r"\{actor(?::(\d+))?\}",
        lambda m: (
            "、".join(a.name for a in actors_all[: int(m.group(1))])
            if m.group(1)
            else actor_val
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
        video_path.rename(new_path)
    return new_path


def _rename_videos_in_dir(
    movie_dir: Path,
    metadata: MovieMetadata,
    format_str: str,
) -> dict[Path, Path]:
    """重命名目录下所有视频文件，返回 旧路径 -> 新路径 映射。"""
    video_files = sorted(
        [
            p
            for p in movie_dir.iterdir()
            if p.is_file() and p.suffix.lower() in VIDEO_EXTENSIONS
        ],
        key=lambda p: p.name.lower(),
    )
    if not video_files:
        return {}

    is_vr = _is_vr(metadata)
    # 清理上次崩溃遗留的临时文件
    _cleanup_orphaned_temps(movie_dir)
    # 两阶段重命名：先到临时名，再到最终名，避免冲突
    temp_renames: list[tuple[Path, Path]] = []
    resolutions: list[str] = []
    for i, old_path in enumerate(video_files, start=1):
        resolution = _get_video_resolution(old_path)
        resolutions.append(resolution)
        base_name = _format_rename(
            metadata, i, is_vr, format_str, resolution=resolution
        )
        ext = old_path.suffix
        ext_bytes = len(ext.encode("utf-8"))
        max_base_bytes = max(1, MAX_FILENAME_BYTES - ext_bytes - RESERVED_SUFFIX_BYTES)
        base_name = _truncate_to_bytes(base_name, max_base_bytes)
        temp_path = movie_dir / f"{_TEMP_PREFIX}{i}{ext}"
        temp_renames.append((old_path, temp_path))

    # 执行临时重命名
    for old_p, temp_p in temp_renames:
        old_p.rename(temp_p)

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
    poster_url: str | None = None,
    fanart_url: str | None = None,
    crop_direction: str = "none",
    download_concurrency: int = 4,
    http_timeout: int = 20,
    batch_timeout: int = 120,
    on_progress: ProgressCallback | None = None,
) -> tuple[Path, Path | None, Path | None, list[Path]]:
    """写入 movie.nfo 并下载图片资源，返回相关路径。"""

    def _report(phase: str, current: int, total: int, detail: str) -> None:
        if on_progress:
            on_progress(phase, current, total, detail)

    # 写入 movie.nfo
    _report("nfo", 0, 1, "正在写入 NFO 文件…")
    nfo_path = movie_dir / "movie.nfo"
    with nfo_path.open("w", encoding="utf-8") as f:
        f.write(nfo_text)

    # 下载图片
    poster_path: Path | None = None
    fanart_path: Path | None = None
    extra_paths: list[Path] = []

    # 构造候选 URL 列表（用户选择优先，其次为元数据中的顺序）
    poster_urls: list[str] = []
    if poster_url:
        poster_urls.append(poster_url)
    for u in metadata.posters:
        s = str(u)
        if s not in poster_urls:
            poster_urls.append(s)

    art_urls: list[str] = []
    for u in metadata.art:
        s = str(u)
        if s not in art_urls:
            art_urls.append(s)

    def download_image(url: str, dest: Path) -> bool:
        try:
            client_kwargs: dict = {
                "headers": {"User-Agent": settings.user_agent},
                "timeout": http_timeout,
            }
            if settings.http_proxy:
                client_kwargs["proxies"] = {
                    "http://": settings.http_proxy,
                    "https://": settings.http_proxy,
                }

            def _fetch() -> None:
                with httpx.Client(**client_kwargs) as client:
                    with client.stream("GET", url) as resp:
                        resp.raise_for_status()
                        with dest.open("wb") as f:
                            for chunk in resp.iter_bytes():
                                f.write(chunk)

            retry_request(_fetch, max_retries=1, base_delay=1.0)
            return True
        except Exception as exc:
            logger.warning("下载失败: %s - %s", url, exc)
            dest.unlink(missing_ok=True)
            return False

    # 1. poster.jpg
    _report("poster", 0, 1, "正在下载封面 poster.jpg…")
    if poster_urls:
        poster_path = movie_dir / "poster.jpg"
        if download_image(str(poster_urls[0]), poster_path):
            if crop_direction != "none":
                _crop_image(poster_path, crop_direction)
        else:
            poster_path = None

    # 2. fanart.jpg
    _report("fanart", 0, 1, "正在下载背景 fanart.jpg…")
    fanart_candidates: list[str] = []
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

    # 3. extrafanart/*（并发下载）
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

    all_extra_sources: list[str] = []
    all_extra_sources.extend(str(u) for u in art_urls)
    all_extra_sources.extend(str(u) for u in poster_urls)

    download_tasks: list[tuple[str, Path]] = []
    idx = 1
    for url in all_extra_sources:
        if url in used_urls:
            continue
        if idx > max_extra_images:
            break
        dest = extra_dir / f"{idx:02d}.jpg"
        if dest.exists() and dest.stat().st_size > 0:
            extra_paths.append(dest)
        else:
            download_tasks.append((url, dest))
        idx += 1

    total_tasks = len(download_tasks)
    _report("extrafanart", 0, total_tasks, "正在下载剧照…")
    if total_tasks > 0:
        with ThreadPoolExecutor(max_workers=download_concurrency) as executor:
            fs = {
                executor.submit(download_image, url, dest): dest
                for url, dest in download_tasks
            }
            completed = 0
            try:
                for future in as_completed(fs, timeout=batch_timeout):
                    dest = fs[future]
                    if future.result():
                        extra_paths.append(dest)
                    completed += 1
                    _report(
                        "extrafanart",
                        completed,
                        total_tasks,
                        f"正在下载剧照 {completed}/{total_tasks}…",
                    )
            except TimeoutError:
                for future in fs:
                    if not future.done():
                        future.cancel()

    return nfo_path, poster_path, fanart_path, extra_paths


def _check_reuse_existing(movie_dir: Path, source_url: str) -> bool:
    """检查目录是否已有同源刮削记录。"""
    nfo_path = movie_dir / "movie.nfo"
    if not nfo_path.exists():
        return False
    try:
        tree = ET.parse(nfo_path)
        root = tree.getroot()
        url_el = root.find("source_url")
        return url_el is not None and url_el.text == source_url
    except Exception:
        return False


def _rename_directory(
    movie_dir: Path,
    metadata: MovieMetadata,
    video_path: Path,
    format_str: str,
) -> tuple[Path, Path]:
    """重命名视频所在文件夹，返回 (新目录, 更新后的视频路径)。"""
    is_vr = _is_vr(metadata)
    resolution = _get_video_resolution(video_path)
    new_dir_name = _format_dir_rename(
        metadata, is_vr, format_str, resolution=resolution
    )
    parent = movie_dir.parent
    new_dir = parent / new_dir_name
    if new_dir == movie_dir:
        return movie_dir, video_path
    if new_dir.exists():
        raise OSError(f"目标文件夹已存在：{new_dir_name}")
    movie_dir.rename(new_dir)
    new_video_path = new_dir / video_path.name
    return new_dir, new_video_path


def save_assets_for_existing_video(
    *,
    metadata: MovieMetadata,
    nfo_text: str,
    video_path: Path,
    settings: Settings,
    max_extra_images: int = 8,
    poster_url: str | None = None,
    fanart_url: str | None = None,
    crop_direction: str = "none",
    rename_format: str | None = None,
    rename_dir: str | None = None,
    download_concurrency: int = 4,
    http_timeout: int = 20,
    batch_timeout: int = 120,
    on_progress: ProgressCallback | None = None,
) -> ScrapeResult:
    """针对已存在的视频文件，在同一目录下生成 NFO 和图片，不复制视频。

    - movie_dir 使用现有视频文件的父目录；
    - 若提供 rename_format：含 {idx} 时重命名同目录下所有视频，不含则仅重命名选中的视频；
    - 若提供 rename_dir：重命名视频所在文件夹。
    """

    video_path = video_path.resolve()
    movie_dir = video_path.parent
    movie_dir.mkdir(parents=True, exist_ok=True)

    # 目录级文件锁，防止并发刮削同一目录（Issue 4）
    with _DirectoryLock(movie_dir):
        # 1. 重命名视频文件（始终执行，幂等设计）
        final_video_path = video_path
        if rename_format and rename_format.strip():
            fmt = rename_format.strip()
            try:
                if "{idx}" in fmt:
                    renames = _rename_videos_in_dir(movie_dir, metadata, fmt)
                    final_video_path = renames.get(video_path, video_path)
                else:
                    final_video_path = _rename_single_video(video_path, metadata, fmt)
            except OSError as e:
                return ScrapeResult(
                    success=False,
                    message=f"重命名失败：{e}",
                    metadata=metadata,
                )

        # 2. 重命名文件夹（在视频重命名之后、NFO 写入之前执行）
        if rename_dir and rename_dir.strip():
            fmt_dir = rename_dir.strip()
            try:
                movie_dir, final_video_path = _rename_directory(
                    movie_dir,
                    metadata,
                    final_video_path,
                    fmt_dir,
                )
            except OSError as e:
                return ScrapeResult(
                    success=False,
                    message=f"文件夹重命名失败：{e}",
                    metadata=metadata,
                )

        # 3. 去重检测：目录已有同源刮削记录 → 跳过 NFO / 图片写入
        reuse = metadata.source_url is not None and _check_reuse_existing(
            movie_dir, str(metadata.source_url)
        )
        if reuse:
            if on_progress:
                on_progress("reuse", 0, 1, "检测到已有同源刮削记录，跳过下载…")
            nfo_path = movie_dir / "movie.nfo"
            poster_path = movie_dir / "poster.jpg"
            fanart_path = movie_dir / "fanart.jpg"
            extra_dir = movie_dir / "extrafanart"
            extra_images = (
                sorted(str(p) for p in extra_dir.glob("*.jpg"))
                if extra_dir.is_dir()
                else []
            )
            return ScrapeResult(
                success=True,
                metadata=metadata,
                movie_dir=str(movie_dir),
                nfo_path=str(nfo_path),
                video_path=str(final_video_path),
                poster_path=str(poster_path) if poster_path.exists() else None,
                fanart_path=str(fanart_path) if fanart_path.exists() else None,
                extra_images=extra_images,
                chosen_poster_url=poster_url,
                chosen_fanart_url=fanart_url,
            )

        # 4. 正常写入 NFO + 图片
        nfo_path, poster_path, fanart_path, extra_paths = _write_nfo_and_images(
            movie_dir=movie_dir,
            nfo_text=nfo_text,
            metadata=metadata,
            settings=settings,
            max_extra_images=max_extra_images,
            poster_url=poster_url,
            fanart_url=fanart_url,
            crop_direction=crop_direction,
            download_concurrency=download_concurrency,
            http_timeout=http_timeout,
            batch_timeout=batch_timeout,
            on_progress=on_progress,
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
