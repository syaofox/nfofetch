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
    _read_nfo_art_mapping,
    _read_nfo_url_hash,
    _url_hash,
    _write_delay,
    run_with_timeout,
)
from app.services.image_utils import (
    _download_image,
    _download_image_with_crop,
    _download_to_temp,
)
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


def _delete_orphan_extrafanart(extra_dir: Path, valid_names: set[str]) -> None:
    """删除 extrafanart 目录中不在 valid_names 里的 .jpg 文件。"""
    if not extra_dir.is_dir():
        return
    for p in list(extra_dir.iterdir()):
        if p.suffix.lower() == ".jpg" and p.name not in valid_names:
            p.unlink(missing_ok=True)
            logger.info("删除孤立剧照: %s", p.name)


def _write_nfo_and_images(
    *,
    movie_dir: Path,
    nfo_text: str,
    metadata: MovieMetadata,
    settings: Settings,
    poster_url: str | None = None,
    fanart_url: str | None = None,
    crop_direction: str = "none",
    download_concurrency: int = 4,
    http_timeout: int = 20,
    batch_timeout: int = 120,
    existing_names: set[str] | None = None,
    on_progress: ProgressCallback | None = None,
) -> tuple[Path, Path | None, Path | None, list[Path]]:
    """写入 movie.nfo 并下载图片资源，返回相关路径。"""

    def _report(phase: str, current: int, total: int, detail: str) -> None:
        if on_progress:
            on_progress(phase, current, total, detail)

    # 读取已有的 NFO 获取 URL hash 存储（优先使用调用者传入的扫描结果）
    if existing_names is None:
        existing_names = _scan_dir_names(movie_dir)
    nfo_path = movie_dir / "movie.nfo"
    stored_root: ET.Element | None = None
    if nfo_path.name in existing_names:
        try:
            stored_root = ET.parse(nfo_path).getroot()
        except Exception:
            logger.warning("NFO 解析失败（将重新生成）: %s", nfo_path, exc_info=True)

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

    # 1. 下载 poster.jpg 和 fanart.jpg
    poster_path = movie_dir / "poster.jpg"
    fanart_dest = movie_dir / "fanart.jpg"

    poster_url_val = str(poster_urls[0]) if poster_urls else None

    # 构造 fanart URL 候选列表（用户选择优先 > art[0] 兜底）
    fanart_candidates: list[str] = []
    if fanart_url:
        fanart_candidates.append(fanart_url)
    if art_urls:
        fanart_candidates.append(str(art_urls[0]))

    # NFO URL hash 检测：存储在 NFO 中的 hash 与当前 URL 一致则跳过
    poster_needs_download = False
    if poster_url_val is not None:
        stored = _read_nfo_url_hash(stored_root, "poster_url_hash")
        poster_needs_download = stored != _url_hash(poster_url_val)
    fanart_needs_download = False
    if fanart_candidates:
        stored = _read_nfo_url_hash(stored_root, "fanart_url_hash")
        fanart_needs_download = stored != _url_hash(fanart_candidates[0])

    # 2. 下载 poster.jpg 和 fanart.jpg（串行或并行取决于 serial_writes）
    poster_ok: bool
    if settings.serial_writes:
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
        elif poster_url_val and not poster_needs_download:
            poster_ok = True

        if not poster_ok:
            poster_path = None

        fanart_ok = not fanart_needs_download
        if fanart_needs_download:
            _report("fanart", 0, 1, "正在下载背景 fanart.jpg…")
            for url in fanart_candidates:
                if download_image(url, fanart_dest):
                    fanart_ok = True
                    break

        # 兜底：poster 下载成功但 fanart 没有时，拷贝 poster 文件
        if (
            not fanart_ok
            and poster_url_val
            and poster_ok
            and poster_path is not None
            and poster_path.exists()
        ):
            shutil.copy2(str(poster_path), str(fanart_dest))
            fanart_ok = True

        fanart_path = fanart_dest if fanart_ok else None
    else:
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
            elif poster_url_val and not poster_needs_download:
                poster_ok = True
            else:
                poster_path = None

            fanart_ft = None
            if fanart_needs_download:
                _report("fanart", 0, 1, "正在下载背景 fanart.jpg…")

                def _try_fanart() -> bool:
                    for url in fanart_candidates:
                        if download_image(url, fanart_dest):
                            return True
                    return False

                fanart_ft = executor.submit(_try_fanart)

            poster_ok = (
                poster_ft.result()
                if poster_ft
                else (poster_path is not None)
                if poster_url_val
                else False
            )  # type: ignore[has-type]
            if not poster_ok:
                poster_path = None

            fanart_ok = not fanart_needs_download
            if fanart_ft:
                fanart_ok = fanart_ft.result()

            # 兜底：poster 下载成功但 fanart 没有时，拷贝 poster 文件
            if (
                not fanart_ok
                and poster_url_val
                and poster_ok
                and poster_path is not None
                and poster_path.exists()
            ):
                shutil.copy2(str(poster_path), str(fanart_dest))
                fanart_ok = True

            fanart_path = fanart_dest if fanart_ok else None  # type: ignore[no-redef]

    _write_delay(settings.write_delay)

    # 3. extrafanart/*（顺序命名 01.jpg, 02.jpg…，不删除已有文件）
    extra_dir = movie_dir / "extrafanart"
    extra_dir.mkdir(exist_ok=True)
    extra_names = _scan_dir_names(extra_dir)

    all_extra_sources: list[str] = []
    all_extra_sources.extend(str(u) for u in art_urls)
    all_extra_sources.extend(str(u) for u in poster_urls)

    # 从 NFO 读取已有的 art_url 映射（url_hash → filename）
    art_mapping = _read_nfo_art_mapping(stored_root)

    # 对已有映射中的文件，确认磁盘上还存在
    existing_extra_by_hash: dict[str, Path] = {}
    for h, fn in art_mapping.items():
        p = extra_dir / fn
        if fn in extra_names:
            existing_extra_by_hash[h] = p
            extra_paths.append(p)

    # 计算下一个可用序号
    existing_nums = sorted(
        int(n.removesuffix(".jpg"))
        for n in extra_names
        if n.endswith(".jpg") and n.removesuffix(".jpg").isdigit()
    )
    next_idx = (existing_nums[-1] + 1) if existing_nums else 1

    download_tasks: list[tuple[str, Path]] = []
    extra_art_write: list[tuple[str, Path]] = []  # (url, dest) for NFO update
    for url in all_extra_sources:
        h = _url_hash(url)
        if h in existing_extra_by_hash:
            continue
        dest = extra_dir / f"{next_idx:02d}.jpg"
        download_tasks.append((url, dest))
        extra_art_write.append((url, dest))
        next_idx += 1

    total_tasks = len(download_tasks)
    _report("extrafanart", 0, total_tasks, "正在下载剧照…")
    if total_tasks > 0:
        # 阶段一：并行下载到 /tmp（HTTP 不涉及 FUSE I/O，始终并行）
        batch_moves: list[tuple[Path, Path]] = []
        with ThreadPoolExecutor(max_workers=download_concurrency) as executor:
            ft_map = {
                executor.submit(
                    _download_to_temp, url, settings, http_timeout=http_timeout
                ): dest
                for url, dest in download_tasks
            }
            completed = 0
            try:
                for future in as_completed(ft_map, timeout=batch_timeout):
                    dest = ft_map[future]
                    tmp = future.result()
                    if tmp is not None:
                        batch_moves.append((tmp, dest))
                    completed += 1
                    _report(
                        "extrafanart",
                        completed,
                        total_tasks,
                        f"正在下载剧照 {completed}/{total_tasks}…",
                    )
            except _FutureTimeoutError:
                for future in ft_map:
                    if not future.done():
                        future.cancel()
                _report(
                    "extrafanart",
                    completed,
                    total_tasks,
                    "下载超时，中止…",
                )

        # 阶段二：批量 move 到 FUSE（serial_writes 时串行 + 停顿）
        move_count = len(batch_moves)
        if settings.serial_writes:
            for move_idx, (tmp, dest) in enumerate(batch_moves, 1):
                _report(
                    "extrafanart",
                    move_idx,
                    move_count,
                    f"正在写入剧照 {move_idx}/{move_count}…",
                )
                _write_delay(settings.write_delay)
                try:
                    shutil.move(str(tmp), str(dest))
                    extra_paths.append(dest)
                except Exception:
                    tmp.unlink(missing_ok=True)
        else:
            for tmp, dest in batch_moves:
                try:
                    shutil.move(str(tmp), str(dest))
                    extra_paths.append(dest)
                except Exception:
                    tmp.unlink(missing_ok=True)

    _write_delay(settings.write_delay)

    # 写入 NFO（含 URL hash 信息）
    root = ET.fromstring(nfo_text)
    if poster_ok and poster_url_val:
        el = ET.SubElement(root, "poster_url_hash")
        el.text = _url_hash(poster_url_val)
    if fanart_path is not None:
        el = ET.SubElement(root, "fanart_url_hash")
        el.text = _url_hash(fanart_candidates[0])
    all_art: dict[str, str] = {}
    all_art.update(art_mapping)
    for art_url, dest_path in extra_art_write:
        all_art[_url_hash(art_url)] = dest_path.name
    if settings.delete_orphan_extrafanart:
        valid = set(all_art.values())
        logger.info("删除孤立剧照: extra_dir=%s valid=%s", extra_dir, valid)
        _delete_orphan_extrafanart(extra_dir, valid)
    for h, fn in all_art.items():
        el = ET.SubElement(root, "art_url")
        el.set("hash", h)
        el.text = fn
    ET.indent(root)
    final_nfo = ET.tostring(root, encoding="unicode")
    _report("nfo", 0, 1, "正在写入 NFO 文件…")
    _atomic_write_text(nfo_path, final_nfo, delay=settings.write_delay)

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
        logger.warning("读取 NFO 失败（将重新刮削）: %s", nfo_path, exc_info=True)
    return False


def _rename_directory(
    movie_dir: Path,
    metadata: MovieMetadata,
    video_path: Path,
    format_str: str,
) -> tuple[Path, Path]:
    """重命名视频所在文件夹，返回 (新目录, 更新后的视频路径)。

    快速匹配：先用空分辨率生成预期目录名，若已匹配则跳过 ffprobe 和重命名。
    """
    is_vr = _is_vr(metadata)
    # 快速匹配：用空分辨率生成预期目录名，若已匹配则直接返回（省 ffprobe）
    resolution = ""
    new_dir_name = _format_dir_rename(
        metadata, is_vr, format_str, resolution=resolution
    )
    parent = movie_dir.parent
    new_dir = parent / new_dir_name
    if new_dir == movie_dir:
        return movie_dir, video_path
    # 需要分辨率信息时再调 ffprobe
    if "{resolution}" in format_str or "{vr}" in format_str:
        resolution = _get_video_resolution(video_path)
    new_dir_name = _format_dir_rename(
        metadata, is_vr, format_str, resolution=resolution
    )
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

    # 获取目录锁，防止同目录并发刮削（默认关闭，单人使用无需）
    lock_acquired = False
    if settings.lock_enabled:
        lock_acquired = _acquire_dir_lock(movie_dir)
    try:
        # 1. 重命名视频文件（始终执行，幂等设计）
        final_video_path = video_path
        if rename_format and rename_format.strip():
            fmt = rename_format.strip()
            if on_progress:
                on_progress("rename_video", 0, 1, "正在重命名视频文件…")
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
        _write_delay(settings.write_delay)

        # 2. 重命名文件夹（在视频重命名之后、NFO 写入之前执行）
        if rename_dir and rename_dir.strip():
            fmt_dir = rename_dir.strip()
            if on_progress:
                on_progress("rename_dir", 0, 1, "正在重命名文件夹…")
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
        _write_delay(settings.write_delay)

        # 3. 去重检测：先 stat 判 NFO 存在，有 NFO 才全目录扫描
        nfo_exists = (movie_dir / "movie.nfo").exists()
        existing_names: set[str] = set()
        reuse = False
        if nfo_exists:
            if on_progress:
                on_progress("scanning", 0, 1, "正在扫描已有文件…")
            existing_names = _scan_dir_names(movie_dir)
            reuse = _check_reuse_existing(
                movie_dir,
                str(metadata.source_url) if metadata.source_url else None,
                metadata.number,
                existing_names=existing_names,
            )
        if reuse:
            if on_progress:
                on_progress("reuse", 0, 1, "检测到已有同源刮削记录，重新下载图片…")
            nfo_path = movie_dir / "movie.nfo"
            poster_path = movie_dir / "poster.jpg"
            fanart_path = movie_dir / "fanart.jpg"
            extra_dir = movie_dir / "extrafanart"

            # 读取已有 NFO 获取 URL hash
            stored_root: ET.Element | None = None
            nfo_file = movie_dir / "movie.nfo"
            try:
                stored_root = ET.parse(nfo_file).getroot()
            except Exception:
                logger.warning(
                    "读取已有 NFO 失败（将重新生成）: %s", nfo_file, exc_info=True
                )

            # poster：NFO URL hash 检测，不同才重新下载
            poster_dl_url = poster_url or (
                str(metadata.posters[0]) if metadata.posters else None
            )
            poster_needs_renew = True
            if poster_dl_url is not None:
                stored = _read_nfo_url_hash(stored_root, "poster_url_hash")
                poster_needs_renew = stored != _url_hash(poster_dl_url)
            if poster_needs_renew and poster_dl_url:
                if on_progress:
                    on_progress("poster", 0, 1, "正在重新下载封面…")
                _download_image_with_crop(
                    poster_dl_url,
                    poster_path,
                    settings,
                    crop_direction=crop_direction,
                    http_timeout=http_timeout,
                )

            # fanart：NFO URL hash 检测，不同才重新下载
            fanart_dl_url = (
                fanart_url
                or (str(metadata.art[0]) if metadata.art else None)
                or (str(metadata.posters[0]) if metadata.posters else None)
            )
            fanart_needs_renew = True
            if fanart_dl_url is not None:
                stored = _read_nfo_url_hash(stored_root, "fanart_url_hash")
                fanart_needs_renew = stored != _url_hash(fanart_dl_url)
            if fanart_needs_renew and fanart_dl_url:
                if on_progress:
                    on_progress("fanart", 0, 1, "正在重新下载背景…")
                _download_image(
                    fanart_dl_url, fanart_path, settings, http_timeout=http_timeout
                )

            # extrafanart：顺序命名，NFO 映射去重，不删除已有
            extra_dir.mkdir(exist_ok=True)
            extra_names = _scan_dir_names(extra_dir)
            art_mapping = _read_nfo_art_mapping(stored_root)
            # 只保留磁盘上还存在的映射
            valid_mapping: dict[str, str] = {}
            for h, fn in art_mapping.items():
                if fn in extra_names:
                    valid_mapping[h] = fn
            existing_nums = sorted(
                int(n.removesuffix(".jpg"))
                for n in extra_names
                if n.endswith(".jpg") and n.removesuffix(".jpg").isdigit()
            )
            next_idx = (existing_nums[-1] + 1) if existing_nums else 1

            all_extra: list[str] = []
            all_extra.extend(str(u) for u in metadata.art)
            all_extra.extend(str(u) for u in metadata.posters)
            extra_downloads: list[tuple[str, Path]] = []
            for url in all_extra:
                h = _url_hash(url)
                if h in valid_mapping:
                    continue
                dest = extra_dir / f"{next_idx:02d}.jpg"
                extra_downloads.append((url, dest))
                next_idx += 1
            total_extra = len(extra_downloads)
            for i, (url, dest) in enumerate(extra_downloads, 1):
                if on_progress:
                    on_progress(
                        "extrafanart",
                        i,
                        total_extra,
                        f"正在下载剧照 {i}/{total_extra}…",
                    )
                _download_image(url, dest, settings, http_timeout=http_timeout)

            extra_images = (
                sorted(str(p) for p in extra_dir.glob("*.jpg"))
                if extra_dir.is_dir()
                else []
            )

            # 更新 NFO 写入 URL hash
            root = ET.fromstring(nfo_text)
            if poster_dl_url:
                el = ET.SubElement(root, "poster_url_hash")
                el.text = _url_hash(poster_dl_url)
            if fanart_dl_url:
                el = ET.SubElement(root, "fanart_url_hash")
                el.text = _url_hash(fanart_dl_url)
            all_art: dict[str, str] = {}
            all_art.update(valid_mapping)
            for url, dest in extra_downloads:
                all_art[_url_hash(url)] = dest.name
            if settings.delete_orphan_extrafanart:
                valid = set(all_art.values())
                logger.info(
                    "删除孤立剧照(reuse): extra_dir=%s valid=%s", extra_dir, valid
                )
                _delete_orphan_extrafanart(extra_dir, valid)
            for h, fn in all_art.items():
                el = ET.SubElement(root, "art_url")
                el.set("hash", h)
                el.text = fn
            ET.indent(root)
            final_nfo = ET.tostring(root, encoding="unicode")
            _atomic_write_text(nfo_file, final_nfo, delay=settings.write_delay)

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
            poster_url=poster_url,
            fanart_url=fanart_url,
            crop_direction=crop_direction,
            download_concurrency=download_concurrency,
            http_timeout=http_timeout,
            batch_timeout=batch_timeout,
            existing_names=existing_names,
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
