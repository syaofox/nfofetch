from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache


@dataclass
class Settings:
    """应用基础配置。

    可以通过环境变量覆盖默认值：
    - NFOFETCH_USER_AGENT : HTTP User-Agent
    - NFOFETCH_HTTP_PROXY : HTTP 代理，例如 http://127.0.0.1:7890
    - NFOFETCH_JAVDB_COOKIE: 访问 javdb 时使用的 Cookie（含 cf_clearance 等）
    - NFOFETCH_JAVDB_MIRROR: javdb 镜像域名（默认 javdb565.com）
    - NFOFETCH_MAX_EXTRA_IMAGES: extrafanart 最大保存数量（默认 8，设为 0 完全禁用）
    - NFOFETCH_HTTP_TIMEOUT: 单个 HTTP 请求超时秒数（默认 20）
    - NFOFETCH_BATCH_TIMEOUT: extrafanart 批量下载总超时秒数（默认 120）
    - NFOFETCH_SERIAL_WRITES: 串行写入图片，避免 FUSE 网络文件系统并发 I/O 断开（默认 false）
    """

    user_agent: str
    http_proxy: str | None
    javdb_cookie: str | None
    javdb_mirror: str = "javdb565.com"
    max_extra_images: int = 8
    http_timeout: int = 20
    batch_timeout: int = 120
    serial_writes: bool = False


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
    javdb_mirror = os.getenv("NFOFETCH_JAVDB_MIRROR") or "javdb565.com"

    def _parse_int_env(name: str, default: int) -> int:
        val = os.getenv(name)
        if val is not None:
            try:
                return int(val)
            except (ValueError, TypeError):
                pass
        return default

    def _parse_bool_env(name: str, default: bool) -> bool:
        val = os.getenv(name)
        if val is not None:
            return val.lower() in ("true", "1", "yes")
        return default

    return Settings(
        user_agent=user_agent,
        http_proxy=http_proxy,
        javdb_cookie=javdb_cookie,
        javdb_mirror=javdb_mirror,
        max_extra_images=_parse_int_env("NFOFETCH_MAX_EXTRA_IMAGES", 8),
        http_timeout=_parse_int_env("NFOFETCH_HTTP_TIMEOUT", 20),
        batch_timeout=_parse_int_env("NFOFETCH_BATCH_TIMEOUT", 120),
        serial_writes=_parse_bool_env("NFOFETCH_SERIAL_WRITES", False),
    )
