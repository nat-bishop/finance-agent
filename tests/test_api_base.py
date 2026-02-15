"""Tests for finance_agent.api_base -- BaseAPIClient."""

from __future__ import annotations

import threading
import time
from unittest.mock import MagicMock, patch

from finance_agent.api_base import BaseAPIClient, _thread_safe

# ── _to_dict ─────────────────────────────────────────────────────


def test_to_dict_with_to_dict():
    obj = MagicMock()
    obj.to_dict.return_value = {"a": 1}
    assert BaseAPIClient._to_dict(obj) == {"a": 1}


def test_to_dict_with_model_dump():
    obj = MagicMock(spec=[])
    # Need to add model_dump explicitly since spec=[] removes everything
    obj.model_dump = MagicMock(return_value={"b": 2})
    assert BaseAPIClient._to_dict(obj) == {"b": 2}


def test_to_dict_passthrough():
    assert BaseAPIClient._to_dict({"c": 3}) == {"c": 3}
    assert BaseAPIClient._to_dict([1, 2, 3]) == [1, 2, 3]
    assert BaseAPIClient._to_dict("string") == "string"


# ── Rate limiting delegation ─────────────────────────────────────


def test_rate_read_calls_limiter():
    client = BaseAPIClient(reads_per_sec=10, writes_per_sec=5)
    with patch.object(client._limiter, "acquire_read_sync") as mock:
        client._rate_read()
        mock.assert_called_once()


def test_rate_write_calls_limiter():
    client = BaseAPIClient(reads_per_sec=10, writes_per_sec=5)
    with patch.object(client._limiter, "acquire_write_sync") as mock:
        client._rate_write()
        mock.assert_called_once()


# ── Thread safety ────────────────────────────────────────────────


def test_api_lock_exists():
    client = BaseAPIClient(reads_per_sec=10, writes_per_sec=5)
    assert hasattr(client, "_api_lock")
    # threading.Lock() returns a _thread.lock object; verify it has acquire/release
    assert hasattr(client._api_lock, "acquire")
    assert hasattr(client._api_lock, "release")


def test_thread_safe_acquires_lock():
    """_thread_safe decorator holds the lock during method execution."""
    client = BaseAPIClient(reads_per_sec=10, writes_per_sec=5)
    lock_was_held = []

    @_thread_safe
    def fake_method(self):
        # Lock should already be held — non-blocking acquire should fail
        lock_was_held.append(not self._api_lock.acquire(blocking=False))

    fake_method(client)
    assert lock_was_held == [True]


def test_concurrent_calls_serialized():
    """Two threads calling the same decorated method never overlap."""
    client = BaseAPIClient(reads_per_sec=100, writes_per_sec=100)
    in_critical = threading.Event()
    overlap_detected = threading.Event()

    @_thread_safe
    def slow_method(self):
        if in_critical.is_set():
            overlap_detected.set()
        in_critical.set()
        time.sleep(0.05)
        in_critical.clear()

    t1 = threading.Thread(target=slow_method, args=(client,))
    t2 = threading.Thread(target=slow_method, args=(client,))
    t1.start()
    t2.start()
    t1.join()
    t2.join()

    assert not overlap_detected.is_set()


def test_separate_instances_independent():
    """Different BaseAPIClient instances have independent locks."""
    c1 = BaseAPIClient(reads_per_sec=10, writes_per_sec=5)
    c2 = BaseAPIClient(reads_per_sec=10, writes_per_sec=5)
    assert c1._api_lock is not c2._api_lock
