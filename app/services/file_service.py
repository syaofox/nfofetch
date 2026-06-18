from __future__ import annotations

import logging
import os
import shutil
import xml.etree.ElementTree as ET
from collections.abc import Callable
from concurrent.futures import (
    ThreadPoolExecutor,
    TimeoutError as _FutureTimeoutError,
    as_completed,
)
from pathlib import Path

from app.config import Settings
from app.schemas import MovieMetadata, ScrapeResult
from app.services.file_utils import (
    _atomic_write_text,
    retry_on_oserror,
    run_with_timeout,
)
from app.services.image_utils import _download_image, _download_image_with_crop
from app.services.lock_utils import _acquire_dir_lock, _release_dir_lock
from app.services.rename_utils import (
    _format_dir_rename,
    _get_video_resolution,
    _is_vr,
    _rename_single_video,
    _rename_videos_in_dir,
)

logger = logging.getLogger(__name__)

ProgressCallback = Callable[[str, int, int, str], None]


@retry_on_oserror(max_retries=1, base_delay=1.0)
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

    # 2. 下载 poster.jpg 和 fanart.jpg（串行或并行取决于 serial_writes）
    poster_ok: bool
    if settings.serial_writes:
        # 串行模式：先 poster 后 fanart，避免 FUSE 并发写入
        poster_ok = False
        if poster_needs_download and poster_url_val:
            _report("poster", 0, 1, "正在下载封面 poster.jpg…")
            poster_ok = _download_image_with_crop(
                poster_url_val,
                poster_path,
                settings,
                crop_direction=crop_direction,
                http_timeout=http_timeout,
            )
        elif not poster_url_val:
            poster_path = None
        else:
            poster_ok = True

        if not poster_ok:
            poster_path = None

        fanart_ok = fanart_available
        if not fanart_available and fanart_candidates:
            _report("fanart", 0, 1, "正在下载背景 fanart.jpg…")
            for url in fanart_candidates:
                if download_image(url, fanart_dest):
                    fanart_ok = True
                    break

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

        fanart_path = fanart_dest if fanart_ok else None
    else:
        # 并行模式：poster + fanart 同时下载
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

    # 3. extrafanart/*（串行或并行取决于 serial_writes）
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
        if settings.serial_writes:
            # 串行逐个下载，避免 FUSE 并发写入
            completed = 0
            for url, dest in download_tasks:
                if download_image(url, dest):
                    extra_paths.append(dest)
                completed += 1
                _report(
                    "extrafanart",
                    completed,
                    total_tasks,
                    f"正在下载剧照 {completed}/{total_tasks}…",
                )
        else:
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
                except _FutureTimeoutError:
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
    lock_acquired = _acquire_dir_lock(movie_dir)
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
        if lock_acquired:
            _release_dir_lock(movie_dir)
