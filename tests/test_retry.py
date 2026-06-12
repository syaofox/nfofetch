from __future__ import annotations

import httpx
import pytest

from app.retry import _get_status, retry_request


class TestGetStatus:
    def test_httpx_status_error(self) -> None:
        resp = httpx.Response(503)
        exc = httpx.HTTPStatusError(
            "error", request=httpx.Request("GET", "/"), response=resp
        )
        assert _get_status(exc) == 503

    def test_other_exception(self) -> None:
        exc = ValueError("something else")
        assert _get_status(exc) is None


class TestRetryRequest:
    def test_success_on_first_try(self) -> None:
        call_count = 0

        def func() -> str:
            nonlocal call_count
            call_count += 1
            return "ok"

        result = retry_request(func, max_retries=2)
        assert result == "ok"
        assert call_count == 1

    def test_retry_on_5xx_then_succeed(self) -> None:
        call_count = 0

        def func() -> str:
            nonlocal call_count
            call_count += 1
            if call_count < 3:
                resp = httpx.Response(502)
                raise httpx.HTTPStatusError(
                    "bad gateway", request=httpx.Request("GET", "/"), response=resp
                )
            return "ok"

        result = retry_request(func, max_retries=3)
        assert result == "ok"
        assert call_count == 3

    def test_retry_on_429(self) -> None:
        call_count = 0

        def func() -> str:
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                resp = httpx.Response(429)
                raise httpx.HTTPStatusError(
                    "too many", request=httpx.Request("GET", "/"), response=resp
                )
            return "ok"

        result = retry_request(func, max_retries=1)
        assert result == "ok"

    def test_no_retry_on_4xx(self) -> None:
        def func() -> str:
            resp = httpx.Response(404)
            raise httpx.HTTPStatusError(
                "not found", request=httpx.Request("GET", "/"), response=resp
            )

        with pytest.raises(httpx.HTTPStatusError):
            retry_request(func, max_retries=2)

    def test_exhaust_retries(self) -> None:
        call_count = 0

        def func() -> str:
            nonlocal call_count
            call_count += 1
            resp = httpx.Response(503)
            raise httpx.HTTPStatusError(
                "fail", request=httpx.Request("GET", "/"), response=resp
            )

        with pytest.raises(httpx.HTTPStatusError):
            retry_request(func, max_retries=2)
        assert call_count == 3  # initial + 2 retries

    def test_network_error_retry(self) -> None:
        call_count = 0

        def func() -> str:
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise httpx.ConnectError("connection refused")
            return "ok"

        result = retry_request(func, max_retries=1)
        assert result == "ok"
