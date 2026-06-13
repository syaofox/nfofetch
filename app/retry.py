from __future__ import annotations

import random
import time

import httpx

try:
    from curl_cffi.requests.exceptions import HTTPError as _CurlHTTPError
except Exception:
    _CurlHTTPError = None  # type: ignore[assignment, misc]

RETRYABLE_STATUSES = frozenset({429, 500, 502, 503, 504})


def _get_status(exc: Exception) -> int | None:
    if isinstance(exc, httpx.HTTPStatusError):
        return exc.response.status_code
    if _CurlHTTPError is not None and isinstance(exc, _CurlHTTPError):
        r = getattr(exc, "response", None)
        if r is not None:
            return getattr(r, "status_code", None)
    return None


def retry_request(func, max_retries: int = 2, base_delay: float = 1.0):
    """带指数退避的重试封装，适用于 httpx / curl_cffi 请求。

    - HTTP 状态码属于 5xx 或 429 时重试
    - 连接错误 / 超时 / 协议错误等网络异常无条件重试
    - 其他 4xx 客户端错误不重试
    """
    for attempt in range(max_retries + 1):
        try:
            return func()
        except Exception as exc:
            if attempt == max_retries:
                raise
            status = _get_status(exc)
            if status is not None and status not in RETRYABLE_STATUSES:
                raise
            delay = min(base_delay * (2**attempt) + random.uniform(0, 0.5), 10.0)
            time.sleep(delay)
