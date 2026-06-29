from __future__ import annotations

from starlette.requests import Request

from app.main import TEMPLATES_DIR
from app.schemas import MovieMetadata
from fastapi.templating import Jinja2Templates

templates = Jinja2Templates(directory=str(TEMPLATES_DIR))


def _make_request() -> Request:
    scope = {
        "type": "http",
        "method": "GET",
        "path": "/",
        "headers": [],
        "query_string": b"",
    }
    return Request(scope)


def _render(
    metadata: MovieMetadata | None = None,
    poster_candidates: list[str] | None = None,
    error: str | None = None,
    url: str = "https://example.com",
    video_path: str = "/path/to/video.mp4",
) -> str:
    request = _make_request()
    resp = templates.TemplateResponse(
        request,
        "partials/scrape_preview.html",
        {
            "request": request,
            "metadata": metadata,
            "metadata_b64": None,
            "poster_candidates": poster_candidates or [],
            "local_image_map": {},
            "error": error,
            "url": url,
            "video_path": video_path,
        },
    )
    return bytes(resp.body).decode()


class TestStickyFab:
    def test_sticky_fab_renders(self) -> None:
        """正常刮削预览包含粘性 FAB 按钮。"""
        html = _render()
        assert 'class="nf-sticky-fab"' in html
        assert 'id="write-button"' in html

    def test_form_attribute_on_button(self) -> None:
        """按钮通过 form 属性关联到 write-form。"""
        html = _render()
        assert 'form="write-form"' in html

    def test_svg_icon_present(self) -> None:
        """按钮包含 SVG 图标。"""
        html = _render()
        assert "<svg" in html
        assert "viewBox" in html

    def test_title_attribute(self) -> None:
        """按钮有 title 提示。"""
        html = _render()
        assert 'title="写入 NFO 与图片"' in html

    def test_no_button_when_error(self) -> None:
        """刮削失败时不应渲染粘性按钮。"""
        html = _render(error="something went wrong")
        assert 'class="nf-sticky-fab"' not in html
        assert 'id="write-button"' not in html

    def test_sticky_fab_with_metadata(
        self, sample_movie_metadata: MovieMetadata
    ) -> None:
        """有元数据时按钮正常渲染。"""
        html = _render(
            metadata=sample_movie_metadata,
            poster_candidates=[str(u) for u in sample_movie_metadata.posters],
        )
        assert 'class="nf-sticky-fab"' in html
        assert 'id="write-button"' in html
        assert 'form="write-form"' in html

    def test_sticky_fab_without_posters(self) -> None:
        """无图片候选人时按钮仍正常渲染。"""
        html = _render(video_path="/path/to/video.mp4")
        assert 'class="nf-sticky-fab"' in html
        assert 'id="write-button"' in html

    def test_fab_after_form_closing(self) -> None:
        """FAB 在 </form> 标签之后出现（在页面源码中）。"""
        html = _render()
        assert "</form>" in html
        assert html.index("</form>") < html.index("nf-sticky-fab")

    def test_minimal_context(self) -> None:
        """最简上下文（无 metadata, 无视频路径）也能渲染。"""
        request = _make_request()
        resp = templates.TemplateResponse(
            request,
            "partials/scrape_preview.html",
            {
                "request": request,
                "metadata": None,
                "metadata_b64": None,
                "poster_candidates": [],
                "error": None,
                "url": "https://example.com",
                "video_path": None,
            },
        )
        html = bytes(resp.body).decode()
        assert 'class="nf-sticky-fab"' in html
