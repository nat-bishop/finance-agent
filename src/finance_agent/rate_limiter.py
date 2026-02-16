"""Token-bucket rate limiter for API calls."""

from __future__ import annotations

import asyncio
import threading
import time
from typing import Literal


class RateLimiter:
    """Token-bucket rate limiter with separate read/write buckets.

    Thread-safe: used from ThreadPoolExecutor in TUIServices.
    """

    def __init__(self, reads_per_sec: int = 30, writes_per_sec: int = 30) -> None:
        self._tokens = {"read": float(reads_per_sec), "write": float(writes_per_sec)}
        self._max = {"read": float(reads_per_sec), "write": float(writes_per_sec)}
        self._last_refill = time.monotonic()
        self._lock = threading.Lock()

    def _refill(self) -> None:
        now = time.monotonic()
        elapsed = now - self._last_refill
        for bucket in ("read", "write"):
            self._tokens[bucket] = min(
                self._max[bucket], self._tokens[bucket] + elapsed * self._max[bucket]
            )
        self._last_refill = now

    def _try_acquire(self, bucket: Literal["read", "write"], cost: float = 1.0) -> float | None:
        """Try to consume `cost` tokens. Returns None on success, or wait time if unavailable."""
        with self._lock:
            self._refill()
            if self._tokens[bucket] >= cost:
                self._tokens[bucket] -= cost
                return None
            return (cost - self._tokens[bucket]) / self._max[bucket]

    def acquire_sync(self, bucket: Literal["read", "write"], cost: float = 1.0) -> None:
        while (wait := self._try_acquire(bucket, cost)) is not None:
            time.sleep(wait)

    def acquire_read_sync(self, cost: float = 1.0) -> None:
        self.acquire_sync("read", cost)

    def acquire_write_sync(self, cost: float = 1.0) -> None:
        self.acquire_sync("write", cost)

    async def acquire(self, bucket: Literal["read", "write"], cost: float = 1.0) -> None:
        while (wait := self._try_acquire(bucket, cost)) is not None:
            await asyncio.sleep(wait)

    async def acquire_read(self, cost: float = 1.0) -> None:
        await self.acquire("read", cost)

    async def acquire_write(self, cost: float = 1.0) -> None:
        await self.acquire("write", cost)
