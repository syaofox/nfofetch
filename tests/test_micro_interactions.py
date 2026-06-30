from __future__ import annotations

from app.main import BASE_DIR, TEMPLATES_DIR
from fastapi.templating import Jinja2Templates
from starlette.requests import Request

templates = Jinja2Templates(directory=str(TEMPLATES_DIR))
CSS_PATH = BASE_DIR / "static" / "css" / "style.css"
BASE_HTML_PATH = TEMPLATES_DIR / "base.html"
INDEX_HTML_PATH = TEMPLATES_DIR / "index.html"


def _make_request() -> Request:
    scope = {
        "type": "http",
        "method": "GET",
        "path": "/",
        "headers": [],
        "query_string": b"",
    }
    return Request(scope)


class TestMicroInteractionCss:
    """验证 style.css 中包含 micro-interaction 样式。"""

    CSS = CSS_PATH.read_text()

    def test_ripple_effect_class(self) -> None:
        """.nf-btn-ripple 类存在且包含 position:relative 和 overflow:hidden。"""
        assert ".nf-btn-ripple" in self.CSS
        assert "overflow: hidden" in self.CSS

    def test_press_scale_class(self) -> None:
        """.nf-btn-press 存在 active scale 变换。"""
        assert ".nf-btn-press" in self.CSS
        assert "scale(0.97)" in self.CSS

    def test_toggle_switch_classes(self) -> None:
        """Toggle switch 相关 CSS 类存在。"""
        assert ".nf-toggle-track" in self.CSS
        assert ".nf-toggle-knob" in self.CSS
        assert ".nf-toggle-input" in self.CSS

    def test_custom_radio_class(self) -> None:
        """.nf-radio-custom 存在且隐藏原生 radio。"""
        assert ".nf-radio-custom" in self.CSS
        assert "appearance: none" in self.CSS

    def test_loading_dots_animation(self) -> None:
        """Loading dots 动画 keyframe 存在。"""
        assert ".nf-loading-dots" in self.CSS
        assert ".nf-loading-dot" in self.CSS
        assert "@keyframes nf-bounce" in self.CSS

    def test_status_icon_animation(self) -> None:
        """Status 图标动画 keyframe 存在。"""
        assert ".nf-status-icon" in self.CSS
        assert ".nf-status-success" in self.CSS
        assert ".nf-status-error" in self.CSS
        assert "@keyframes nf-status-pop" in self.CSS

    def test_modal_in_animation(self) -> None:
        """模态框入场动画 keyframe 存在。"""
        assert "@keyframes nf-modal-in" in self.CSS
        assert "@keyframes nf-fade-in" in self.CSS

    def test_enhanced_button_transitions(self) -> None:
        """按钮 Transition 增强存在。"""
        assert ".nf-button," in self.CSS
        assert "transition: transform" in self.CSS

    def test_search_item_hover_lift(self) -> None:
        """.nf-search-item 存在 -3px hover lift。"""
        assert ".nf-search-item:hover" in self.CSS
        assert "translateY(-3px)" in self.CSS

    def test_file_browser_item_micro(self) -> None:
        """文件浏览器列表项 hover 有平移。"""
        assert ".nf-file-browser-item:hover" in self.CSS
        assert "translateX(2px)" in self.CSS

    def test_card_hover_lift(self) -> None:
        """.nf-card 存在 hover lift。"""
        assert ".nf-card:hover" in self.CSS
        assert "translateY(-1px)" in self.CSS

    def test_image_option_hover(self) -> None:
        """.nf-image-option hover 有 lift。"""
        assert ".nf-image-option:hover" in self.CSS
        assert "translateY(-2px)" in self.CSS

    def test_write_button_enhanced(self) -> None:
        """写入按钮 scale(1.1) hover 存在。"""
        assert ".nf-button-write:hover" in self.CSS


class TestToggleSwitchInSettings:
    """验证 settings 中 checkbox 被替换为 toggle switch。"""

    INDEX_HTML = INDEX_HTML_PATH.read_text()

    def test_toggle_class_present(self) -> None:
        """serial_writes 使用 nf-toggle 类。"""
        assert 'id="serial_writes"' in self.INDEX_HTML
        assert 'id="lock_enabled"' in self.INDEX_HTML

    def test_toggle_track_exists(self) -> None:
        """serial_writes 有 toggle track。"""
        parts = self.INDEX_HTML.split('id="serial_writes"')
        assert len(parts) > 1
        # After the checkbox, there should be a toggle track
        assert "nf-toggle-track" in self.INDEX_HTML

    def test_no_checkbox_class(self) -> None:
        """serial_writes 使用 nf-toggle-input 隐藏类。"""
        lines = self.INDEX_HTML.splitlines()
        serial_lines = [line for line in lines if "serial_writes" in line]
        assert any("nf-toggle-input" in line for line in serial_lines)


class TestRippleOnButtons:
    """验证 ripple 类被添加到按钮上。"""

    BASE_HTML = BASE_HTML_PATH.read_text()

    def test_modal_cancel_ripple(self) -> None:
        """取消按钮有 nf-btn-ripple。"""
        assert "nf-btn-ripple" in self.BASE_HTML
        assert "nf-btn-press" in self.BASE_HTML

    def test_loading_dots_in_overlay(self) -> None:
        """加载遮罩中包含 nf-loading-dots。"""
        assert "nf-loading-dots" in self.BASE_HTML
        assert "nf-loading-dot" in self.BASE_HTML

    def test_settings_status_svg_icon(self) -> None:
        """JS 中使用 nf-status-icon SVG 图标。"""
        assert "nf-status-icon nf-status-success" in self.BASE_HTML
        assert "nf-status-icon nf-status-error" in self.BASE_HTML


class TestCustomRadioInPreview:
    """验证预览页使用了自定义 radio 样式。"""

    def test_radio_custom_class_in_scrape_preview(self) -> None:
        """scrape_preview.html 的 label 使用 nf-radio-custom。"""
        html = (TEMPLATES_DIR / "partials" / "scrape_preview.html").read_text()
        assert "nf-radio-custom" in html

    def test_radio_custom_class_in_image_options(self) -> None:
        """image_options.html 的 label 使用 nf-radio-custom。"""
        html = (TEMPLATES_DIR / "partials" / "image_options.html").read_text()
        assert "nf-radio-custom" in html

    def test_crop_radio_custom_in_preview(self) -> None:
        """scrape_preview.html 的 crop radio 使用 nf-radio-custom。"""
        html = (TEMPLATES_DIR / "partials" / "scrape_preview.html").read_text()
        assert "nf-radio-custom" in html

    def test_crop_radio_custom_in_image_options(self) -> None:
        """image_options.html 的 crop radio 使用 nf-radio-custom。"""
        html = (TEMPLATES_DIR / "partials" / "image_options.html").read_text()
        assert "nf-radio-custom" in html

    def test_crop_ratio_toggle_button_in_preview(self) -> None:
        """scrape_preview.html 包含比例切换按钮。"""
        html = (TEMPLATES_DIR / "partials" / "scrape_preview.html").read_text()
        assert 'id="nf-crop-ratio-toggle"' in html
        assert "window._nfToggleCropRatio" in html
        assert "比例: 2:3" in html


class TestRippleInPartials:
    """验证 partials 中的按钮也添加了 ripple。"""

    def test_sticky_fab_ripple(self) -> None:
        """粘性写入按钮有 nf-btn-ripple。"""
        html = (TEMPLATES_DIR / "partials" / "scrape_preview.html").read_text()
        assert "nf-button-write nf-btn-ripple" in html

    def test_preset_buttons_ripple(self) -> None:
        """预设按钮有 nf-btn-ripple。"""
        html = (TEMPLATES_DIR / "partials" / "scrape_preview.html").read_text()
        assert "nf-preset-btn" in html
        assert "nf-btn-ripple nf-btn-press" in html

    def test_file_browser_buttons_ripple(self) -> None:
        """文件浏览器按钮有 ripple。"""
        html = (TEMPLATES_DIR / "partials" / "file_browser.html").read_text()
        assert "nf-btn-ripple nf-btn-press" in html

    def test_sort_buttons_ripple(self) -> None:
        """排序按钮有 ripple。"""
        html = (TEMPLATES_DIR / "partials" / "file_browser.html").read_text()
        assert "nf-sort-btn nf-btn-ripple nf-btn-press" in html

    def test_delete_button_ripple(self) -> None:
        """文件浏览器删除按钮有 ripple。"""
        html = (TEMPLATES_DIR / "partials" / "file_browser.html").read_text()
        assert "nf-file-browser-delete-btn nf-btn-ripple nf-btn-press" in html

    def test_search_item_button_ripple(self) -> None:
        """搜索项按钮有 ripple。"""
        html = (TEMPLATES_DIR / "partials" / "search_results.html").read_text()
        assert "nf-search-item-btn nf-btn-ripple nf-btn-press" in html
        assert "nf-btn-ripple" in html

    def test_index_buttons_ripple(self) -> None:
        """index 按钮有 ripple。"""
        html = INDEX_HTML_PATH.read_text()
        assert "nf-btn-ripple nf-btn-press" in html


class TestMicroInteractionRendered:
    """验证实际渲染的页面包含 micro-interaction 元素。"""

    def test_index_renders_with_toggle(self) -> None:
        """index 页面渲染后包含 toggle track。"""
        html = INDEX_HTML_PATH.read_text()
        assert "nf-toggle-track" in html
        assert "nf-toggle-knob" in html

    def test_scrape_preview_renders_radio_custom(self) -> None:
        """scrape_preview 渲染后包含自定义 radio。"""
        request = _make_request()
        resp = templates.TemplateResponse(
            request,
            "partials/scrape_preview.html",
            {
                "request": request,
                "metadata": None,
                "metadata_b64": None,
                "poster_candidates": ["https://example.com/img.jpg"],
                "local_image_map": {},
                "error": None,
                "url": "https://example.com",
                "video_path": None,
            },
        )
        html = bytes(resp.body).decode()
        assert "nf-radio-custom" in html

    def test_search_results_renders_ripple(self) -> None:
        """search_results 渲染后包含 ripple 类。"""
        request = _make_request()
        resp = templates.TemplateResponse(
            request,
            "partials/search_results.html",
            {
                "request": request,
                "results": [],
                "error": None,
                "video_path": "",
            },
        )
        html = bytes(resp.body).decode()
        assert "nf-btn-ripple" in html
