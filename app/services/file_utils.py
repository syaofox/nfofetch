from __future__ import annotations

import hashlib
import logging
import re
import shutil
import tempfile
from concurrent.futures import ThreadPoolExecutor, TimeoutError as _FutureTimeoutError
from pathlib import Path
from typing import Any, Callable, TypeVar
from xml.etree import ElementTree as ET

logger = logging.getLogger(__name__)

T = TypeVar("T")

_SHARED_EXECUTOR = ThreadPoolExecutor(max_workers=4)


def run_with_timeout(
    func: Callable[..., T],
    timeout: float,
    *args: Any,
    **kwargs: Any,
) -> T:
    """在独立线程中执行 func，超过 timeout 秒则抛出 TimeoutError。"""
    future = _SHARED_EXECUTOR.submit(func, *args, **kwargs)
    try:
        return future.result(timeout=timeout)
    except _FutureTimeoutError:
        future.cancel()
        raise TimeoutError(f"Operation timed out after {timeout}s: {func.__name__}")


_TEMP_PREFIX = "._nfofetch_"

_ART_URL_HASH_LEN = 12


def _url_hash(url: str) -> str:
    """返回 URL 的固定长度 hash，用于 NFO 中存储 URL 指纹。"""
    return hashlib.md5(url.encode()).hexdigest()[:_ART_URL_HASH_LEN]


def _read_nfo_url_hash(root: ET.Element | None, tag: str) -> str | None:
    """从 NFO 根元素读取指定 tag 的 URL hash 文本。"""
    if root is None:
        return None
    el = root.find(tag)
    if el is not None and el.text:
        txt = el.text.strip()
        return txt if txt else None
    return None


def _read_nfo_art_mapping(root: ET.Element | None) -> dict[str, str]:
    """从 NFO 读取 art_url 映射（url_hash → filename）。"""
    mapping: dict[str, str] = {}
    if root is None:
        return mapping
    for el in root.findall("art_url"):
        h = el.get("hash", "").strip()
        fn = (el.text or "").strip()
        if h and fn:
            mapping[h] = fn
    return mapping


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

# 支持的字幕扩展名
SUBTITLE_EXTENSIONS = (
    ".srt",
    ".ass",
    ".ssa",
    ".sub",
    ".idx",
    ".sup",
    ".vtt",
    ".pgs",
)

# 文件名中不允许的字符（Windows/Linux 通用）
_FILENAME_UNSAFE = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
# 空括号对（占位符为空时留下）
_EMPTY_BRACKETS = re.compile(r"\[\s*\]")


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
