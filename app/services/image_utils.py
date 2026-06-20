from __future__ import annotations

import logging
import shutil
import tempfile
from pathlib import Path

import httpx

from app.config import Settings
from app.retry import retry_request
from app.services.file_utils import _TEMP_PREFIX

logger = logging.getLogger(__name__)


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
    """下载图片到临时文件，返回临时路径（失败返回 None）。"""
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
        shutil.move(str(tmp), str(dest))
        return True
    except Exception:
        tmp.unlink(missing_ok=True)
        return False


def _download_image_with_crop(
    url: str,
    dest: Path,
    settings: Settings,
    crop_direction: str = "none",
    http_timeout: int = 20,
) -> bool:
    """下载图片，需要裁切时先下载到 /tmp 裁切后再移动到目标路径。

    避免在目标目录产生未裁切的临时文件。
    """
    if crop_direction == "none":
        return _download_image(url, dest, settings, http_timeout=http_timeout)

    tmp = _download_to_temp(url, settings, http_timeout=http_timeout)
    if tmp is None:
        return False
    try:
        _crop_image(tmp, crop_direction)
        shutil.move(str(tmp), str(dest))
        return True
    except Exception as exc:
        logger.warning("下载/裁切失败: %s - %s", url, exc)
        tmp.unlink(missing_ok=True)
        return False
