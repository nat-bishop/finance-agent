"""Tests for finance_agent.rate_limiter -- token bucket rate limiter."""

from __future__ import annotations

from unittest.mock import patch

from finance_agent.rate_limiter import RateLimiter

# ── _try_acquire ─────────────────────────────────────────────────


def test_try_acquire_success_returns_none():
    rl = RateLimiter(reads_per_sec=10, writes_per_sec=5)
    with patch("finance_agent.rate_limiter.time.monotonic", return_value=0.0):
        rl._last_refill = 0.0
        rl._tokens["read"] = 5.0
        result = rl._try_acquire("read")
    assert result is None
    assert rl._tokens["read"] == 4.0


def test_try_acquire_failure_returns_wait_time():
    rl = RateLimiter(reads_per_sec=10, writes_per_sec=5)
    with patch("finance_agent.rate_limiter.time.monotonic", return_value=0.0):
        rl._last_refill = 0.0
        rl._tokens["read"] = 0.5
        wait = rl._try_acquire("read")
    assert wait is not None
    # wait = (1.0 - 0.5) / 10 = 0.05
    assert abs(wait - 0.05) < 0.001


def test_try_acquire_exact_one_token():
    rl = RateLimiter(reads_per_sec=10, writes_per_sec=5)
    with patch("finance_agent.rate_limiter.time.monotonic", return_value=0.0):
        rl._last_refill = 0.0
        rl._tokens["read"] = 1.0
        result = rl._try_acquire("read")
    assert result is None
    assert rl._tokens["read"] == 0.0


# ── _refill ──────────────────────────────────────────────────────


def test_refill_adds_tokens():
    rl = RateLimiter(reads_per_sec=10, writes_per_sec=5)
    with patch("finance_agent.rate_limiter.time.monotonic") as mock_time:
        mock_time.return_value = 0.0
        rl._refill()  # sets _last_refill = 0
        rl._tokens["read"] = 5.0
        mock_time.return_value = 0.5  # 0.5 seconds elapsed
        rl._refill()
    # Should add 0.5 * 10 = 5 tokens => 10 (capped at max)
    assert rl._tokens["read"] == 10.0


def test_refill_caps_at_max():
    rl = RateLimiter(reads_per_sec=10, writes_per_sec=5)
    rl._tokens["read"] = 10.0
    with patch("finance_agent.rate_limiter.time.monotonic", return_value=100.0):
        rl._last_refill = 0.0
        rl._refill()
    assert rl._tokens["read"] == 10.0


# ── Separate buckets ─────────────────────────────────────────────


def test_separate_read_write_buckets():
    rl = RateLimiter(reads_per_sec=1, writes_per_sec=1)
    with patch("finance_agent.rate_limiter.time.monotonic", return_value=0.0):
        rl._last_refill = 0.0
        rl._tokens = {"read": 1.0, "write": 1.0}
        rl._try_acquire("read")
    assert rl._tokens["read"] == 0.0
    assert rl._tokens["write"] == 1.0  # unaffected


# ── Sync methods ─────────────────────────────────────────────────


def test_acquire_read_sync():
    rl = RateLimiter(reads_per_sec=100, writes_per_sec=100)
    rl.acquire_read_sync()  # Should succeed immediately


def test_acquire_write_sync():
    rl = RateLimiter(reads_per_sec=100, writes_per_sec=100)
    rl.acquire_write_sync()


# ── Cost parameter ──────────────────────────────────────────────


def test_try_acquire_multi_token_cost():
    rl = RateLimiter(reads_per_sec=10, writes_per_sec=10)
    with patch("finance_agent.rate_limiter.time.monotonic", return_value=0.0):
        rl._last_refill = 0.0
        rl._tokens["write"] = 10.0
        result = rl._try_acquire("write", cost=5.0)
    assert result is None
    assert rl._tokens["write"] == 5.0


def test_try_acquire_fractional_cost():
    rl = RateLimiter(reads_per_sec=10, writes_per_sec=10)
    with patch("finance_agent.rate_limiter.time.monotonic", return_value=0.0):
        rl._last_refill = 0.0
        rl._tokens["write"] = 1.0
        result = rl._try_acquire("write", cost=0.2)
    assert result is None
    assert abs(rl._tokens["write"] - 0.8) < 0.001


def test_try_acquire_insufficient_for_cost():
    rl = RateLimiter(reads_per_sec=10, writes_per_sec=10)
    with patch("finance_agent.rate_limiter.time.monotonic", return_value=0.0):
        rl._last_refill = 0.0
        rl._tokens["write"] = 1.5
        wait = rl._try_acquire("write", cost=3.0)
    assert wait is not None
    # wait = (3.0 - 1.5) / 10 = 0.15
    assert abs(wait - 0.15) < 0.001


def test_acquire_write_sync_with_cost():
    rl = RateLimiter(reads_per_sec=100, writes_per_sec=100)
    rl.acquire_write_sync(cost=5.0)  # Should succeed immediately (100 tokens available)
