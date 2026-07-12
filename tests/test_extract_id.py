from __future__ import annotations

from app.main import BASE_DIR, TEMPLATES_DIR

CSS_PATH = BASE_DIR / "static" / "css" / "style.css"
BASE_HTML_PATH = TEMPLATES_DIR / "base.html"
INDEX_HTML_PATH = TEMPLATES_DIR / "index.html"


class TestExtractIdJs:
    """验证 nfExtractId 的 JS 逻辑存在且正确。"""

    HTML = BASE_HTML_PATH.read_text()

    def test_function_exists(self) -> None:
        """nfExtractId 函数存在（含可选参数 text）。"""
        assert "window.nfExtractId = function" in self.HTML

    def test_heyzo_regex_exists(self) -> None:
        """HEYZO 专用正则在 JS 中。"""
        assert "reHeyzo" in self.HTML

    def test_heyzo_pattern(self) -> None:
        """HEYZO 正则匹配 HEYZO-0282 格式（固定4位，保留前导零）。"""
        assert r"(HEYZO)[-_]?(\d{4})" in self.HTML

    def test_heyzo_output_preserves_raw_digits(self) -> None:
        """HEYZO 番号输出直接用 m[2]（原始数字字符串），不用 parseInt。"""
        assert 'm[1].toUpperCase() + "-" + m[2]' in self.HTML

    def test_cleaned_text_removes_heyzo(self) -> None:
        """cleanedText 从源文本移除 HEYZO 模式。"""
        assert "cleanedText" in self.HTML

    def test_standard_regex_uses_cleaned_text(self) -> None:
        """标准正则对 cleanedText 匹配，避免 HEYZO/PT 误匹配。"""
        assert "reStd.exec(cleanedText)" in self.HTML

    def test_pt_regex_exists(self) -> None:
        """PT 专用正则在 JS 中。"""
        assert "rePT" in self.HTML

    def test_pt_pattern(self) -> None:
        """PT 正则匹配 PT-12 格式（可变位数，不补0）。"""
        assert r"(PT)[-_]?(\d+)" in self.HTML

    def test_pt_output_preserves_raw_digits(self) -> None:
        """PT 番号输出直接用 m[2]（原始数字字符串），不补0。"""
        assert 'm[1].toUpperCase() + "-" + m[2]' in self.HTML

    def test_pt_removed_from_cleaned_text(self) -> None:
        """PT 模式从 cleanedText 中移除。"""
        assert "PT[-_]?\\d+" in self.HTML

    def test_standard_id_regex(self) -> None:
        """匹配标准番号正则在 JS 中。"""
        assert "([A-Za-z]{2,6})[-_]?(\\d{2,8})" in self.HTML

    def test_numeric_id_regex_hyphen(self) -> None:
        """匹配纯数字番号连字符版。"""
        assert "(\\d{4,})\\s*-\\s*(\\d{2,6})" in self.HTML

    def test_numeric_id_regex_underscore(self) -> None:
        """匹配纯数字番号下划线版（与连字符版不同）。"""
        assert "(\\d{4,})\\s*_\\s*(\\d{2,6})" in self.HTML

    def test_n_prefix_id_regex(self) -> None:
        """匹配 n 前缀番号 n0179 / N0179。"""
        assert "/n(\\d{2,8})/gi" in self.HTML

    def test_n_prefix_output_format(self) -> None:
        """n 前缀番号转大写 N + 原样数字。"""
        assert 'ids.push("N" + m[1])' in self.HTML

    def test_multi_match_popup_manual(self) -> None:
        """手动模式多匹配时弹出选择窗口。"""
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

    def test_auto_mode_param(self) -> None:
        """自动模式通过 text 参数传入。"""
        assert "var isAuto = (text !== undefined)" in self.HTML

    def test_auto_mode_source_text(self) -> None:
        """自动模式使用传入的 text，手动模式使用 input.value。"""
        assert "var sourceText = isAuto ? text : input.value" in self.HTML

    def test_multi_match_popup_in_both_modes(self) -> None:
        """多匹配时无论模式都弹出选择窗口（无自动取第一条的短路逻辑）。"""
        assert "多匹配时取第一个" not in self.HTML

    def test_auto_mode_no_match_empty_fallback(self) -> None:
        """自动模式无匹配且 input 为空时才回退填入原始文本。"""
        assert "isAuto && !input.value" in self.HTML


class TestAutoExtractToggle:
    """验证 index.html 中自动提取番号的开关。"""

    HTML = INDEX_HTML_PATH.read_text()

    def test_toggle_exists(self) -> None:
        """auto_extract_id 开关存在。"""
        assert 'id="auto_extract_id"' in self.HTML

    def test_toggle_uses_nf_toggle_class(self) -> None:
        """开关使用 .nf-toggle 样式。"""
        assert 'class="nf-toggle" for="auto_extract_id"' in self.HTML

    def test_toggle_label(self) -> None:
        """开关有中文描述。"""
        assert "选择文件后自动从路径提取番号" in self.HTML

    def test_manual_button_still_exists(self) -> None:
        """手动提取番号按钮仍然保留。"""
        assert "window.nfExtractId()" in self.HTML
        assert "提取番号" in self.HTML


class TestAutoExtractJs:
    """验证 base.html 中自动提取番号的 JS 逻辑。"""

    HTML = BASE_HTML_PATH.read_text()

    def test_auto_extract_key_defined(self) -> None:
        """AUTO_EXTRACT_KEY 常量存在。"""
        assert "AUTO_EXTRACT_KEY" in self.HTML
        assert "nfofetch_auto_extract" in self.HTML

    def test_get_auto_extract_exists(self) -> None:
        """nfGetAutoExtract 函数存在。"""
        assert "window.nfGetAutoExtract = function" in self.HTML

    def test_get_auto_extract_uses_localstorage(self) -> None:
        """nfGetAutoExtract 先读取 localStorage。"""
        assert "localStorage.getItem(AUTO_EXTRACT_KEY)" in self.HTML

    def test_get_auto_extract_dom_fallback(self) -> None:
        """nfGetAutoExtract 在 localStorage 不可用时回退到 DOM checkbox。"""
        assert 'document.getElementById("auto_extract_id")' in self.HTML

    def test_set_auto_extract_exists(self) -> None:
        """nfSetAutoExtract 函数存在。"""
        assert "window.nfSetAutoExtract = function" in self.HTML

    def test_set_auto_extract_writes_localstorage(self) -> None:
        """nfSetAutoExtract 写入 localStorage。"""
        assert "localStorage.setItem(AUTO_EXTRACT_KEY" in self.HTML

    def test_select_file_calls_auto_extract(self) -> None:
        """nfSelectFile 在自动模式下调用 nfExtractId(filename)。"""
        assert "window.nfGetAutoExtract()" in self.HTML
        assert "window.nfExtractId(filename)" in self.HTML

    def test_restore_on_load(self) -> None:
        """页面加载时恢复开关状态。"""
        assert "restoreAutoExtract" in self.HTML
        assert "cb.checked = window.nfGetAutoExtract()" in self.HTML

    def test_change_listener_persists(self) -> None:
        """开关变化时保存状态。"""
        assert 'e.target.id === "auto_extract_id"' in self.HTML
        assert "window.nfSetAutoExtract(e.target.checked)" in self.HTML


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
