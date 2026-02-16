"""Base class for platform API clients with shared rate limiting and serialization."""

from __future__ import annotations

from collections.abc import Awaitable
from typing import Any

from .rate_limiter import RateLimiter


class BaseAPIClient:
    """Shared helpers for async API client wrappers."""

    def __init__(self, reads_per_sec: int, writes_per_sec: int) -> None:
        self._limiter = RateLimiter(reads_per_sec=reads_per_sec, writes_per_sec=writes_per_sec)

    @staticmethod
    def _to_dict(resp: Any) -> Any:
        """Convert SDK response to dict (supports to_dict, model_dump, or passthrough)."""
        if hasattr(resp, "to_dict"):
            return resp.to_dict()
        if hasattr(resp, "model_dump"):
            return resp.model_dump()
        return resp

    async def _rate_read(self, cost: float = 1.0) -> None:
        await self._limiter.acquire_read(cost)

    async def _rate_write(self, cost: float = 1.0) -> None:
        await self._limiter.acquire_write(cost)

    async def _read(self, coro: Awaitable[Any], cost: float = 1.0) -> Any:
        """Rate-limit, await, and convert an SDK read call."""
        await self._rate_read(cost)
        return self._to_dict(await coro)

    async def _write(self, coro: Awaitable[Any], cost: float = 1.0) -> Any:
        """Rate-limit, await, and convert an SDK write call."""
        await self._rate_write(cost)
        return self._to_dict(await coro)
