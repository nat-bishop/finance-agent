"""Base class for platform API clients with shared rate limiting and serialization."""

from __future__ import annotations

import functools
import threading
from collections.abc import Callable
from typing import Any

from .rate_limiter import RateLimiter


def _thread_safe[F: Callable[..., Any]](method: F) -> F:
    """Decorator that serializes access to the underlying SDK client.

    Each BaseAPIClient instance has its own ``_api_lock``, so calls to
    different exchanges can still run in parallel.
    """

    @functools.wraps(method)
    def wrapper(self: BaseAPIClient, *args: Any, **kwargs: Any) -> Any:
        with self._api_lock:
            return method(self, *args, **kwargs)

    return wrapper  # type: ignore[return-value]


class BaseAPIClient:
    """Shared helpers for API client wrappers (rate limiting, response conversion)."""

    def __init__(self, reads_per_sec: int, writes_per_sec: int) -> None:
        self._limiter = RateLimiter(reads_per_sec=reads_per_sec, writes_per_sec=writes_per_sec)
        self._api_lock = threading.Lock()

    @staticmethod
    def _to_dict(resp: Any) -> Any:
        """Convert SDK response to dict (supports to_dict, model_dump, or passthrough)."""
        if hasattr(resp, "to_dict"):
            return resp.to_dict()
        if hasattr(resp, "model_dump"):
            return resp.model_dump()
        return resp

    def _rate_read(self, cost: float = 1.0) -> None:
        self._limiter.acquire_read_sync(cost)

    def _rate_write(self, cost: float = 1.0) -> None:
        self._limiter.acquire_write_sync(cost)
