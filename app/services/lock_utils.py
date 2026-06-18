from __future__ import annotations

import logging
import os
import time
from pathlib import Path

from app.services.file_utils import _TEMP_PREFIX

logger = logging.getLogger(__name__)

_LOCK_FILE = ".nfofetch_lock"
_STALE_LOCK_SECS = 60


def _acquire_dir_lock(movie_dir: Path, timeout: float = 10.0) -> bool:
    """获取目录级别排他锁（O_EXCL 原子创建），防止同目录并发刮削。

    使用 O_EXCL 原子创建锁文件，避免依赖 fcntl.flock（多数 FUSE 文件系统不支持）。
    返回 True 表示获取成功，False 表示超时或失败。
    """
    lock_path = movie_dir / _LOCK_FILE
    try:
        os.makedirs(str(movie_dir), exist_ok=True)
    except OSError:
        return False

    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            fd = os.open(str(lock_path), os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644)
            os.write(fd, str(time.time()).encode())
            os.close(fd)
            return True
        except FileExistsError:
            pass
        except OSError:
            return False

        # Lock file exists — check if stale (crashed process)
        try:
            st = os.stat(str(lock_path))
            if time.time() - st.st_mtime > _STALE_LOCK_SECS:
                os.unlink(str(lock_path))
                continue
        except OSError:
            pass

        time.sleep(0.1)

    logger.warning("目录锁等待超时(%.1fs): %s", timeout, movie_dir)
    return False


def _release_dir_lock(movie_dir: Path) -> None:
    """释放目录锁。"""
    lock_path = movie_dir / _LOCK_FILE
    try:
        os.unlink(str(lock_path))
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
