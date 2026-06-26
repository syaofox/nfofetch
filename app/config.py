from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache


@dataclass(frozen=True)
class Settings:
    """应用基础配置。

    可以通过环境变量覆盖默认值：
    - NFOFETCH_USER_AGENT : HTTP User-Agent
    - NFOFETCH_HTTP_PROXY : HTTP 代理，例如 http://127.0.0.1:7890
    - NFOFETCH_JAVDB_COOKIE: 访问 javdb 时使用的 Cookie（含 cf_clearance 等）
    - NFOFETCH_JAV321_COOKIE: 访问 jav321 时使用的 Cookie
    - NFOFETCH_DMM_COOKIE: 访问 video.dmm.co.jp (FANZA) 时使用的 Cookie（含 age_check_done 等）
    - NFOFETCH_JAVDB_MIRROR: javdb 镜像域名（默认 javdb565.com）
    - NFOFETCH_MAX_EXTRA_IMAGES: extrafanart 最大保存数量（默认 8，设为 0 完全禁用）
    - NFOFETCH_HTTP_TIMEOUT: 单个 HTTP 请求超时秒数（默认 20）
    - NFOFETCH_BATCH_TIMEOUT: extrafanart 批量下载总超时秒数（默认 120）
    - NFOFETCH_SERIAL_WRITES: 串行写入图片，避免 FUSE 网络文件系统并发 I/O 断开（默认 false）
    - NFOFETCH_LOCK_ENABLED: 启用目录锁防止同目录并发刮削，多用户 Web 场景需要（默认 false）
    - NFOFETCH_WRITE_DELAY: 每次 FUSE 写入操作前的停顿秒数，缓解网络文件系统断开（默认 0.2）
    - NFOFETCH_DELETE_ORPHAN_EXTRAFANART: 重新刮削时删除网页上不再存在的本地剧照（默认 false）
    - NFOFETCH_FILTER_ACTOR_GENDER: {actor} 占位符只包含女演员（默认 true）
    - NFOFETCH_DOWNLOAD_CONCURRENCY: extrafanart 剧照下载并发数（默认 4）
    - NFOFETCH_AUTO_TRIM_WHITE_BORDERS: 裁切前自动检测并去除图片白边（默认 false）
    - NFOFETCH_ENABLED_SCRAPERS: 启用的刮削站点列表，逗号分隔，例如 "site1,site2"（默认全部启用）
    """

    user_agent: str
    http_proxy: str | None
    javdb_cookie: str | None
    jav321_cookie: str | None = None
    dmm_cookie: str | None = None
    javdb_mirror: str = "javdb565.com"
    max_extra_images: int = 8
    http_timeout: int = 20
    batch_timeout: int = 120
    serial_writes: bool = False
    lock_enabled: bool = False
    write_delay: float = 0.2
    delete_orphan_extrafanart: bool = False
    filter_actor_gender: bool = True
    download_concurrency: int = 4
    auto_trim_white_borders: bool = False
    enabled_scrapers: set[str] | None = None


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
    jav321_cookie = os.getenv("NFOFETCH_JAV321_COOKIE") or None
    dmm_cookie = os.getenv("NFOFETCH_DMM_COOKIE") or None
    javdb_mirror = os.getenv("NFOFETCH_JAVDB_MIRROR") or "javdb565.com"

    def _parse_int_env(name: str, default: int) -> int:
        val = os.getenv(name)
        if val is not None:
            try:
                return int(val)
            except (ValueError, TypeError):
                pass
        return default

    def _parse_float_env(name: str, default: float) -> float:
        val = os.getenv(name)
        if val is not None:
            try:
                return float(val)
            except (ValueError, TypeError):
                pass
        return default

    def _parse_bool_env(name: str, default: bool) -> bool:
        val = os.getenv(name)
        if val is not None:
            return val.lower() in ("true", "1", "yes")
        return default

    def _parse_set_env(name: str) -> set[str] | None:
        val = os.getenv(name)
        if val is not None:
            return {s.strip().lower() for s in val.split(",") if s.strip()}
        return None

    return Settings(
        user_agent=user_agent,
        http_proxy=http_proxy,
        javdb_cookie=javdb_cookie,
        jav321_cookie=jav321_cookie,
        dmm_cookie=dmm_cookie,
        javdb_mirror=javdb_mirror,
        max_extra_images=_parse_int_env("NFOFETCH_MAX_EXTRA_IMAGES", 8),
        http_timeout=_parse_int_env("NFOFETCH_HTTP_TIMEOUT", 20),
        batch_timeout=_parse_int_env("NFOFETCH_BATCH_TIMEOUT", 120),
        serial_writes=_parse_bool_env("NFOFETCH_SERIAL_WRITES", False),
        lock_enabled=_parse_bool_env("NFOFETCH_LOCK_ENABLED", False),
        write_delay=_parse_float_env("NFOFETCH_WRITE_DELAY", 0.2),
        delete_orphan_extrafanart=_parse_bool_env(
            "NFOFETCH_DELETE_ORPHAN_EXTRAFANART", False
        ),
        filter_actor_gender=_parse_bool_env("NFOFETCH_FILTER_ACTOR_GENDER", True),
        download_concurrency=_parse_int_env("NFOFETCH_DOWNLOAD_CONCURRENCY", 4),
        auto_trim_white_borders=_parse_bool_env(
            "NFOFETCH_AUTO_TRIM_WHITE_BORDERS", False
        ),
        enabled_scrapers=_parse_set_env("NFOFETCH_ENABLED_SCRAPERS"),
    )
