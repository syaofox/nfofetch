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

    def test_save_serial_writes_and_lock(self, client: TestClient) -> None:
        saved: dict[str, Any] = {}
        mock_user = UserSettings()

        def _mock_save(settings: Any) -> None:
            saved["serial_writes"] = settings.serial_writes
            saved["lock_enabled"] = settings.lock_enabled
            saved["write_delay"] = settings.write_delay
            saved["max_extra_images"] = settings.max_extra_images

        with patch(
            "app.main.load_user_settings",
            return_value=mock_user,
        ):
            with patch("app.main.save_user_settings", side_effect=_mock_save):
                resp = client.post(
                    "/api/settings",
                    json={
                        "serial_writes": True,
                        "lock_enabled": True,
                        "write_delay": 0.5,
                        "max_extra_images": 16,
                    },
                )
        assert resp.status_code == 200
        assert saved.get("serial_writes") is True
        assert saved.get("lock_enabled") is True
        assert saved.get("write_delay") == 0.5
        assert saved.get("max_extra_images") == 16

    def test_save_jav321_cookie_via_api(self, client: TestClient) -> None:
        saved: dict[str, Any] = {}
        mock_user = UserSettings()

        def _mock_save(settings: Any) -> None:
            saved["jav321_cookie"] = settings.jav321_cookie

        with patch(
            "app.main.load_user_settings",
            return_value=mock_user,
        ):
            with patch("app.main.save_user_settings", side_effect=_mock_save):
                resp = client.post(
                    "/api/settings",
                    json={"jav321_cookie": "test321_cookie_value"},
                )
        assert resp.status_code == 200
        assert resp.json() == {"ok": True}
        assert saved.get("jav321_cookie") == "test321_cookie_value"

    def test_merge_ui_settings_overrides_env(self) -> None:
        """_merge_ui_settings 应使用 UI 设置覆盖 env。"""
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
            return_value=UserSettings(
                javdb_cookie="ui_cookie",
                jav321_cookie="ui_jav321_cookie",
                serial_writes=True,
                lock_enabled=True,
                write_delay=0.5,
                max_extra_images=16,
            ),
        ):
            from app.main import _merge_ui_settings

            merged = _merge_ui_settings(env_settings)
        assert merged.javdb_cookie == "ui_cookie"
        assert merged.jav321_cookie == "ui_jav321_cookie"
        assert merged.serial_writes is True
        assert merged.lock_enabled is True
        assert merged.write_delay == 0.5
        assert merged.max_extra_images == 16
        # 原始 settings 不受影响
        assert env_settings.javdb_cookie == "env_cookie"

    def test_merge_ui_settings_none_keeps_env(self) -> None:
        """UI 设置值为 None 时应保留环境变量。"""
        from app.config import Settings

        env_settings = Settings(
            user_agent="test",
            http_proxy=None,
            javdb_cookie="env_cookie",
            javdb_mirror="javdb565.com",
            max_extra_images=8,
            http_timeout=20,
            batch_timeout=120,
            serial_writes=True,
            lock_enabled=True,
            write_delay=0.0,
        )
        with patch(
            "app.main.load_user_settings",
            return_value=UserSettings(
                javdb_cookie="",
                jav321_cookie="",
                serial_writes=None,
                lock_enabled=None,
                write_delay=None,
                max_extra_images=None,
            ),
        ):
            from app.main import _merge_ui_settings

            merged = _merge_ui_settings(env_settings)
        assert merged.javdb_cookie == "env_cookie"
        assert merged.jav321_cookie is None
        assert merged.serial_writes is True
        assert merged.lock_enabled is True
        assert merged.write_delay == 0.0
        assert merged.max_extra_images == 8
        # 原始 settings 不受影响
        assert env_settings.javdb_cookie == "env_cookie"

    def test_merge_enabled_scrapers_overrides_env(self) -> None:
        """enabled_scrapers 列表应覆盖环境变量。"""
        from app.config import Settings

        env_settings = Settings(
            user_agent="test",
            http_proxy=None,
            javdb_cookie=None,
            enabled_scrapers={"javdb"},
        )
        with patch(
            "app.main.load_user_settings",
            return_value=UserSettings(
                enabled_scrapers=["javdb", "jav321", "javhoo"],
            ),
        ):
            from app.main import _merge_ui_settings

            merged = _merge_ui_settings(env_settings)
        assert merged.enabled_scrapers == {"javdb", "jav321", "javhoo"}
        # 原始 settings 不受影响
        assert env_settings.enabled_scrapers == {"javdb"}

    def test_merge_enabled_scrapers_none_keeps_env(self) -> None:
        """enabled_scrapers 为 None 时应保留环境变量。"""
        from app.config import Settings

        env_settings = Settings(
            user_agent="test",
            http_proxy=None,
            javdb_cookie=None,
            enabled_scrapers={"javdb"},
        )
        with patch(
            "app.main.load_user_settings",
            return_value=UserSettings(enabled_scrapers=None),
        ):
            from app.main import _merge_ui_settings

            merged = _merge_ui_settings(env_settings)
        assert merged.enabled_scrapers == {"javdb"}
        assert env_settings.enabled_scrapers == {"javdb"}

    def test_merge_ui_settings_returns_new_instance(self) -> None:
        """_merge_ui_settings 应返回新实例，原始 settings 不受影响。"""
        from app.config import Settings

        env_settings = Settings(
            user_agent="test",
            http_proxy=None,
            javdb_cookie="env_cookie",
            javdb_mirror="javdb565.com",
            max_extra_images=8,
            http_timeout=20,
            batch_timeout=120,
            serial_writes=True,
            lock_enabled=False,
            write_delay=0.0,
        )
        with patch(
            "app.main.load_user_settings",
            return_value=UserSettings(
                javdb_cookie="ui_cookie",
                serial_writes=False,
                lock_enabled=True,
            ),
        ):
            from app.main import _merge_ui_settings

            merged = _merge_ui_settings(env_settings)
        # 返回新实例
        assert merged is not env_settings
        # 新实例包含 UI 覆盖值
        assert merged.javdb_cookie == "ui_cookie"
        assert merged.serial_writes is False
        assert merged.lock_enabled is True
        # 原始实例保持不变
        assert env_settings.javdb_cookie == "env_cookie"
        assert env_settings.serial_writes is True
        assert env_settings.lock_enabled is False

    def test_merge_ui_settings_exception_returns_original(self) -> None:
        """_merge_ui_settings 在异常时应返回原始 settings。"""
        from app.config import Settings

        env_settings = Settings(
            user_agent="test",
            http_proxy=None,
            javdb_cookie=None,
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
            side_effect=RuntimeError("模拟加载失败"),
        ):
            from app.main import _merge_ui_settings

            merged = _merge_ui_settings(env_settings)
        assert merged is env_settings

    def test_create_scrape_task_rejects_when_queue_full(
        self, client: TestClient
    ) -> None:
        """队列满时应返回 503。"""
        from app.main import MAX_SCRAPE_TASKS

        fake_tasks: dict[str, dict[str, object]] = {}
        now = 1000.0
        for i in range(MAX_SCRAPE_TASKS):
            fake_tasks[f"active_{i}"] = {
                "phase": "scraping",
                "current": 0,
                "total": 0,
                "detail": "测试任务",
                "done": False,
                "error": None,
                "created_at": now,
            }
        with patch.dict(
            "app.main.scrape_tasks",
            fake_tasks,  # type: ignore[arg-type]
            clear=True,
        ):
            resp = client.post("/api/scrape-task")
        assert resp.status_code == 503

    def test_index_template_has_settings_modal(self, client: TestClient) -> None:
        """首页模板应包含 cookie 设置相关元素。"""
        resp = client.get("/")
        assert resp.status_code == 200
        html = resp.text
        assert "javdb_cookie" in html
        assert "jav321_cookie" in html
        assert "serial_writes" in html
        assert "lock_enabled" in html
        assert "write_delay" in html
        assert "max_extra_images" in html
        assert "delete_orphan_extrafanart" in html
        assert "nfSaveSettings" in html
        assert "nfOpenSettingsModal" in html
