"""Token-bucket rate limiter for API calls."""

from __future__ import annotations

import asyncio
import time
from typing import Literal


class RateLimiter:
    """Token-bucket rate limiter with separate read/write buckets."""

    def __init__(self, reads_per_sec: int = 20, writes_per_sec: int = 10) -> None:
        self._tokens = {"read": float(reads_per_sec), "write": float(writes_per_sec)}
        self._max = {"read": float(reads_per_sec), "write": float(writes_per_sec)}
        self._last_refill = time.monotonic()

    def _refill(self) -> None:
        now = time.monotonic()
        elapsed = now - self._last_refill
        for bucket in ("read", "write"):
            self._tokens[bucket] = min(
                self._max[bucket], self._tokens[bucket] + elapsed * self._max[bucket]
            )
        self._last_refill = now

    def _try_acquire(self, bucket: Literal["read", "write"]) -> float | None:
        """Try to consume a token. Returns None on success, or wait time if unavailable."""
        self._refill()
        if self._tokens[bucket] >= 1.0:
            self._tokens[bucket] -= 1.0
            return None
        return (1.0 - self._tokens[bucket]) / self._max[bucket]

    async def acquire_read(self) -> None:
        while (wait := self._try_acquire("read")) is not None:
            await asyncio.sleep(wait)

    async def acquire_write(self) -> None:
        while (wait := self._try_acquire("write")) is not None:
            await asyncio.sleep(wait)

    def acquire_read_sync(self) -> None:
        while (wait := self._try_acquire("read")) is not None:
            time.sleep(wait)

    def acquire_write_sync(self) -> None:
        while (wait := self._try_acquire("write")) is not None:
            time.sleep(wait)
