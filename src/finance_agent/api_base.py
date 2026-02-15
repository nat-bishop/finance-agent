"""Base class for platform API clients with shared rate limiting and serialization."""

from __future__ import annotations

from typing import Any

from .rate_limiter import RateLimiter


class BaseAPIClient:
    """Shared helpers for API client wrappers (rate limiting, response conversion)."""

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

    def _rate_read(self) -> None:
        self._limiter.acquire_read_sync()

    def _rate_write(self) -> None:
        self._limiter.acquire_write_sync()
