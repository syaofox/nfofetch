from __future__ import annotations


from app.main import BASE_DIR, TEMPLATES_DIR
from app.schemas import MovieMetadata
from fastapi.templating import Jinja2Templates
from starlette.requests import Request

templates = Jinja2Templates(directory=str(TEMPLATES_DIR))

CSS_PATH = BASE_DIR / "static" / "css" / "style.css"
BASE_TEMPLATE_PATH = TEMPLATES_DIR / "base.html"


def _make_request() -> Request:
    scope = {
        "type": "http",
        "method": "GET",
        "path": "/",
        "headers": [],
        "query_string": b"",
    }
    return Request(scope)


class TestImageClickJsInBase:
    """验证 base.html 模板源码中包含图片点击 JS 逻辑。"""

    BASE_HTML = BASE_TEMPLATE_PATH.read_text()

    def test_click_delegation_on_body(self) -> None:
        """使用事件委托监听 document.body。"""
        assert 'document.body.addEventListener("click"' in self.BASE_HTML
        assert "e.target.closest" in self.BASE_HTML

    def test_thumb_target_selector(self) -> None:
        """JS 中引用 .nf-image-thumb 作为点击目标。"""
        assert ".nf-image-thumb" in self.BASE_HTML

    def test_option_parent_selector(self) -> None:
        """JS 中引用 .nf-image-option 作为父容器。"""
        assert ".nf-image-option" in self.BASE_HTML

    def test_single_click_sets_poster(self) -> None:
        """单击逻辑检出 poster_url radio。"""
        assert "posterRadio.checked = true" in self.BASE_HTML
        assert "input[name='poster_url']" in self.BASE_HTML

    def test_double_click_sets_fanart(self) -> None:
        """双击逻辑检出 fanart_url radio。"""
        assert "fanartRadio.checked = true" in self.BASE_HTML
        assert "input[name='fanart_url']" in self.BASE_HTML

    def test_timer_based_distinction(self) -> None:
        """使用 setTimeout/clearTimeout 区分单击和双击。"""
        assert "setTimeout" in self.BASE_HTML
        assert "clearTimeout" in self.BASE_HTML
        assert "_clickTimer" in self.BASE_HTML

    def test_iiife_wrapped(self) -> None:
        """JS 逻辑以 IIFE 包裹。"""
        assert "(function ()" in self.BASE_HTML
        assert "})();" in self.BASE_HTML

    def test_click_handler_comment(self) -> None:
        """包含描述性注释。"""
        assert "图片单击设 poster，双击设 fanart" in self.BASE_HTML


class TestImageThumbInPreview:
    """验证 scrape_preview.html 渲染出可点击的图片元素。"""

    def _render_preview(
        self,
        poster_candidates: list[str] | None = None,
        metadata: MovieMetadata | None = None,
        error: str | None = None,
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
                "error": error,
                "url": "https://example.com",
                "video_path": "/path/to/video.mp4",
            },
        )
        return bytes(resp.body).decode()

    def test_image_thumb_rendered(self) -> None:
        """有 poster_candidates 时渲染 .nf-image-thumb 图片。"""
        html = self._render_preview(
            poster_candidates=[
                "https://example.com/img1.jpg",
                "https://example.com/img2.jpg",
            ],
        )
        assert 'class="nf-image-thumb"' in html

    def test_multiple_images_in_grid(self) -> None:
        """多个 poster_candidates 都渲染为图片。"""
        candidates = [
            "https://example.com/a.jpg",
            "https://example.com/b.jpg",
            "https://example.com/c.jpg",
        ]
        html = self._render_preview(poster_candidates=candidates)
        for c in candidates:
            assert c in html
        assert html.count('class="nf-image-thumb"') == len(candidates)

    def test_no_images_when_empty(self) -> None:
        """无 poster_candidates 时不应渲染图片。"""
        html = self._render_preview(poster_candidates=[])
        assert 'class="nf-image-thumb"' not in html
        assert 'class="nf-image-grid"' not in html

    def test_image_has_alt_text(self) -> None:
        """每张图片都有 alt 文本。"""
        html = self._render_preview(
            poster_candidates=["https://example.com/img.jpg"],
        )
        assert 'alt="候选图片' in html

    def test_image_inside_image_option(self) -> None:
        """图片包含在 .nf-image-option 容器内。"""
        html = self._render_preview(
            poster_candidates=["https://example.com/img.jpg"],
        )
        assert 'class="nf-image-option"' in html
        # 图片在 option 内部
        assert html.index('class="nf-image-option"') < html.index(
            'class="nf-image-thumb"'
        )

    def test_error_no_image(self) -> None:
        """刮削失败时不渲染图片。"""
        html = self._render_preview(error="出错了")
        assert 'class="nf-image-thumb"' not in html
        assert "出错了" in html


class TestImageThumbCss:
    """验证 CSS 中图片的可点击样式。"""

    CSS = CSS_PATH.read_text()

    def test_cursor_pointer_on_thumb(self) -> None:
        """.nf-image-thumb 应有 cursor: pointer。"""
        lines = self.CSS.splitlines()
        in_block = False
        found = False
        for line in lines:
            stripped = line.strip()
            if stripped.startswith(".nf-image-thumb"):
                in_block = True
            elif in_block and stripped == "}":
                in_block = False
            elif in_block and "cursor:" in stripped:
                found = True
                break
        assert found, ".nf-image-thumb CSS 块中未找到 cursor 属性"
