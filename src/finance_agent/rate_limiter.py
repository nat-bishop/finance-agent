"""Token-bucket rate limiter for Kalshi API calls."""

from __future__ import annotations

import asyncio
import time


class RateLimiter:
    """Async token-bucket rate limiter with separate read/write buckets."""

    def __init__(self, reads_per_sec: int = 20, writes_per_sec: int = 10) -> None:
        self._read_tokens = float(reads_per_sec)
        self._write_tokens = float(writes_per_sec)
        self._max_read = float(reads_per_sec)
        self._max_write = float(writes_per_sec)
        self._last_refill = time.monotonic()

    def _refill(self) -> None:
        now = time.monotonic()
        elapsed = now - self._last_refill
        self._read_tokens = min(self._max_read, self._read_tokens + elapsed * self._max_read)
        self._write_tokens = min(self._max_write, self._write_tokens + elapsed * self._max_write)
        self._last_refill = now

    async def acquire_read(self) -> None:
        """Wait until a read token is available."""
        while True:
            self._refill()
            if self._read_tokens >= 1.0:
                self._read_tokens -= 1.0
                return
            # Wait for ~1 token to refill
            wait = (1.0 - self._read_tokens) / self._max_read
            await asyncio.sleep(wait)

    async def acquire_write(self) -> None:
        """Wait until a write token is available."""
        while True:
            self._refill()
            if self._write_tokens >= 1.0:
                self._write_tokens -= 1.0
                return
            wait = (1.0 - self._write_tokens) / self._max_write
            await asyncio.sleep(wait)

    def acquire_read_sync(self) -> None:
        """Blocking version for synchronous code."""
        while True:
            self._refill()
            if self._read_tokens >= 1.0:
                self._read_tokens -= 1.0
                return
            wait = (1.0 - self._read_tokens) / self._max_read
            time.sleep(wait)

    def acquire_write_sync(self) -> None:
        """Blocking version for synchronous code."""
        while True:
            self._refill()
            if self._write_tokens >= 1.0:
                self._write_tokens -= 1.0
                return
            wait = (1.0 - self._write_tokens) / self._max_write
            time.sleep(wait)
