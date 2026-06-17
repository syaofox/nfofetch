from __future__ import annotations

import time

import pytest

from app.services.file_utils import retry_on_oserror, run_with_timeout


class TestRunWithTimeout:
    def test_success(self) -> None:
        result = run_with_timeout(lambda: 42, 5.0)
        assert result == 42

    def test_with_args(self) -> None:
        result = run_with_timeout(lambda a, b: a + b, 5.0, 3, 4)
        assert result == 7

    def test_timeout(self) -> None:
        with pytest.raises(TimeoutError):
            run_with_timeout(lambda: time.sleep(10), 0.05)

    def test_exception_propagated(self) -> None:
        def _fail() -> None:
            msg = "something went wrong"
            raise ValueError(msg)

        with pytest.raises(ValueError, match="something went wrong"):
            run_with_timeout(_fail, 5.0)


class TestRetryOnOSError:
    def test_success_first_try(self) -> None:
        call_count = [0]

        @retry_on_oserror(max_retries=2, base_delay=0.01)
        def ok() -> str:
            call_count[0] += 1
            return "done"

        assert ok() == "done"
        assert call_count[0] == 1

    def test_retry_then_success(self) -> None:
        call_count = [0]

        @retry_on_oserror(max_retries=2, base_delay=0.01)
        def flaky() -> str:
            call_count[0] += 1
            if call_count[0] < 3:
                raise OSError(5, "fake I/O error")
            return "ok"

        assert flaky() == "ok"
        assert call_count[0] == 3

    def test_exhaust_retries(self) -> None:
        call_count = [0]

        @retry_on_oserror(max_retries=1, base_delay=0.01)
        def always_fail() -> str:
            call_count[0] += 1
            raise OSError(122, "fake timeout")

        with pytest.raises(OSError, match="fake timeout"):
            always_fail()
        assert call_count[0] == 2  # 1 original + 1 retry

    def test_non_retryable_errno(self) -> None:
        @retry_on_oserror(max_retries=2, base_delay=0.01)
        def perm_error() -> str:
            raise OSError(13, "permission denied")

        with pytest.raises(OSError, match="permission denied"):
            perm_error()

    def test_custom_errno_set(self) -> None:
        call_count = [0]

        @retry_on_oserror(max_retries=1, base_delay=0.01, retryable_errnos={99})
        def custom_errno() -> str:
            call_count[0] += 1
            if call_count[0] == 1:
                raise OSError(99, "custom retryable")
            return "ok"

        assert custom_errno() == "ok"
        assert call_count[0] == 2

    def test_non_oserror_passes_through(self) -> None:
        @retry_on_oserror(max_retries=2, base_delay=0.01)
        def non_os() -> str:
            msg = "not an OSError"
            raise RuntimeError(msg)

        with pytest.raises(RuntimeError, match="not an OSError"):
            non_os()

    def test_preserves_function_metadata(self) -> None:
        @retry_on_oserror(max_retries=1, base_delay=0.01)
        def my_func() -> str:
            return "ok"

        assert my_func.__name__ == "my_func"
