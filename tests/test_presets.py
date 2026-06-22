from __future__ import annotations

from typing import Any, Generator
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.schemas import Preset, UserSettings


@pytest.fixture
def client() -> Generator[TestClient, None, None]:
    with TestClient(app) as c:
        yield c


def _make_settings(presets: dict[str, Any] | None = None) -> dict[str, Any]:
    return {
        "rename_format": "[{actor}][{date}]{id}",
        "rename_dir": "",
        "last_browse_path": "",
        "sort_by": "name",
        "sort_order": "asc",
        "download_concurrency": 4,
        "presets": presets or {},
    }


class TestGetPresets:
    def test_returns_built_in_and_user(self, client: TestClient) -> None:
        with patch(
            "app.main.load_user_settings",
            return_value=type("obj", (), {"presets": {}})(),
        ):
            resp = client.get("/api/presets")
        assert resp.status_code == 200
        data = resp.json()
        assert "built_in" in data
        assert "user" in data
        # 内置预设应包含 "VR"、"非VR"
        assert "VR" in data["built_in"]
        assert "非VR" in data["built_in"]
        assert len(data["built_in"]) == 2

    def test_returns_user_presets(self, client: TestClient) -> None:
        user_presets = {"我的": {"rename_format": "{id}", "rename_dir": "{id}"}}
        with patch(
            "app.main.load_user_settings",
            return_value=type("obj", (), {"presets": user_presets})(),
        ):
            resp = client.get("/api/presets")
        assert resp.status_code == 200
        data = resp.json()
        assert data["user"]["我的"]["rename_format"] == "{id}"


class TestSavePreset:
    def test_saves_new_preset(self, client: TestClient) -> None:
        saved: dict[str, Any] = {}

        def _mock_save(settings: Any) -> None:
            saved["presets"] = settings.presets

        with patch(
            "app.main.load_user_settings",
            return_value=type(
                "obj",
                (),
                {
                    "presets": {},
                    "model_copy": lambda **kw: type("obj", (), kw.get("update", {}))(),
                },
            )(),
        ):
            with patch("app.main.save_user_settings", side_effect=_mock_save):
                resp = client.post(
                    "/api/presets",
                    data={
                        "name": "测试预设",
                        "rename_format": "{id}",
                        "rename_dir": "{id}",
                    },
                )
        assert resp.status_code == 200
        assert resp.json() == {"ok": True}


class TestDeletePreset:
    def test_deletes_user_preset(self, client: TestClient) -> None:
        saved: dict[str, Any] = {}

        def _mock_save(settings: Any) -> None:
            saved["presets"] = settings.presets

        user_presets = {"删除我": Preset(rename_format="{id}", rename_dir="{id}")}

        with patch(
            "app.main.load_user_settings",
            return_value=type(
                "obj",
                (),
                {
                    "presets": user_presets,
                    "model_copy": lambda **kw: type("obj", (), kw.get("update", {}))(),
                },
            )(),
        ):
            with patch("app.main.save_user_settings", side_effect=_mock_save):
                resp = client.delete("/api/presets?name=删除我")
        assert resp.status_code == 200
        assert resp.json() == {"ok": True}


class TestJavdbCookie:
    def test_settings_api_returns_cookie(self, client: TestClient) -> None:
        with patch(
            "app.main.load_user_settings",
            return_value=UserSettings(
                javdb_cookie="theme=auto; over18=1; _jdb_session=xxx"
            ),
        ):
            resp = client.get("/api/settings")
        assert resp.status_code == 200
        data = resp.json()
        assert data["javdb_cookie"] == "theme=auto; over18=1; _jdb_session=xxx"

    def test_save_cookie_via_api(self, client: TestClient) -> None:
        saved: dict[str, Any] = {}
        mock_user = UserSettings()

        def _mock_save(settings: Any) -> None:
            saved["javdb_cookie"] = settings.javdb_cookie

        with patch(
            "app.main.load_user_settings",
            return_value=mock_user,
        ):
            with patch("app.main.save_user_settings", side_effect=_mock_save):
                resp = client.post(
                    "/api/settings",
                    json={"javdb_cookie": "theme=auto; over18=1; _jdb_session=yyy"},
                )
        assert resp.status_code == 200
        assert resp.json() == {"ok": True}
        assert saved.get("javdb_cookie") == "theme=auto; over18=1; _jdb_session=yyy"

    def test_merge_ui_cookie_overrides_env(self) -> None:
        """_merge_ui_cookie 应使用 UI 设置的 cookie 覆盖 env cookie。"""
        from app.config import Settings

        env_settings = Settings(
            user_agent="test",
            http_proxy=None,
            javdb_cookie="env_cookie",
            javdb_mirror="javdb565.com",
            max_extra_images=8,
            http_timeout=20,
            batch_timeout=120,
            serial_writes=False,
            lock_enabled=False,
            write_delay=0.0,
        )
        with patch(
            "app.main.load_user_settings",
            return_value=UserSettings(javdb_cookie="ui_cookie"),
        ):
            from app.main import _merge_ui_cookie

            _merge_ui_cookie(env_settings)
        assert env_settings.javdb_cookie == "ui_cookie"

    def test_merge_ui_cookie_empty_keeps_env(self) -> None:
        """UI cookie 为空时应保留环境变量中的 cookie。"""
        from app.config import Settings

        env_settings = Settings(
            user_agent="test",
            http_proxy=None,
            javdb_cookie="env_cookie",
            javdb_mirror="javdb565.com",
            max_extra_images=8,
            http_timeout=20,
            batch_timeout=120,
            serial_writes=False,
            lock_enabled=False,
            write_delay=0.0,
        )
        with patch(
            "app.main.load_user_settings",
            return_value=UserSettings(javdb_cookie=""),
        ):
            from app.main import _merge_ui_cookie

            _merge_ui_cookie(env_settings)
        assert env_settings.javdb_cookie == "env_cookie"

    def test_index_template_has_cookie_section(self, client: TestClient) -> None:
        """首页模板应包含 cookie 设置相关元素。"""
        resp = client.get("/")
        assert resp.status_code == 200
        html = resp.text
        assert "JavDB Cookie" in html
        assert "javdb_cookie" in html
        assert "nfSaveCookie" in html
        assert "nfToggleCookieSection" in html
