from __future__ import annotations

import logging
import os
import threading
from pathlib import Path

import portalocker

from app.schemas import UserSettings


logger = logging.getLogger(__name__)

_settings_lock = threading.Lock()

_SETTINGS_PATH_ENV = "NFOFETCH_SETTINGS_PATH"


def _default_settings_dir() -> Path:
    """获取默认设置目录，回退链确保 Docker 容器内也能正常工作。"""
    try:
        home = Path.home()
        if str(home) != "~" and home.is_absolute():
            return home / ".config" / "nfofetch"
    except Exception:
        pass
    # 回退 1: HOME 环境变量
    home_env = os.getenv("HOME")
    if home_env:
        return Path(home_env) / ".config" / "nfofetch"
    # 回退 2: 当前工作目录
    return Path.cwd() / ".config" / "nfofetch"


def _settings_path() -> Path:
    env = os.getenv(_SETTINGS_PATH_ENV)
    if env:
        return Path(env)
    return _default_settings_dir() / "settings.json"


def load_user_settings() -> UserSettings:
    path = _settings_path()
    if path.exists():
        try:
            with _settings_lock:
                with open(path, "rb") as f:
                    portalocker.lock(f, portalocker.LOCK_SH)
                    data = f.read().decode("utf-8")
                return UserSettings.model_validate_json(data)
        except Exception:
            logger.warning("设置文件 %s 读取失败，使用默认设置", path)
    return UserSettings()


def save_user_settings(settings: UserSettings) -> None:
    path = _settings_path()
    with _settings_lock:
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "wb") as f:
            portalocker.lock(f, portalocker.LOCK_EX)
            f.write(settings.model_dump_json(indent=2).encode("utf-8"))
