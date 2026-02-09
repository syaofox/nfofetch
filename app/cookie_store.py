from __future__ import annotations

from typing import Optional, Dict
from urllib.parse import urlparse


# 站点级 Cookie 配置：
# - key 可以是完整域名（例如 "javdb.com"）、镜像域名（例如 "javdb565.com"），
#   也可以是逻辑站点名（例如 "javdb"）。
# - 建议只在本地填自己的 Cookie，不要提交到公开仓库。
SITE_COOKIES: Dict[str, str] = {
    # 示例（请按需在本地取消注释并填入真实 Cookie）：
    "javdb": "theme=auto; locale=zh; over18=1; list_mode=v; cf_clearance=Q7JWebG79o2mgPvKh221eHvwzqtMeIxyzxaqSWwCQfU-1770643654-1.2.1.1-0AVR23pIZ86tghek0MnXsYVpO0km7VG9MNmgMR005uAtT9sV_BFvRx4xU02_HDCJY6Y9XndneSccFgCWwKUGGxsTJrMEAM9PuWngGx15gBYyV9Y8v1vf2kmfXNFvLp4MeLW514RulCqkWuCV48TmLxd1h3jLTDjsG1N0rlwfIP_DKqM.P2tVKMxEfg38uG8UdvzT0wNNuYdLW3O5Q9PddwsfQ1WNq0dZG0NmrMSyfZE; _jdb_session=Pg8G6xJzriv4vEdO6Z4lJNOVVnA2imL5uvP9CtQtrArnLGGhCxU7EgnNbAD9dkfP91CtYxU0noNOTjjRxr45k4kOnE8aIjEe7ovJw%2B74bGS1EJ6ZCnY39K65XHetqtF5Iivb5M7FKGBcbwIkDRtlFj5fUEDlBllscjvlVPbIMSM6qlOK2ueGSbJjRHI6Gj1gllxs%2BBoa4xpBH3ezhCPlkUDHrSrlXsbE2u%2Bk0MqVoAxU4TrGdBrcxaoBuPKpAUsBYeFqGdRWPEtuX1STGfuRSegYKX%2BtsRROEh8GxMWyOzyVMpbLXlmJHwyIIvXEiAXmNvT5oQ339kZn%2FV54zG1ePRCMtZLeBfQ02qUKezr%2BMlNMEBeAT4pghOwhyCppsvm0mf4hlA3H7ySi9ec1AWmY8A3zhhQw14rHzNMYgRibdZiY%2FQd2u%2Fk6%2FDr1Hrj65QmDqqGxraU%2FIhYFETZxUH7T%2FfetqVZSaA%3D%3D--yLmMCJT73SfjWxSO--s3CSSzW3hVlcAB3i6XwRyg%3D%3D",
    # "javdb565.com": "theme=auto; locale=zh; over18=1; ...",
}


def get_cookie_for_url(url: str, env_cookie: Optional[str] = None) -> Optional[str]:
    """根据 URL 和环境变量返回最终要使用的 Cookie。

    优先级：
    1. 显式传入的 env_cookie（例如 NFOFETCH_JAVDB_COOKIE）
    2. 根据站点 / 域名在 SITE_COOKIES 中查找预设 Cookie
    """

    # 1. 环境变量优先
    if env_cookie:
        return env_cookie

    parsed = urlparse(url)
    host = parsed.netloc.lower()

    # 2. 精确域名匹配
    if host in SITE_COOKIES:
        return SITE_COOKIES[host]

    # 3. 站点名匹配（例如 "javdb565.com" 命中逻辑 key "javdb"）
    for key, value in SITE_COOKIES.items():
        if key and key in host:
            return value

    return None

