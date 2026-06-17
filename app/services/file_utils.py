from __future__ import annotations

import functools
import logging
import time
from concurrent.futures import ThreadPoolExecutor, TimeoutError as _FutureTimeoutError
from typing import Any, Callable, TypeVar

logger = logging.getLogger(__name__)

T = TypeVar("T")

_RETRYABLE_ERRNOS: set[int] = {
    5,  # EIO - I/O error (NFS/network disconnect)
    116,  # ESTALE - Stale NFS file handle
    117,  # ENETDOWN - Network is down
    118,  # ENETUNREACH - Network is unreachable
    119,  # ENETRESET - Network dropped connection
    120,  # ECONNABORTED - Connection aborted
    121,  # ECONNRESET - Connection reset
    122,  # ETIMEDOUT - Connection timed out
    123,  # EHOSTUNREACH - No route to host
    124,  # EHOSTDOWN - Host is down
    125,  # EREMOTEIO - Remote I/O error
}


def run_with_timeout(
    func: Callable[..., T],
    timeout: float,
    *args: Any,
    **kwargs: Any,
) -> T:
    """在独立线程中执行 func，超过 timeout 秒则抛出 TimeoutError。"""
    with ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(func, *args, **kwargs)
        try:
            return future.result(timeout=timeout)
        except _FutureTimeoutError:
            future.cancel()
            raise TimeoutError(f"Operation timed out after {timeout}s: {func.__name__}")


def retry_on_oserror(
    max_retries: int = 2,
    base_delay: float = 1.0,
    retryable_errnos: set[int] | None = None,
) -> Callable[[Callable[..., T]], Callable[..., T]]:
    """装饰器：对网络文件系统的 OSError 自动重试。"""
    if retryable_errnos is None:
        retryable_errnos = _RETRYABLE_ERRNOS

    def decorator(func: Callable[..., T]) -> Callable[..., T]:
        @functools.wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> T:
            last_exc: OSError | None = None
            for attempt in range(max_retries + 1):
                try:
                    return func(*args, **kwargs)
                except OSError as e:
                    last_exc = e
                    errno = getattr(e, "errno", None)
                    if errno in retryable_errnos and attempt < max_retries:
                        delay = base_delay * (2**attempt)
                        logger.warning(
                            "OSError (errno=%d) on %s, retry %d/%d in %.1fs: %s",
                            errno,
                            func.__name__,
                            attempt + 1,
                            max_retries,
                            delay,
                            e,
                        )
                        time.sleep(delay)
                        continue
                    raise
            raise last_exc  # type: ignore[misc]

        return wrapper

    return decorator
