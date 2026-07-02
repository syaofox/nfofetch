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
    CropBox,
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


_IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".webp"}


def find_local_images(video_path: Path) -> list[str]:
    """扫描视频文件同目录下的图片文件，返回绝对路径列表。

    用于在刮削预览中自动加载本地已有图片供用户选择。
    FUSE 友好：先 stat 目录刷新缓存，再用 iterdir 扫描。
    """
    movie_dir = video_path.absolute().parent
    try:
        movie_dir.stat()  # FUSE: 触发 getattr 刷新缓存
    except OSError:
        return []
    if not movie_dir.is_dir():
        return []
    images: list[str] = []
    for entry in movie_dir.iterdir():
        try:
            if entry.is_file() and entry.suffix.lower() in _IMAGE_EXTS:
                images.append(str(entry.absolute()))
        except OSError:
            continue
    images.sort()
    return images


def _write_nfo_and_images(
    *,
    movie_dir: Path,
    nfo_text: str,
    metadata: MovieMetadata,
    settings: Settings,
    poster_url: str | None = None,
    fanart_url: str | None = None,
    crop_direction: str = "none",
    crop_box: CropBox = None,
    crop_rotation: float = 0,
    skip_all_processing: bool = False,
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
    # 若有裁切/旋转参数或 auto_trim 激活时，强制重新下载以应用裁切
    # skip_all_processing 时（前端已精确裁切上传），仍需下载但跳过所有处理
    _has_crop = crop_direction != "none" or crop_box is not None or crop_rotation != 0
    poster_needs_download = (
        _has_crop or settings.auto_trim_white_borders or skip_all_processing
    )
    if not poster_needs_download and poster_url_val is not None:
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
                crop_box=crop_box,
                crop_rotation=crop_rotation,
                http_timeout=http_timeout,
                skip_all_processing=skip_all_processing,
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
                    crop_box=crop_box,
                    crop_rotation=crop_rotation,
                    http_timeout=http_timeout,
                    skip_all_processing=skip_all_processing,
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

    # 当前页面的 URL hash 集合（用于孤立检测）
    current_hashes = {_url_hash(u) for u in all_extra_sources}

    # 对已有映射中的文件，确认磁盘上还存在
    existing_extra_by_hash: dict[str, Path] = {}
    for h, fn in art_mapping.items():
        p = extra_dir / fn
        if fn not in extra_names:
            continue
        if settings.delete_orphan_extrafanart and h not in current_hashes:
            continue
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
    filter_actor_gender: bool = True,
) -> tuple[Path, Path]:
    """重命名视频所在文件夹，返回 (新目录, 更新后的视频路径)。

    快速匹配：先用空分辨率生成预期目录名，若已匹配则跳过 ffprobe 和重命名。
    """
    is_vr = _is_vr(metadata)
    # 快速匹配：用空分辨率生成预期目录名，若已匹配则直接返回（省 ffprobe）
    resolution = ""
    new_dir_name = _format_dir_rename(
        metadata,
        is_vr,
        format_str,
        resolution=resolution,
        filter_actor_gender=filter_actor_gender,
    )
    parent = movie_dir.parent
    new_dir = parent / new_dir_name
    if new_dir == movie_dir:
        return movie_dir, video_path
    # 需要分辨率信息时再调 ffprobe
    if "{resolution}" in format_str or "{vr}" in format_str:
        resolution = _get_video_resolution(video_path)
    new_dir_name = _format_dir_rename(
        metadata,
        is_vr,
        format_str,
        resolution=resolution,
        filter_actor_gender=filter_actor_gender,
    )
    new_dir = parent / new_dir_name
    if new_dir == movie_dir:
        return movie_dir, video_path
    if new_dir.exists():
        raise OSError(f"目标文件夹已存在：{new_dir_name}")
    movie_dir.rename(new_dir)
    new_video_path = new_dir / video_path.name
    return new_dir, new_video_path


def _update_local_path_after_move(
    url: str | None,
    old_dir: Path,
    new_dir: Path,
) -> str | None:
    """如果 url 是 old_dir 内的本地文件路径，更新目录前缀到 new_dir。

    用于 rename_dir / move_to_subdir 后更新 poster_url/fanart_url。
    """
    if not url:
        return url
    try:
        p = Path(url).absolute()
        rel = p.relative_to(old_dir.absolute())
    except ValueError:
        return url
    return str(new_dir / rel)


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
    crop_box: CropBox = None,
    crop_rotation: float = 0,
    custom_poster_path: str | None = None,
    custom_fanart_path: str | None = None,
    move_to_subdir: bool = False,
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

    # 自定义上传图片覆盖 poster_url / fanart_url
    if custom_poster_path:
        poster_url = custom_poster_path
    if custom_fanart_path:
        fanart_url = custom_fanart_path

    # 避免对网络路径做多余的符号链接解析（absolute() 不触发网络 stat）
    video_path = video_path.absolute()
    movie_dir = video_path.parent
    movie_dir.mkdir(parents=True, exist_ok=True)

    # 获取目录锁，防止同目录并发刮削（默认关闭，单人使用无需）
    lock_acquired = False
    if settings.lock_enabled:
        lock_acquired = _acquire_dir_lock(movie_dir)
    try:
        # 1. 先移动到子目录（仅处理选中的视频 + 分集，避免影响同目录其他文件）
        final_video_path = video_path
        if move_to_subdir:
            subdir_fmt = (rename_dir or "").strip() or "{id}"
            if on_progress:
                on_progress("move_dir", 0, 1, "正在移动到子目录…")
            try:
                old_movie_dir = movie_dir
                movie_dir, final_video_path = _move_video_to_subdir(
                    movie_dir,
                    video_path,
                    metadata,
                    subdir_fmt,
                    settings,
                )
                poster_url = _update_local_path_after_move(
                    poster_url, old_movie_dir, movie_dir
                )
                fanart_url = _update_local_path_after_move(
                    fanart_url, old_movie_dir, movie_dir
                )
            except OSError as e:
                return ScrapeResult(
                    success=False,
                    message=f"移动到子目录失败：{e}",
                    metadata=metadata,
                )
            _write_delay(settings.write_delay)

        # 2. 重命名视频文件（move_to_subdir 后仅在子目录内操作，不影响其他文件）
        if rename_format and rename_format.strip():
            fmt = rename_format.strip()
            if on_progress:
                on_progress("rename_video", 0, 1, "正在重命名视频文件…")
            try:
                if "{idx}" in fmt:
                    renames = _rename_videos_in_dir(
                        movie_dir,
                        metadata,
                        fmt,
                        filter_actor_gender=settings.filter_actor_gender,
                    )
                    final_video_path = renames.get(final_video_path, final_video_path)
                else:
                    final_video_path = _rename_single_video(
                        final_video_path,
                        metadata,
                        fmt,
                        filter_actor_gender=settings.filter_actor_gender,
                    )
            except OSError as e:
                return ScrapeResult(
                    success=False,
                    message=f"重命名失败：{e}",
                    metadata=metadata,
                )
        _write_delay(settings.write_delay)

        # 3. 重命名文件夹（仅未启用 move_to_subdir 时执行，因为子目录已是最终名）
        if rename_dir and rename_dir.strip() and not move_to_subdir:
            fmt_dir = rename_dir.strip()
            if on_progress:
                on_progress("rename_dir", 0, 1, "正在重命名文件夹…")
            try:
                old_movie_dir = movie_dir
                movie_dir, final_video_path = _rename_directory(
                    movie_dir,
                    metadata,
                    final_video_path,
                    fmt_dir,
                    filter_actor_gender=settings.filter_actor_gender,
                )
                poster_url = _update_local_path_after_move(
                    poster_url, old_movie_dir, movie_dir
                )
                fanart_url = _update_local_path_after_move(
                    fanart_url, old_movie_dir, movie_dir
                )
            except OSError as e:
                return ScrapeResult(
                    success=False,
                    message=f"文件夹重命名失败：{e}",
                    metadata=metadata,
                )
        _write_delay(settings.write_delay)

        # 4. 去重检测：先 stat 判 NFO 存在，有 NFO 才全目录扫描
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
            nfo_path, poster_path, fanart_path, extra_paths = _write_nfo_and_images(
                movie_dir=movie_dir,
                nfo_text=nfo_text,
                metadata=metadata,
                settings=settings,
                poster_url=poster_url,
                fanart_url=fanart_url,
                crop_direction=crop_direction,
                crop_box=crop_box,
                crop_rotation=crop_rotation,
                skip_all_processing=bool(custom_poster_path),
                download_concurrency=download_concurrency,
                http_timeout=http_timeout,
                batch_timeout=batch_timeout,
                existing_names=existing_names,
                on_progress=on_progress,
            )
            return ScrapeResult(
                success=True,
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

        # 5. 正常写入 NFO + 图片
        nfo_path, poster_path, fanart_path, extra_paths = _write_nfo_and_images(
            movie_dir=movie_dir,
            nfo_text=nfo_text,
            metadata=metadata,
            settings=settings,
            poster_url=poster_url,
            fanart_url=fanart_url,
            crop_direction=crop_direction,
            crop_box=crop_box,
            crop_rotation=crop_rotation,
            skip_all_processing=bool(custom_poster_path),
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


def _is_split_base(name: str) -> tuple[str, str | None]:
    """检测文件名是否包含分集后缀（CD1/part1/_1 等），返回 (基名, 后缀)。

    例如 "IPVR-335-CD1.mp4" → ("IPVR-335", "-CD1")
         "ABF-360_part2.mp4" → ("ABF-360", "_part2")
         "IPVR-335.mp4"      → ("IPVR-335", None)
    """
    import re as _re

    stem, _ = os.path.splitext(name)
    m = _re.search(r"[-_](?:CD|PART)(\d+)$", stem, _re.IGNORECASE)
    if m:
        return stem[: m.start()], m.group(0)
    m = _re.search(r"[-_](\d{1,2})$", stem)
    if m:
        return stem[: m.start()], m.group(0)
    return stem, None


def _move_video_to_subdir(
    movie_dir: Path,
    video_path: Path,
    metadata: MovieMetadata,
    subdir_format: str,
    settings: Settings,
) -> tuple[Path, Path]:
    """将视频文件移动到按格式命名的子目录中，并返回 (new_movie_dir, new_video_path)。

    如果视频是分集（如 XXX-123-CD1、XXX-123-CD2），同基名的视频会一起移动。
    """
    from app.services.rename_utils import _get_video_resolution

    is_vr = _is_vr(metadata)
    resolution = _get_video_resolution(video_path)
    subdir_name = _format_dir_rename(
        metadata,
        is_vr,
        subdir_format,
        resolution=resolution,
        filter_actor_gender=settings.filter_actor_gender,
    )
    new_dir = movie_dir / subdir_name
    if new_dir == movie_dir:
        return movie_dir, video_path
    if new_dir.exists():
        raise OSError(f"目标子目录已存在：{subdir_name}")
    new_dir.mkdir(parents=True)

    # 收集需要移动的视频文件（含分集）
    video_exts = (
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
        ".iso",
        ".rmvb",
        ".rm",
        ".asf",
        ".mts",
        ".m2t",
        ".3g2",
        ".qt",
    )
    base_name, _ = _is_split_base(video_path.name)
    to_move: list[Path] = [video_path]
    for f in movie_dir.iterdir():
        if f == video_path or not f.is_file() or f.suffix.lower() not in video_exts:
            continue
        fb, _ = _is_split_base(f.name)
        if fb == base_name:
            to_move.append(f)

    _write_delay(settings.write_delay)
    for src in to_move:
        shutil.move(str(src), str(new_dir / src.name))
    new_video_path = new_dir / video_path.name
    logger.info(
        "移动到子目录: %s → %s（共 %d 个视频文件）",
        video_path.name,
        subdir_name,
        len(to_move),
    )
    return new_dir, new_video_path
