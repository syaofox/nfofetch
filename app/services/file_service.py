from __future__ import annotations

import fcntl
import functools
import json
import logging
import os
import re
import shutil
import subprocess
import tempfile
import time
import xml.etree.ElementTree as ET
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor, TimeoutError, as_completed
from pathlib import Path

import httpx

from app.config import Settings
from app.retry import retry_request
from app.schemas import MovieMetadata, ScrapeResult
from app.services.file_utils import run_with_timeout, retry_on_oserror

ProgressCallback = Callable[[str, int, int, str], None]

logger = logging.getLogger(__name__)


def _crop_image(image_path: Path, direction: str) -> None:
    """将图片按 2:3 竖版比例裁切（仅对非 none 方向生效），保留指定水平区域。

    始终保留原图全高，将宽度按 2:3 比例裁切，确保 direction 决定保留左/中/右区域。
    若原图宽度不足以达到 2:3，则保持原图不裁切。
    """
    if direction == "none":
        return
    from PIL import Image

    img = Image.open(image_path)
    w, h = img.size

    target_ratio = 2.0 / 3.0
    target_h = h
    target_w = int(target_h * target_ratio)

    if target_w > w:
        logger.warning(
            "图片宽度 %d 不足以裁切成 2:3（需要 %d），跳过裁切",
            w,
            target_w,
        )
        return

    if direction == "left":
        x = 0
    elif direction == "right":
        x = w - target_w
    else:
        x = (w - target_w) // 2

    y = 0
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


def _download_image(
    url: str, dest: Path, settings: Settings, http_timeout: int = 20
) -> bool:
    """下载单张图片到目标路径（原子写入）。"""
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

        with tempfile.NamedTemporaryFile(
            suffix=".tmp", prefix=_TEMP_PREFIX, delete=False
        ) as tmp:
            tmp_path = Path(tmp.name)

        def _fetch() -> None:
            with httpx.Client(**client_kwargs) as client:
                with client.stream("GET", url) as resp:
                    resp.raise_for_status()
                    with tmp_path.open("wb") as f:
                        for chunk in resp.iter_bytes():
                            f.write(chunk)

        try:
            retry_request(_fetch, max_retries=1, base_delay=1.0)
            shutil.move(str(tmp_path), str(dest))
        except Exception:
            tmp_path.unlink(missing_ok=True)
            raise
        return True
    except Exception as exc:
        logger.warning("下载失败: %s - %s", url, exc)
        return False


def _download_image_with_crop(
    url: str,
    dest: Path,
    settings: Settings,
    crop_direction: str = "none",
    http_timeout: int = 20,
) -> bool:
    """下载图片，需要裁切时先下载到临时文件再裁切后移动到目标路径。

    避免在目标目录产生未裁切的临时文件。
    """
    if crop_direction == "none":
        return _download_image(url, dest, settings, http_timeout=http_timeout)

    with tempfile.NamedTemporaryFile(
        suffix=".jpg", prefix=_TEMP_PREFIX, delete=False
    ) as tmp:
        tmp_path = Path(tmp.name)
    try:
        if not _download_image(url, tmp_path, settings, http_timeout=http_timeout):
            tmp_path.unlink(missing_ok=True)
            return False
        _crop_image(tmp_path, crop_direction)
        shutil.move(str(tmp_path), str(dest))
        return True
    except Exception as exc:
        logger.warning("下载/裁切失败: %s - %s", url, exc)
        tmp_path.unlink(missing_ok=True)
        return False


@retry_on_oserror(max_retries=1, base_delay=1.0)
def _atomic_write_text(path: Path, content: str) -> None:
    """原子写入文本文件：先写系统临时文件，再 rename 覆盖目标。

    临时文件放在系统临时目录（/tmp），避免网盘同步工具误上传。
    网络文件系统下支持自动重试一次。
    """
    with tempfile.NamedTemporaryFile(
        suffix=".tmp",
        prefix=_TEMP_PREFIX,
        delete=False,
        mode="w",
        encoding="utf-8",
    ) as f:
        tmp_path = Path(f.name)
        f.write(content)
    try:
        shutil.move(str(tmp_path), str(path))
    except BaseException:
        tmp_path.unlink(missing_ok=True)
        raise


# 临时文件前缀，用于原子写入等
_TEMP_PREFIX = "._nfofetch_"

# 目录锁文件名（fcntl.flock 防止同目录并发刮削）
_LOCK_FILE = ".nfofetch_lock"


def _acquire_dir_lock(
    movie_dir: Path, timeout: float = 10.0
) -> tuple[int, Path] | None:
    """获取目录级别排他锁（fcntl.flock），防止同目录并发刮削。

    返回 (fd, lock_path) 供 _release_dir_lock 使用；超时或失败返回 None。
    """
    lock_path = movie_dir / _LOCK_FILE
    try:
        os.makedirs(str(movie_dir), exist_ok=True)
        fd = os.open(str(lock_path), os.O_CREAT | os.O_RDWR, 0o644)
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                return fd, lock_path
            except (OSError, IOError):
                time.sleep(0.1)
        os.close(fd)
        logger.warning("目录锁等待超时(%.1fs): %s", timeout, movie_dir)
        return None
    except OSError:
        return None


def _release_dir_lock(fd: int, lock_path: Path) -> None:
    """释放目录锁。"""
    try:
        fcntl.flock(fd, fcntl.LOCK_UN)
        os.close(fd)
    except OSError:
        pass


def _cleanup_orphaned_temps(movie_dir: Path) -> None:
    """清理指定目录下残留的 __nfofetch_ 临时文件。"""
    try:
        for p in movie_dir.glob(f"{_TEMP_PREFIX}*"):
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


def _scan_dir_names_impl(movie_dir: Path) -> set[str]:
    with os.scandir(movie_dir) as it:
        return {e.name for e in it}


def _scan_dir_names(movie_dir: Path, timeout: float = 30.0) -> set[str]:
    """一次性扫描目录，返回文件名集合，避免多次 stat。

    通过网络文件系统扫描时，加入超时保护避免长时间阻塞。
    """
    try:
        return run_with_timeout(_scan_dir_names_impl, timeout, movie_dir)
    except (OSError, TimeoutError):
        return set()


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

    # 一次性扫描目录文件列表，后续检查不再走网络 stat
    existing_names = _scan_dir_names(movie_dir)

    # 写入 movie.nfo（原子写入，避免崩溃残留不完整文件）
    nfo_path = movie_dir / "movie.nfo"
    if nfo_path.name in existing_names:
        existing = nfo_path.read_text(encoding="utf-8")
        if existing == nfo_text:
            _report("nfo", 0, 1, "NFO 文件无变化，跳过写入…")
        else:
            _report("nfo", 0, 1, "正在写入 NFO 文件…")
            _atomic_write_text(nfo_path, nfo_text)
    else:
        _report("nfo", 0, 1, "正在写入 NFO 文件…")
        _atomic_write_text(nfo_path, nfo_text)

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
        return _download_image(url, dest, settings, http_timeout=http_timeout)

    # 1. 并行下载 poster.jpg 和 fanart.jpg
    # 先确定两者是否需要下载
    poster_path = movie_dir / "poster.jpg"
    poster_needs_download = True
    if poster_path.name in existing_names:
        try:
            if poster_path.stat().st_size > 0:
                _report("poster", 0, 1, "封面已存在，跳过下载…")
                poster_needs_download = False
        except OSError:
            pass

    fanart_dest = movie_dir / "fanart.jpg"
    fanart_available = False
    if fanart_dest.name in existing_names:
        try:
            fanart_available = fanart_dest.stat().st_size > 0
        except OSError:
            pass
    if fanart_available:
        _report("fanart", 0, 1, "背景已存在，跳过下载…")

    poster_url_val = str(poster_urls[0]) if poster_urls else None

    # 构造 fanart URL 候选列表（用户选择优先 > art[0] > poster[0] 兜底）
    fanart_candidates: list[str] = []
    if fanart_url:
        fanart_candidates.append(fanart_url)
    if art_urls:
        fanart_candidates.append(str(art_urls[0]))
    # poster URL 作为兜底，但如果 poster 正在下载中则跳过（后续用文件拷贝代替）
    if poster_url_val and not poster_needs_download:
        fanart_candidates.append(poster_url_val)
    # 去重
    _seen_set: set[str] = set()
    deduped: list[str] = []
    for c in fanart_candidates:
        if c not in _seen_set:
            _seen_set.add(c)
            deduped.append(c)
    fanart_candidates = deduped

    with ThreadPoolExecutor(max_workers=2) as executor:
        poster_ft = None
        if poster_needs_download and poster_url_val:
            _report("poster", 0, 1, "正在下载封面 poster.jpg…")
            poster_ft = executor.submit(
                _download_image_with_crop,
                poster_url_val,
                poster_path,
                settings,
                crop_direction=crop_direction,
                http_timeout=http_timeout,
            )
        elif not poster_url_val:
            poster_path = None

        fanart_ft = None
        if not fanart_available and fanart_candidates:
            _report("fanart", 0, 1, "正在下载背景 fanart.jpg…")

            def _try_fanart() -> bool:
                for url in fanart_candidates:
                    if download_image(url, fanart_dest):
                        return True
                return False

            fanart_ft = executor.submit(_try_fanart)

        poster_ok = poster_ft.result() if poster_ft else (poster_path is not None)
        if not poster_ok:
            poster_path = None

        fanart_ok = fanart_available
        if fanart_ft:
            fanart_ok = fanart_ft.result()

        # 若 fanart 兜底 URL 是 poster URL 且 poster 下载成功，用文件拷贝代替重复下载
        if (
            not fanart_ok
            and not fanart_available
            and poster_url_val
            and poster_ok
            and poster_path is not None
            and poster_path.exists()
        ):
            shutil.copy2(str(poster_path), str(fanart_dest))
            fanart_ok = True

        fanart_path = fanart_dest if fanart_ok else None  # type: ignore[no-redef]

    # 3. extrafanart/*（并发下载）
    extra_dir = movie_dir / "extrafanart"
    extra_dir.mkdir(exist_ok=True)
    # 一次性扫描 extrafanart 目录，避免多次 stat
    extra_names = _scan_dir_names(extra_dir)
    existing_extras = sorted(
        extra_dir / n for n in extra_names if Path(n).suffix.lower() == ".jpg"
    )
    for p in existing_extras[max_extra_images:]:
        p.unlink()

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
        if dest.name in extra_names:
            try:
                st = dest.stat()
                if st.st_size > 0:
                    extra_paths.append(dest)
                    idx += 1
                    continue
            except OSError:
                pass
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


def _check_reuse_existing(
    movie_dir: Path,
    source_url: str | None,
    number: str | None,
    existing_names: set[str] | None = None,
) -> bool:
    """检查目录是否已有同源或同番号刮削记录。

    若提供 existing_names（预先扫描的文件名集合），跳过独立的 exists() 调用。
    通过网络文件系统时，读取 NFO 文件加超时保护。
    """
    if existing_names is not None:
        if "movie.nfo" not in existing_names:
            return False
    else:
        try:
            if not run_with_timeout(lambda: (movie_dir / "movie.nfo").exists(), 10.0):
                return False
        except TimeoutError:
            return False
    nfo_path = movie_dir / "movie.nfo"
    try:

        def _parse_nfo() -> ET.Element:
            return ET.parse(nfo_path).getroot()

        root = run_with_timeout(_parse_nfo, 10.0)
        if source_url:
            url_el = root.find("source_url")
            if url_el is not None and url_el.text == source_url:
                return True
        if number:
            id_el = root.find("id")
            if id_el is not None and id_el.text == number:
                return True
    except Exception:
        pass
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

    # 避免对网络路径做多余的符号链接解析（absolute() 不触发网络 stat）
    video_path = video_path.absolute()
    movie_dir = video_path.parent
    movie_dir.mkdir(parents=True, exist_ok=True)

    # 获取目录锁，防止同目录并发刮削
    lock = _acquire_dir_lock(movie_dir)
    lock_fd: int | None = None
    lock_path: Path | None = None
    if lock is not None:
        lock_fd, lock_path = lock
    try:
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
        # 在重命名之后、写入之前一次性扫描目录，后续不再走网络 stat
        existing_names = _scan_dir_names(movie_dir)
        reuse = _check_reuse_existing(
            movie_dir,
            str(metadata.source_url) if metadata.source_url else None,
            metadata.number,
            existing_names=existing_names,
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

            # 补充下载缺失的图片（用户可能手动删除了）
            # 先用 existing_names 判断存在性，避免网络 stat
            poster_needs_download = True
            if "poster.jpg" in existing_names:
                try:
                    poster_needs_download = poster_path.stat().st_size == 0
                except OSError:
                    poster_needs_download = True

            if poster_needs_download:
                dl_url = poster_url or (
                    str(metadata.posters[0]) if metadata.posters else None
                )
                if dl_url:
                    if on_progress:
                        on_progress("poster", 0, 1, "封面缺失，正在补充下载…")
                    _download_image_with_crop(
                        dl_url,
                        poster_path,
                        settings,
                        crop_direction=crop_direction,
                        http_timeout=http_timeout,
                    )

            fanart_needs_download = True
            if "fanart.jpg" in existing_names:
                try:
                    fanart_needs_download = fanart_path.stat().st_size == 0
                except OSError:
                    fanart_needs_download = True

            if fanart_needs_download:
                dl_url = (
                    fanart_url
                    or (str(metadata.art[0]) if metadata.art else None)
                    or (str(metadata.posters[0]) if metadata.posters else None)
                )
                if dl_url:
                    if on_progress:
                        on_progress("fanart", 0, 1, "背景缺失，正在补充下载…")
                    _download_image(
                        dl_url, fanart_path, settings, http_timeout=http_timeout
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
        nfo_path, poster_path, fanart_path, extra_paths = _write_nfo_and_images(  # type: ignore[assignment]
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
    finally:
        if lock_fd is not None and lock_path is not None:
            _release_dir_lock(lock_fd, lock_path)
