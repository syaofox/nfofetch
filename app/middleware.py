from __future__ import annotations

import threading
import time
from typing import Callable

from fastapi import FastAPI, Request, Response
from fastapi.responses import JSONResponse


LOCK_DURATION = 30.0


class RequestLock:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._locks: dict[str, float] = {}

    def _cleanup(self) -> None:
        now = time.monotonic()
        stale = [k for k, v in self._locks.items() if now - v >= LOCK_DURATION]
        for k in stale:
            self._locks.pop(k, None)

    def is_locked(self, key: str) -> bool:
        now = time.monotonic()
        with self._lock:
            if key in self._locks:
                if now - self._locks[key] < LOCK_DURATION:
                    return True
                del self._locks[key]
            return False

    def lock(self, key: str) -> None:
        with self._lock:
            self._locks[key] = time.monotonic()
            self._cleanup()

    def unlock(self, key: str) -> None:
        with self._lock:
            self._locks.pop(key, None)


_request_lock = RequestLock()


LOCKED_ENDPOINTS = {"/scrape/fetch", "/scrape/search", "/scrape"}


def get_client_ip(request: Request) -> str:
    forwarded = request.headers.get("X-Forwarded-For")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


def create_rate_limit_middleware(app: FastAPI) -> None:
    @app.middleware("http")
    async def rate_limit_middleware(
        request: Request, call_next: Callable[[Request], Response]
    ) -> Response:
        if request.url.path not in LOCKED_ENDPOINTS:
            return await call_next(request)

        ip = get_client_ip(request)
        key = f"{ip}:{request.url.path}"

        if _request_lock.is_locked(key):
            return JSONResponse(
                status_code=429,
                content={
                    "error": "操作进行中，请勿重复提交",
                    "retry_after": LOCK_DURATION,
                },
            )

        _request_lock.lock(key)
        try:
            response = await call_next(request)
            return response
        finally:
            _request_lock.unlock(key)
