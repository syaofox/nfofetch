from __future__ import annotations

import logging
import shutil
import tempfile
from pathlib import Path

import httpx

from app.config import Settings
from app.retry import retry_request
from app.services.file_utils import _TEMP_PREFIX, _write_delay

logger = logging.getLogger(__name__)


_WHITE_THRESHOLD = 245


def _trim_white_borders(image_path: Path) -> None:
    """检测并裁掉图片四周的白边（RGB 各通道均接近 255 的区域）。

    将图片转换为灰度图，通过阈值二值化后使用 getbbox 定位内容区域。
    若检测不到内容区域（全白/全接近白色），或内容区域几乎覆盖整张图，则不裁切。
    """
    from PIL import Image

    img = Image.open(image_path)
    orig_size = img.size

    # 转换为灰度图
    gray = img.convert("L")
    # 白边区域（像素值 > 阈值）→ 0（黑），内容区域 → 255（白）
    bw = gray.point(lambda p: 0 if p > _WHITE_THRESHOLD else 255)
    bbox = bw.getbbox()

    if bbox is None:
        logger.warning("图片全白或全接近白色，跳过白边裁切: %s", image_path.name)
        return

    x1, y1, x2, y2 = bbox
    # 若内容区域覆盖 95% 以上像素，认为没有明显白边
    content_area = (x2 - x1) * (y2 - y1)
    if content_area >= orig_size[0] * orig_size[1] * 0.95:
        return

    cropped = img.crop((x1, y1, x2, y2))
    cropped.save(image_path, format=img.format)
    logger.info(
        "裁掉白边: %s -> %dx%d（原图 %dx%d，白边区域: 上%d 下%d 左%d 右%d）",
        image_path.name,
        cropped.width,
        cropped.height,
        orig_size[0],
        orig_size[1],
        y1,
        orig_size[1] - y2,
        x1,
        orig_size[0] - x2,
    )


def _crop_image_exact(image_path: Path, x: int, y: int, w: int, h: int) -> None:
    """按精确坐标裁切图片。(x, y, w, h) 相对于当前图片尺寸。"""
    from PIL import Image

    img = Image.open(image_path)
    orig = img.size
    if w <= 0 or h <= 0:
        logger.warning("裁切尺寸无效 (%dx%d)，跳过精确裁切", w, h)
        return
    cropped = img.crop((x, y, x + w, y + h))
    cropped.save(image_path, format=img.format)
    logger.info(
        "精确裁切: %s -> %dx%d（区域: %d,%d %dx%d，原图 %dx%d）",
        image_path.name,
        cropped.width,
        cropped.height,
        x,
        y,
        w,
        h,
        orig[0],
        orig[1],
    )


def _crop_image(image_path: Path, direction: str) -> None:
    """将图片按 2:3 竖版比例裁切（仅对非 none 方向生效），保留指定水平区域。

    始终保留原图全高，将宽度按 2:3 比例裁切，确保 direction 决定保留左/中/右区域。
    若原图宽度不足以达到 2:3，则保持原图不裁切。
    """
    if direction == "none":
        return
    from PIL import Image

    img = Image.open(image_path)
    w, h = img.size

    target_ratio = 2.0 / 3.0
    target_h = h
    target_w = int(target_h * target_ratio)

    if target_w > w:
        logger.warning(
            "图片宽度 %d 不足以裁切成 2:3（需要 %d），跳过裁切",
            w,
            target_w,
        )
        return

    if direction == "left":
        x = 0
    elif direction == "right":
        x = w - target_w
    else:
        x = (w - target_w) // 2

    y = 0
    cropped = img.crop((x, y, x + target_w, y + target_h))
    cropped.save(image_path, format=img.format)
    logger.info(
        "裁切 poster: %s -> %dx%d（direction=%s, 原图 %dx%d）",
        image_path.name,
        cropped.width,
        cropped.height,
        direction,
        w,
        h,
    )


def _download_to_temp(
    url: str, settings: Settings, http_timeout: int = 20
) -> Path | None:
    """下载图片到临时文件，返回临时路径（失败返回 None）。

    支持本地文件路径（以 / 开头且文件存在时直接复制）。
    """
    local_path = Path(url)
    if url.startswith("/") and local_path.is_file():
        tmp = tempfile.NamedTemporaryFile(
            suffix=local_path.suffix or ".tmp", prefix=_TEMP_PREFIX, delete=False
        )
        tmp_path = Path(tmp.name)
        tmp.close()
        shutil.copy2(str(local_path), str(tmp_path))
        return tmp_path

    try:
        client_kwargs: dict = {
            "headers": {"User-Agent": settings.user_agent},
            "timeout": http_timeout,
        }
        if settings.http_proxy:
            client_kwargs["proxies"] = {
                "http://": settings.http_proxy,
                "https://": settings.http_proxy,
            }

        tmp = tempfile.NamedTemporaryFile(
            suffix=".tmp", prefix=_TEMP_PREFIX, delete=False
        )
        tmp_path = Path(tmp.name)
        tmp.close()

        def _fetch() -> None:
            with httpx.Client(**client_kwargs) as client:
                with client.stream("GET", url) as resp:
                    resp.raise_for_status()
                    with tmp_path.open("wb") as f:
                        for chunk in resp.iter_bytes():
                            f.write(chunk)

        retry_request(_fetch, max_retries=1, base_delay=1.0)
        return tmp_path
    except Exception as exc:
        logger.warning("下载失败: %s - %s", url, exc)
        return None


def _download_image(
    url: str, dest: Path, settings: Settings, http_timeout: int = 20
) -> bool:
    """下载单张图片到目标路径（原子写入）。"""
    tmp = _download_to_temp(url, settings, http_timeout=http_timeout)
    if tmp is None:
        return False
    try:
        _write_delay(settings.write_delay)
        shutil.move(str(tmp), str(dest))
        return True
    except Exception:
        tmp.unlink(missing_ok=True)
        return False


CropBox = tuple[int, int, int, int] | None


def _download_image_with_crop(
    url: str,
    dest: Path,
    settings: Settings,
    crop_direction: str = "none",
    crop_box: CropBox = None,
    http_timeout: int = 20,
) -> bool:
    """下载图片，需要裁切时先下载到 /tmp 裁切后再移动到目标路径。

    避免在目标目录产生未裁切的临时文件。
    处理顺序：auto_trim → 精确裁切(crop_box) → 方向裁切(crop_direction)。
    """
    if (
        crop_direction == "none"
        and crop_box is None
        and not settings.auto_trim_white_borders
    ):
        return _download_image(url, dest, settings, http_timeout=http_timeout)

    tmp = _download_to_temp(url, settings, http_timeout=http_timeout)
    if tmp is None:
        return False
    try:
        if settings.auto_trim_white_borders:
            _trim_white_borders(tmp)
        if crop_box is not None:
            _crop_image_exact(tmp, *crop_box)
        if crop_direction != "none":
            _crop_image(tmp, crop_direction)
        _write_delay(settings.write_delay)
        shutil.move(str(tmp), str(dest))
        return True
    except Exception as exc:
        logger.warning("下载/裁切失败: %s - %s", url, exc)
        tmp.unlink(missing_ok=True)
        return False
