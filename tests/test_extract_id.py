from __future__ import annotations

from app.main import BASE_DIR, TEMPLATES_DIR

CSS_PATH = BASE_DIR / "static" / "css" / "style.css"
BASE_HTML_PATH = TEMPLATES_DIR / "base.html"


class TestExtractIdJs:
    """验证 nfExtractId 的 JS 逻辑存在且正确。"""

    HTML = BASE_HTML_PATH.read_text()

    def test_function_exists(self) -> None:
        """nfExtractId 函数存在。"""
        assert "window.nfExtractId = function" in self.HTML

    def test_standard_id_regex(self) -> None:
        """匹配标准番号正则在 JS 中。"""
        assert "([A-Za-z]{2,6})[-_]?(\\d{2,8})" in self.HTML

    def test_numeric_id_regex(self) -> None:
        """匹配纯数字番号正则在 JS 中。"""
        assert "(\\d{4,})\\s*[-_]\\s*(\\d{2,6})" in self.HTML

    def test_multi_match_popup(self) -> None:
        """多匹配时弹出选择窗口。"""
        assert "nf-id-popup" in self.HTML
        assert "选择番号" in self.HTML

    def test_single_match_auto_fill(self) -> None:
        """单匹配时自动填入（不回显弹窗）。"""
        assert "ids.length === 1" in self.HTML

    def test_dedup_logic(self) -> None:
        """去重逻辑存在。"""
        assert "indexOf" in self.HTML
        assert "filter" in self.HTML

    def test_click_outside_closes(self) -> None:
        """点击外部关闭弹窗。"""
        assert "contains(e.target)" in self.HTML


class TestExtractIdCss:
    """验证提取番号弹窗的 CSS。"""

    CSS = CSS_PATH.read_text()

    def test_popup_class(self) -> None:
        """.nf-id-popup 存在。"""
        assert ".nf-id-popup" in self.CSS

    def test_popup_item_class(self) -> None:
        """.nf-id-popup-item 存在。"""
        assert ".nf-id-popup-item" in self.CSS

    def test_popup_close_class(self) -> None:
        """.nf-id-popup-close 存在。"""
        assert ".nf-id-popup-close" in self.CSS
