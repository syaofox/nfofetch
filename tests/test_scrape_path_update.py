from __future__ import annotations

import base64
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from app.main import app
from app.schemas import MovieMetadata, ScrapeResult
from app.services.settings_service import load_user_settings


class TestScrapePathUpdate:
    """刮削完成后，文件浏览器记住的路径（last_browse_path）应自动更新。"""

    @pytest.fixture
    def settings_path(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
        path = tmp_path / "settings.json"
        monkeypatch.setenv("NFOFETCH_SETTINGS_PATH", str(path))
        return path

    @pytest.fixture
    def browse_root(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
        root = tmp_path / "browse"
        root.mkdir()
        monkeypatch.setenv("NFOFETCH_BROWSE_ROOT", str(root))
        return root

    @pytest.fixture
    def video_file(self, browse_root: Path) -> Path:
        path = browse_root / "test_video.mp4"
        path.touch()
        return path

    @pytest.fixture
    def metadata_b64(self) -> str:
        metadata = MovieMetadata(
            title="Test Movie",
            number="TEST-123",
            source_url="https://javdb.com/v/test",
        )
        return base64.b64encode(metadata.model_dump_json().encode()).decode()

    def test_success_updates_settings_and_renders_script(
        self,
        settings_path: Path,
        browse_root: Path,
        video_file: Path,
        metadata_b64: str,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """成功后：settings 的 last_browse_path 应更新为 movie_dir，HTML 应包含更新 video_path 的内联脚本。"""
        new_dir = browse_root / "New_Dir_(TEST-123)"
        new_video = new_dir / "new_video.mp4"

        def mock_save(**kwargs: object) -> ScrapeResult:
            return ScrapeResult(
                success=True,
                movie_dir=str(new_dir),
                video_path=str(new_video),
            )

        monkeypatch.setattr("app.main.save_assets_for_existing_video", mock_save)

        client = TestClient(app)
        resp = client.post(
            "/scrape",
            data={
                "url": "https://javdb.com/v/test",
                "video_path": str(video_file),
                "metadata_b64": metadata_b64,
            },
        )

        assert resp.status_code == 200

        # 应包含更新 video_path 的内联脚本
        assert 'input.value = "' in resp.text
        assert str(new_video) in resp.text

        # settings 中的 last_browse_path 应更新为新目录
        settings = load_user_settings()
        assert settings.last_browse_path == str(new_dir)

    def test_failure_does_not_update_settings(
        self,
        settings_path: Path,
        browse_root: Path,
        video_file: Path,
        metadata_b64: str,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """失败时：settings 的 last_browse_path 不应更新，HTML 不应包含更新路径的脚本。"""

        def mock_fail(**kwargs: object) -> ScrapeResult:
            return ScrapeResult(success=False, message="模拟失败")

        monkeypatch.setattr("app.main.save_assets_for_existing_video", mock_fail)

        client = TestClient(app)
        resp = client.post(
            "/scrape",
            data={
                "url": "https://javdb.com/v/test",
                "video_path": str(video_file),
                "metadata_b64": metadata_b64,
            },
        )

        assert resp.status_code == 200
        assert "input.value" not in resp.text

        settings = load_user_settings()
        assert settings.last_browse_path == ""

    def test_no_rename_no_harm(
        self,
        settings_path: Path,
        browse_root: Path,
        video_file: Path,
        metadata_b64: str,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """路径未变时也一样更新 last_browse_path 和 video_path，不应报错。"""

        def mock_save(**kwargs: object) -> ScrapeResult:
            return ScrapeResult(
                success=True,
                movie_dir=str(browse_root),
                video_path=str(video_file),
            )

        monkeypatch.setattr("app.main.save_assets_for_existing_video", mock_save)

        client = TestClient(app)
        resp = client.post(
            "/scrape",
            data={
                "url": "https://javdb.com/v/test",
                "video_path": str(video_file),
                "metadata_b64": metadata_b64,
            },
        )

        assert resp.status_code == 200
        assert 'input.value = "' in resp.text
        assert str(video_file) in resp.text

        settings = load_user_settings()
        assert settings.last_browse_path == str(browse_root)
