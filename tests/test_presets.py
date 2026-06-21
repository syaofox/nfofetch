from __future__ import annotations

from typing import Any, Generator
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.schemas import Preset


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
