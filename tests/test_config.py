from __future__ import annotations

from typing import Generator

import pytest

from app.config import Settings, get_settings


@pytest.fixture(autouse=True)
def _clear_cache() -> Generator[None, None, None]:
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def test_default_values() -> None:
    settings = get_settings()
    assert settings.http_proxy is None
    assert settings.javdb_cookie is None
    assert settings.jav321_cookie is None
    assert settings.max_extra_images == 8
    assert settings.http_timeout == 20
    assert settings.batch_timeout == 120
    assert settings.serial_writes is False
    assert settings.write_delay == 0.2
    assert "Firefox" in settings.user_agent or "Mozilla" in settings.user_agent


def test_env_vars(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("NFOFETCH_USER_AGENT", "CustomAgent/1.0")
    monkeypatch.setenv("NFOFETCH_HTTP_PROXY", "http://127.0.0.1:7890")
    monkeypatch.setenv("NFOFETCH_JAVDB_COOKIE", "theme=auto;")
    monkeypatch.setenv("NFOFETCH_JAV321_COOKIE", "test321_cookie")
    monkeypatch.setenv("NFOFETCH_MAX_EXTRA_IMAGES", "20")
    monkeypatch.setenv("NFOFETCH_HTTP_TIMEOUT", "30")
    monkeypatch.setenv("NFOFETCH_BATCH_TIMEOUT", "60")

    settings = get_settings()
    assert settings.user_agent == "CustomAgent/1.0"
    assert settings.http_proxy == "http://127.0.0.1:7890"
    assert settings.javdb_cookie == "theme=auto;"
    assert settings.jav321_cookie == "test321_cookie"
    assert settings.max_extra_images == 20
    assert settings.http_timeout == 30
    assert settings.batch_timeout == 60


def test_invalid_timeout_fallback(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("NFOFETCH_HTTP_TIMEOUT", "not-a-number")
    monkeypatch.setenv("NFOFETCH_BATCH_TIMEOUT", "also-invalid")

    settings = get_settings()
    assert settings.http_timeout == 20
    assert settings.batch_timeout == 120


def test_empty_proxy(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("NFOFETCH_HTTP_PROXY", "")
    monkeypatch.setenv("NFOFETCH_JAVDB_COOKIE", "")
    monkeypatch.setenv("NFOFETCH_JAV321_COOKIE", "")

    settings = get_settings()
    assert settings.http_proxy is None
    assert settings.javdb_cookie is None
    assert settings.jav321_cookie is None


def test_cache_hit() -> None:
    s1 = get_settings()
    s2 = get_settings()
    assert s1 is s2


def test_dataclass_frozen() -> None:
    """Settings 应为 frozen dataclass，赋值时抛出 FrozenInstanceError。"""
    import dataclasses

    settings = get_settings()
    with pytest.raises(dataclasses.FrozenInstanceError):
        settings.http_timeout = 999  # type: ignore[misc]


def test_dataclass_is_settings() -> None:
    settings = get_settings()
    assert isinstance(settings, Settings)
    assert settings.http_timeout == 20


def test_serial_writes_default() -> None:
    settings = get_settings()
    assert settings.serial_writes is False


def test_serial_writes_env_true(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("NFOFETCH_SERIAL_WRITES", "true")
    settings = get_settings()
    assert settings.serial_writes is True


def test_serial_writes_env_1(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("NFOFETCH_SERIAL_WRITES", "1")
    settings = get_settings()
    assert settings.serial_writes is True


def test_serial_writes_env_false(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("NFOFETCH_SERIAL_WRITES", "false")
    settings = get_settings()
    assert settings.serial_writes is False


def test_lock_enabled_default() -> None:
    settings = get_settings()
    assert settings.lock_enabled is False


def test_lock_enabled_env_true(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("NFOFETCH_LOCK_ENABLED", "true")
    settings = get_settings()
    assert settings.lock_enabled is True


def test_lock_enabled_default_in_defaults() -> None:
    settings = get_settings()
    assert settings.lock_enabled is False


def test_javdb_mirror_default() -> None:
    settings = get_settings()
    assert settings.javdb_mirror == "javdb565.com"


def test_javdb_mirror_env_var(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("NFOFETCH_JAVDB_MIRROR", "javdb666.com")
    settings = get_settings()
    assert settings.javdb_mirror == "javdb666.com"


def test_max_extra_images_zero(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("NFOFETCH_MAX_EXTRA_IMAGES", "0")
    settings = get_settings()
    assert settings.max_extra_images == 0


def test_max_extra_images_negative(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("NFOFETCH_MAX_EXTRA_IMAGES", "-1")
    settings = get_settings()
    assert settings.max_extra_images == -1


def test_write_delay_default() -> None:
    settings = get_settings()
    assert settings.write_delay == 0.2


def test_write_delay_env_var(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("NFOFETCH_WRITE_DELAY", "0.5")
    settings = get_settings()
    assert settings.write_delay == 0.5


def test_write_delay_env_zero(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("NFOFETCH_WRITE_DELAY", "0")
    settings = get_settings()
    assert settings.write_delay == 0.0


def test_write_delay_env_invalid_fallback(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("NFOFETCH_WRITE_DELAY", "not-a-number")
    settings = get_settings()
    assert settings.write_delay == 0.2


def test_auto_trim_white_borders_default_false() -> None:
    settings = get_settings()
    assert settings.auto_trim_white_borders is False


def test_auto_trim_white_borders_env_true(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("NFOFETCH_AUTO_TRIM_WHITE_BORDERS", "true")
    settings = get_settings()
    assert settings.auto_trim_white_borders is True


def test_auto_trim_white_borders_env_false(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("NFOFETCH_AUTO_TRIM_WHITE_BORDERS", "false")
    settings = get_settings()
    assert settings.auto_trim_white_borders is False


def test_auto_trim_white_borders_env_1(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("NFOFETCH_AUTO_TRIM_WHITE_BORDERS", "1")
    settings = get_settings()
    assert settings.auto_trim_white_borders is True
