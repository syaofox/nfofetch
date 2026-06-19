from __future__ import annotations

import logging
from pathlib import Path

from app.services.file_utils import SUBTITLE_EXTENSIONS, _rename_with_retry

logger = logging.getLogger(__name__)


def _find_matching_subtitles(video_path: Path) -> list[tuple[Path, str | None]]:
    """查找与视频文件匹配的所有字幕文件。

    返回列表，每项为 (字幕路径, 语言标签或 None)。
    匹配规则（不区分扩展名字母大小写）：
    - 同名 + 字幕扩展名 → 无语言标签
    - 同名 + .<语言标签> + 字幕扩展名 → 保留语言标签
    """
    movie_dir = video_path.parent
    video_stem = video_path.stem
    results: list[tuple[Path, str | None]] = []

    try:
        for entry in movie_dir.iterdir():
            if not entry.is_file():
                continue
            ext = entry.suffix.lower()
            if ext not in SUBTITLE_EXTENSIONS:
                continue
            sub_base = entry.stem
            if sub_base == video_stem:
                results.append((entry, None))
            elif sub_base.startswith(video_stem + "."):
                lang = sub_base[len(video_stem) + 1 :]
                results.append((entry, lang))
    except OSError:
        logger.warning("无法扫描目录 %s 查找字幕文件", movie_dir)

    return results


def _rename_subtitles(old_video: Path, new_video: Path) -> list[Path]:
    """将匹配 old_video 的所有字幕文件重命名为匹配 new_video 的名称。

    有语言标签的字幕保留语言标签（如 .cht.srt），无标签的与视频基础名一致。
    返回新字幕路径列表。
    """
    new_stem = new_video.stem
    subtitles = _find_matching_subtitles(old_video)
    renamed: list[Path] = []

    for sub_path, lang in subtitles:
        ext = sub_path.suffix
        if lang:
            new_name = f"{new_stem}.{lang}{ext}"
        else:
            new_name = f"{new_stem}{ext}"
        new_path = sub_path.parent / new_name
        if new_path != sub_path:
            _rename_with_retry(sub_path, new_path)
        renamed.append(new_path)

    return renamed
