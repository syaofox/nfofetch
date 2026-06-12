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
    assert settings.max_extra_images == 8
    assert settings.http_timeout == 20
    assert settings.batch_timeout == 120
    assert "Firefox" in settings.user_agent or "Mozilla" in settings.user_agent


def test_env_vars(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("NFOFETCH_USER_AGENT", "CustomAgent/1.0")
    monkeypatch.setenv("NFOFETCH_HTTP_PROXY", "http://127.0.0.1:7890")
    monkeypatch.setenv("NFOFETCH_JAVDB_COOKIE", "theme=auto;")
    monkeypatch.setenv("NFOFETCH_MAX_EXTRA_IMAGES", "20")
    monkeypatch.setenv("NFOFETCH_HTTP_TIMEOUT", "30")
    monkeypatch.setenv("NFOFETCH_BATCH_TIMEOUT", "60")

    settings = get_settings()
    assert settings.user_agent == "CustomAgent/1.0"
    assert settings.http_proxy == "http://127.0.0.1:7890"
    assert settings.javdb_cookie == "theme=auto;"
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

    settings = get_settings()
    assert settings.http_proxy is None
    assert settings.javdb_cookie is None


def test_cache_hit() -> None:
    s1 = get_settings()
    s2 = get_settings()
    assert s1 is s2


def test_dataclass_immutable_like() -> None:
    settings = get_settings()
    assert isinstance(settings, Settings)
    assert settings.http_timeout == 20
