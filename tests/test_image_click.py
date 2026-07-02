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

    def test_single_click_triggers_poster_selected(self) -> None:
        """单击设 poster 后调用 _nfOnPosterSelected 更新封面预览。"""
        assert "posterRadio.checked = true;" in self.BASE_HTML
        assert "window._nfOnPosterSelected()" in self.BASE_HTML


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
                "local_image_map": {},
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
        # 只统计 <script> 之前的 HTML（排除 JS 字符串字面量）
        before_script = html.split("<script")[0]
        assert before_script.count('class="nf-image-thumb"') == len(candidates)

    def test_no_images_when_empty(self) -> None:
        """无 poster_candidates 时不应渲染图片。"""
        html = self._render_preview(poster_candidates=[])
        before_script = html.split("<script")[0]
        assert 'class="nf-image-thumb"' not in before_script

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

    def test_cover_sync_script_exists(self) -> None:
        """包含封面预览同步到选中 poster 的脚本。"""
        html = self._render_preview(
            poster_candidates=["https://example.com/img1.jpg"],
        )
        assert "封面预览同步到当前选中的 poster" in html
        assert "window._nfDisplayUrl(poster)" in html
        assert "coverImg.src" in html


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


class TestDataDisplayUrl:
    """验证 data-display-url 属性的渲染正确性。"""

    def _render_preview(
        self,
        poster_candidates: list[str] | None = None,
        local_image_map: dict[str, str] | None = None,
        metadata: MovieMetadata | None = None,
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
                "local_image_map": local_image_map or {},
                "error": None,
                "url": "https://example.com",
                "video_path": "/path/to/video.mp4",
            },
        )
        return bytes(resp.body).decode()

    def test_local_image_has_data_display_url(self) -> None:
        """本地图片的 data-display-url 应为 /api/local-image?path= 形式的 serve URL。"""
        local_path = "/mnt/media/movie/thumb.jpg"
        serve_url = "/api/local-image?path=%2Fmnt%2Fmedia%2Fmovie%2Fthumb.jpg"
        html = self._render_preview(
            poster_candidates=[serve_url],
            local_image_map={serve_url: local_path},
        )
        before_script = html.split("<script")[0]
        assert f'data-display-url="{serve_url}"' in before_script
        assert f'value="{local_path}"' in before_script

    def test_remote_image_has_data_display_url(self) -> None:
        """远程图片的 data-display-url 应与 value 相同（URL 本身）。"""
        url = "https://example.com/poster.jpg"
        html = self._render_preview(
            poster_candidates=[url],
        )
        before_script = html.split("<script")[0]
        assert f'data-display-url="{url}"' in before_script
        assert f'value="{url}"' in before_script

    def test_data_display_url_on_poster_and_fanart(self) -> None:
        """poster 和 fanart 两个 radio 都有 data-display-url。"""
        url = "https://example.com/poster.jpg"
        html = self._render_preview(
            poster_candidates=[url],
        )
        before_script = html.split("<script")[0]
        assert before_script.count("data-display-url") == 2

    def test_data_display_url_for_local_not_checked(self) -> None:
        """本地图片的 poster radio 默认不应 checked。"""
        serve_url = "/api/local-image?path=%2Fmnt%2Ftest.jpg"
        html = self._render_preview(
            poster_candidates=[serve_url],
            local_image_map={serve_url: "/mnt/test.jpg"},
        )
        before_script = html.split("<script")[0]
        poster_input_start = before_script.index(
            'name="poster_url" value="/mnt/test.jpg"'
        )
        poster_input = before_script[poster_input_start:]
        assert "checked" not in poster_input[:80]


class TestBaseTemplateDisplayUrl:
    """验证 base.html 中 _nfDisplayUrl 相关 JS 逻辑。"""

    BASE_HTML = BASE_TEMPLATE_PATH.read_text()

    def test_nf_display_url_function_exists(self) -> None:
        """_nfDisplayUrl 辅助函数存在。"""
        assert "function _nfDisplayUrl" in self.BASE_HTML

    def test_nf_display_url_uses_data_display_url(self) -> None:
        """_nfDisplayUrl 优先读取 data-display-url。"""
        assert "getAttribute('data-display-url')" in self.BASE_HTML

    def test_nf_display_url_falls_back_to_value(self) -> None:
        """_nfDisplayUrl 没有 data-display-url 时回退到 value。"""
        assert "|| radio.value" in self.BASE_HTML

    def test_update_direction_preview_uses_display_url(self) -> None:
        """方向裁切预览使用 _nfDisplayUrl 获取图片 URL。"""
        assert "var imgUrl = _nfDisplayUrl(poster);" in self.BASE_HTML

    def test_switch_crop_tab_uses_display_url(self) -> None:
        """切到精确裁切时使用 _nfDisplayUrl 获取图片 URL。"""
        assert "var imgUrl = _nfDisplayUrl(poster);" in self.BASE_HTML

    def test_page_load_sync_uses_display_url(self) -> None:
        """页面加载时封面预览同步使用 _nfDisplayUrl。"""
        assert "coverImg.src = _nfDisplayUrl(poster);" in self.BASE_HTML

    def test_switch_to_direction_does_not_clear_precise_data(self) -> None:
        """切到方向裁切 tab 时不应清除精确裁切数据。"""
        # 提取 nfSwitchCropTab 函数体检查
        idx = self.BASE_HTML.index("window.nfSwitchCropTab = function")
        end = self.BASE_HTML.index("};\n\n", idx) + 3
        switch_fn = self.BASE_HTML[idx:end]
        assert "crop_x" not in switch_fn
        assert "crop_y" not in switch_fn
        assert "crop_w" not in switch_fn
        assert "crop_h" not in switch_fn
        assert "custom_poster_path" not in switch_fn

    def test_rotatable_enabled_in_cropper_opts(self) -> None:
        """Cropper.js 启用了 rotatable: true。"""
        assert "rotatable: true" in self.BASE_HTML
        assert "rotatable: false" not in self.BASE_HTML

    def test_nf_rotate_image_function_exists(self) -> None:
        """_nfRotateImage 全局函数存在。"""
        assert "window._nfRotateImage = function" in self.BASE_HTML

    def test_nf_fit_canvas_after_rotate_exists(self) -> None:
        """_nfFitCanvasAfterRotate 辅助函数存在。"""
        assert "function _nfFitCanvasAfterRotate" in self.BASE_HTML

    def test_nf_rotate_image_calls_fit_canvas(self) -> None:
        """_nfRotateImage 调用 _nfFitCanvasAfterRotate。"""
        assert "_nfFitCanvasAfterRotate()" in self.BASE_HTML

    def test_fit_canvas_uses_get_image_data(self) -> None:
        """_nfFitCanvasAfterRotate 使用 getImageData 获取原始尺寸。"""
        assert "getImageData()" in self.BASE_HTML
        assert "naturalHeight" in self.BASE_HTML
        assert "naturalWidth" in self.BASE_HTML

    def test_fit_canvas_uses_get_container_data(self) -> None:
        """_nfFitCanvasAfterRotate 使用 getContainerData 获取容器尺寸。"""
        assert "getContainerData()" in self.BASE_HTML

    def test_fit_canvas_uses_set_canvas_data(self) -> None:
        """_nfFitCanvasAfterRotate 使用 setCanvasData 调整画布。"""
        assert "setCanvasData" in self.BASE_HTML

    def test_fit_canvas_detects_swapped_aspect(self) -> None:
        """_nfFitCanvasAfterRotate 检测 90/270 度旋转以交换宽高比。"""
        assert "swapped" in self.BASE_HTML
        assert "angle === 90" in self.BASE_HTML

    def test_nf_confirm_crop_clears_rotation(self) -> None:
        """nfConfirmCrop 将旋转角度清零（前端已上传裁切结果）。"""
        assert 'document.getElementById("crop_rotation").value' in self.BASE_HTML

    def test_crop_ratio_mode_variable_exists(self) -> None:
        """_nfCropRatioMode 从 localStorage 读取，默认 cover。"""
        assert "localStorage.getItem('nf_crop_ratio_mode') || 'cover'" in self.BASE_HTML
        assert "localStorage.setItem('nf_crop_ratio_mode'" in self.BASE_HTML

    def test_crop_ratio_modes_three_options(self) -> None:
        """_nfToggleCropRatio 在三个模式间循环：2:3 → 3:4 → 自由。"""
        assert "['cover', '3_4', 'free']" in self.BASE_HTML

    def test_toggle_crop_ratio_function_exists(self) -> None:
        """_nfToggleCropRatio 全局函数存在。"""
        assert "window._nfToggleCropRatio = function" in self.BASE_HTML

    def test_dynamic_aspect_ratio_in_cropper_opts(self) -> None:
        """_cropperOpts 使用 isCover/is3_4 动态选择 aspectRatio。"""
        assert (
            "aspectRatio: isCover ? (2 / 3) : (is3_4 ? (3 / 4) : NaN)" in self.BASE_HTML
        )

    def test_cover_mode_small_default_crop_box(self) -> None:
        """cover 模式默认为小裁剪框（高最多 300px）。"""
        assert "h = Math.min(img.naturalHeight, 300)" in self.BASE_HTML

    def test_3_4_mode_small_default_crop_box(self) -> None:
        """3:4 模式默认为小裁剪框（高最多 200px）。"""
        assert "h = Math.min(img.naturalHeight, 200)" in self.BASE_HTML

    def test_free_mode_small_default_crop_box(self) -> None:
        """free 模式默认为 200x200 小裁剪框。"""
        assert "w = 200; h = 200;" in self.BASE_HTML

    def test_crop_box_centered(self) -> None:
        """小裁剪框居中放置。"""
        assert "x = Math.round((img.naturalWidth - w) / 2);" in self.BASE_HTML
        assert "y = Math.round((img.naturalHeight - h) / 2);" in self.BASE_HTML

    def test_toggle_labels_map_exists(self) -> None:
        """_nfToggleCropRatio 中有 labels 映射表存储三种文字。"""
        assert "labels[_nfCropRatioMode]" in self.BASE_HTML

    def test_toggle_button_text_2_3(self) -> None:
        """_nfToggleCropRatio 中按钮文字包含 2:3。"""
        assert "'比例: 2:3'" in self.BASE_HTML

    def test_toggle_button_text_3_4(self) -> None:
        """_nfToggleCropRatio 中按钮文字包含 3:4。"""
        assert "'比例: 3:4'" in self.BASE_HTML

    def test_toggle_button_text_free(self) -> None:
        """_nfToggleCropRatio 中切换到自由时按钮文字。"""
        assert "'比例: 自由'" in self.BASE_HTML

    def test_init_ratio_button_on_image_load(self) -> None:
        """_loadImageToCropper 中载入图片后同步按钮文字。"""
        assert (
            "btn.textContent = labels[_nfCropRatioMode] || '比例: 2:3'"
            in self.BASE_HTML
        )

    def test_confirm_crop_uploads_blob(self) -> None:
        """nfConfirmCrop 上传 getCroppedCanvas Blob 到 /api/upload-image。"""
        assert "var fullCanvas = _nfCropper.getCroppedCanvas();" in self.BASE_HTML
        assert "fullCanvas.toBlob" in self.BASE_HTML
        assert 'fetch("/api/upload-image"' in self.BASE_HTML
        assert (
            'document.getElementById("custom_poster_path").value = data.path'
            in self.BASE_HTML
        )
        assert 'document.getElementById("crop_x").value' in self.BASE_HTML

    def test_confirm_crop_still_uses_get_cropped_canvas_for_preview(self) -> None:
        """nfConfirmCrop 仍使用 getCroppedCanvas 生成前端预览。"""
        assert (
            "var coverCanvas = _nfCropper.getCroppedCanvas({ maxWidth: 320, maxHeight: 480 });"
            in self.BASE_HTML
        )
        assert (
            "var thumbCanvas = _nfCropper.getCroppedCanvas({ maxWidth: 80, maxHeight: 80 });"
            in self.BASE_HTML
        )

    def test_maximize_crop_box_function_exists(self) -> None:
        """_nfMaximizeCropBox 全局函数存在。"""
        assert "window._nfMaximizeCropBox = function" in self.BASE_HTML

    def test_maximize_uses_canvas_data(self) -> None:
        """_nfMaximizeCropBox 使用 getCanvasData/setCropBoxData。"""
        assert "_nfCropper.getCanvasData()" in self.BASE_HTML
        assert "_nfCropper.setCropBoxData({" in self.BASE_HTML

    def test_maximize_sets_crop_box_to_full_canvas(self) -> None:
        """裁剪框设为 canvas 的完整区域。"""
        assert "canvasData.left" in self.BASE_HTML
        assert "canvasData.top" in self.BASE_HTML
        assert "canvasData.width" in self.BASE_HTML
        assert "canvasData.height" in self.BASE_HTML

    def test_dblclick_listener_registered(self) -> None:
        """通过事件委托在 document.body 上注册双击监听。"""
        assert "document.body.addEventListener('dblclick'" in self.BASE_HTML
        assert "window._nfMaximizeCropBox()" in self.BASE_HTML

    def test_dblclick_checks_modal_visible(self) -> None:
        """双击事件中检查弹窗是否可见。"""
        assert "modal.style.display === 'none'" in self.BASE_HTML

    def test_dblclick_checks_dropzone_target(self) -> None:
        """双击事件中检查点击目标是否在裁剪区域。"""
        assert "e.target.closest('.nf-crop-dropzone')" in self.BASE_HTML

    def test_hint_text_mentions_dblclick(self) -> None:
        """提示文字说明双击最大化功能。"""
        assert "双击最大化裁剪框" in self.BASE_HTML

    def test_nf_on_poster_selected_function_exists(self) -> None:
        """_nfOnPosterSelected 全局函数存在。"""
        assert "window._nfOnPosterSelected = function" in self.BASE_HTML

    def test_nf_on_poster_selected_clears_crop_data(self) -> None:
        """_nfOnPosterSelected 清除精确裁切数据。"""
        assert 'document.getElementById("crop_x").value' in self.BASE_HTML
        assert 'document.getElementById("crop_y").value' in self.BASE_HTML
        assert 'document.getElementById("crop_w").value' in self.BASE_HTML
        assert 'document.getElementById("crop_h").value' in self.BASE_HTML
        assert 'document.getElementById("crop_rotation").value' in self.BASE_HTML
        assert 'document.getElementById("custom_poster_path").value' in self.BASE_HTML

    def test_nf_on_poster_selected_updates_preview(self) -> None:
        """_nfOnPosterSelected 调用 nfUpdateDirectionPreview 更新预览。"""
        assert "window.nfUpdateDirectionPreview" in self.BASE_HTML
