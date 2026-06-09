from __future__ import annotations

import os
from pathlib import Path

from app.schemas import UserSettings

_SETTINGS_PATH_ENV = "NFOFETCH_SETTINGS_PATH"
_DEFAULT_SETTINGS_DIR = Path.home() / ".config" / "nfofetch"


def _settings_path() -> Path:
    env = os.getenv(_SETTINGS_PATH_ENV)
    if env:
        return Path(env)
    return _DEFAULT_SETTINGS_DIR / "settings.json"


def load_user_settings() -> UserSettings:
    path = _settings_path()
    if path.exists():
        try:
            return UserSettings.model_validate_json(path.read_text(encoding="utf-8"))
        except Exception:
            pass
    return UserSettings()


def save_user_settings(settings: UserSettings) -> None:
    path = _settings_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(settings.model_dump_json(indent=2), encoding="utf-8")
