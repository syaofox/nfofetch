from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from functools import lru_cache
from typing import Optional


@dataclass
class Settings:
    """应用基础配置。

    可以通过环境变量覆盖默认值：
    - NFOFETCH_OUTPUT_ROOT: 输出根目录（默认 ./output）
    - NFOFETCH_USER_AGENT : HTTP User-Agent
    - NFOFETCH_HTTP_PROXY : HTTP 代理，例如 http://127.0.0.1:7890
    - NFOFETCH_JAVDB_COOKIE: 访问 javdb 时使用的 Cookie（含 cf_clearance 等）
    """

    output_root: Path
    user_agent: str
    http_proxy: Optional[str]
    javdb_cookie: Optional[str]


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    base_dir = Path(os.getenv("NFOFETCH_BASE_DIR", os.getcwd()))

    output_root_env = os.getenv("NFOFETCH_OUTPUT_ROOT")
    if output_root_env:
        output_root = Path(output_root_env)
    else:
        output_root = base_dir / "output"

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

    return Settings(
        output_root=output_root,
        user_agent=user_agent,
        http_proxy=http_proxy,
        javdb_cookie=javdb_cookie,
    )

