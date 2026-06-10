from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache
from typing import Optional


@dataclass
class Settings:
    """应用基础配置。

    可以通过环境变量覆盖默认值：
    - NFOFETCH_USER_AGENT : HTTP User-Agent
    - NFOFETCH_HTTP_PROXY : HTTP 代理，例如 http://127.0.0.1:7890
    - NFOFETCH_JAVDB_COOKIE: 访问 javdb 时使用的 Cookie（含 cf_clearance 等）
    - NFOFETCH_MAX_EXTRA_IMAGES: extrafanart 最大保存数量（默认 8）
    - NFOFETCH_HTTP_TIMEOUT: 单个 HTTP 请求超时秒数（默认 20）
    - NFOFETCH_BATCH_TIMEOUT: extrafanart 批量下载总超时秒数（默认 120）
    """

    user_agent: str
    http_proxy: Optional[str]
    javdb_cookie: Optional[str]
    max_extra_images: int
    http_timeout: int
    batch_timeout: int


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    # 默认使用一个看起来像正常浏览器的 UA，避免被部分站点直接 403。
    user_agent = os.getenv(
        "NFOFETCH_USER_AGENT",
        (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:117.0) "
            "Gecko/20100101 Firefox/117.0"
        ),
    )

    http_proxy = os.getenv("NFOFETCH_HTTP_PROXY") or None
    javdb_cookie = os.getenv("NFOFETCH_JAVDB_COOKIE") or None
    max_extra_images_str = os.getenv("NFOFETCH_MAX_EXTRA_IMAGES")
    max_extra_images = int(max_extra_images_str) if max_extra_images_str else 8

    http_timeout_str = os.getenv("NFOFETCH_HTTP_TIMEOUT")
    try:
        http_timeout = int(http_timeout_str) if http_timeout_str else 20
    except (ValueError, TypeError):
        http_timeout = 20

    batch_timeout_str = os.getenv("NFOFETCH_BATCH_TIMEOUT")
    try:
        batch_timeout = int(batch_timeout_str) if batch_timeout_str else 120
    except (ValueError, TypeError):
        batch_timeout = 120

    return Settings(
        user_agent=user_agent,
        http_proxy=http_proxy,
        javdb_cookie=javdb_cookie,
        max_extra_images=max_extra_images,
        http_timeout=http_timeout,
        batch_timeout=batch_timeout,
    )
