from __future__ import annotations

from app.middleware import RequestLock


class TestRequestLock:
    def test_lock_and_unlock(self) -> None:
        lock = RequestLock()
        assert not lock.is_locked("test-key")
        lock.lock("test-key")
        assert lock.is_locked("test-key")
        lock.unlock("test-key")
        assert not lock.is_locked("test-key")

    def test_expires_after_duration(self) -> None:
        lock = RequestLock()
        lock.lock("test-key")
        assert lock.is_locked("test-key")

        original_duration = lock._locks["test-key"] - 31.0
        lock._locks["test-key"] = original_duration
        assert not lock.is_locked("test-key")

    def test_multiple_keys(self) -> None:
        lock = RequestLock()
        lock.lock("key-a")
        lock.lock("key-b")
        assert lock.is_locked("key-a")
        assert lock.is_locked("key-b")
        lock.unlock("key-a")
        assert not lock.is_locked("key-a")
        assert lock.is_locked("key-b")

    def test_unlock_non_existent_key(self) -> None:
        lock = RequestLock()
        lock.unlock("no-such-key")

    def test_is_locked_unknown_key(self) -> None:
        lock = RequestLock()
        assert not lock.is_locked("unknown")
