from __future__ import annotations

import fcntl
import logging
import os
import time
from pathlib import Path

from app.services.file_utils import _TEMP_PREFIX

logger = logging.getLogger(__name__)

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
    """清理指定目录下残留的 _nfofetch_ 临时文件。"""
    try:
        for p in movie_dir.glob(f"{_TEMP_PREFIX}*"):
            try:
                p.unlink()
                logger.warning("清理残留临时文件: %s", p)
            except OSError:
                pass
    except PermissionError:
        logger.warning("无法扫描 %s（权限不足），跳过临时文件清理", movie_dir)
