from __future__ import annotations

import functools
import hashlib
import logging
import re
import shutil
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor, TimeoutError as _FutureTimeoutError
from pathlib import Path
from typing import Any, Callable, TypeVar
from xml.etree import ElementTree as ET

logger = logging.getLogger(__name__)

T = TypeVar("T")

_SHARED_EXECUTOR = ThreadPoolExecutor(max_workers=4)

_RETRYABLE_ERRNOS: set[int] = {
    5,  # EIO - I/O error (NFS/network disconnect)
    116,  # ESTALE - Stale NFS file handle
    117,  # ENETDOWN - Network is down
    118,  # ENETUNREACH - Network is unreachable
    119,  # ENETRESET - Network dropped connection
    120,  # ECONNABORTED - Connection aborted
    121,  # ECONNRESET - Connection reset
    122,  # ETIMEDOUT - Connection timed out
    123,  # EHOSTUNREACH - No route to host
    124,  # EHOSTDOWN - Host is down
    125,  # EREMOTEIO - Remote I/O error
}


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


def retry_on_oserror(
    max_retries: int = 2,
    base_delay: float = 1.0,
    retryable_errnos: set[int] | None = None,
) -> Callable[[Callable[..., T]], Callable[..., T]]:
    """装饰器：对网络文件系统的 OSError 自动重试。"""
    if retryable_errnos is None:
        retryable_errnos = _RETRYABLE_ERRNOS

    def decorator(func: Callable[..., T]) -> Callable[..., T]:
        @functools.wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> T:
            last_exc: OSError | None = None
            for attempt in range(max_retries + 1):
                try:
                    return func(*args, **kwargs)
                except OSError as e:
                    last_exc = e
                    errno = getattr(e, "errno", None)
                    if errno in retryable_errnos and attempt < max_retries:
                        delay = base_delay * (2**attempt)
                        logger.warning(
                            "OSError (errno=%d) on %s, retry %d/%d in %.1fs: %s",
                            errno,
                            func.__name__,
                            attempt + 1,
                            max_retries,
                            delay,
                            e,
                        )
                        time.sleep(delay)
                        continue
                    raise
            raise last_exc  # type: ignore[misc]

        return wrapper

    return decorator


def _settle_rename(
    path: Path,
    settle_secs: float = 2.0,
    retries: int = 3,
) -> None:
    """重命名后确认路径可访问，并等待 FUSE 文件系统稳定。

    在 FUSE 网络挂载上，rename 返回后 mount daemon 可能仍在处理同步。
    短暂等待 + 重试 stat 可避免后续写入时因 mount 未稳定而断开。
    """
    last_err: OSError | None = None
    for attempt in range(retries):
        try:
            path.stat()
            if settle_secs > 0:
                time.sleep(settle_secs)
            return
        except OSError as e:
            last_err = e
            logger.warning(
                "rename 后路径 stat 失败 (attempt %d/%d): %s - %s",
                attempt + 1,
                retries,
                path,
                e,
            )
            time.sleep(1.0)
    raise OSError(f"rename 后路径仍然不可访问: {path}") from last_err


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
