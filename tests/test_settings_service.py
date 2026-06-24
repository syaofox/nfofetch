from __future__ import annotations

from app.schemas import UserSettings
from app.services.settings_service import load_user_settings, save_user_settings


class TestUserSettingsPersistence:
    def test_default_settings(self, monkeypatch) -> None:
        monkeypatch.setenv(
            "NFOFETCH_SETTINGS_PATH", "/tmp/nonexistent_settings_test.json"
        )
        settings = load_user_settings()
        assert isinstance(settings, UserSettings)
        assert settings.rename_format == "[{actor}][{date}]{id}"
        assert settings.download_concurrency is None

    def test_round_trip(self, tmp_path, monkeypatch) -> None:
        settings_path = tmp_path / "settings.json"
        monkeypatch.setenv("NFOFETCH_SETTINGS_PATH", str(settings_path))

        settings = UserSettings(rename_format="test-{id}", download_concurrency=8)
        save_user_settings(settings)

        loaded = load_user_settings()
        assert loaded.rename_format == "test-{id}"
        assert loaded.download_concurrency == 8

    def test_load_nonexistent_file(self) -> None:
        settings = load_user_settings()
        assert isinstance(settings, UserSettings)
