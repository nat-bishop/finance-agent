"""Thin wrapper around the polymarket-us SDK."""

from __future__ import annotations

from typing import Any

from polymarket_us import PolymarketUS

from .config import TradingConfig
from .rate_limiter import RateLimiter


class PolymarketAPIClient:
    """Convenience wrapper providing typed methods around the Polymarket US SDK."""

    def __init__(
        self,
        config: TradingConfig,
        rate_limiter: RateLimiter | None = None,
    ) -> None:
        self._config = config
        self._client = PolymarketUS(
            key_id=config.polymarket_key_id,
            secret_key=config.polymarket_secret_key,
        )
        self._limiter = rate_limiter

    def _to_dict(self, resp: Any) -> Any:
        """Convert SDK response to dict if needed."""
        if hasattr(resp, "to_dict"):
            return resp.to_dict()
        if hasattr(resp, "model_dump"):
            return resp.model_dump()
        return resp

    def _rate_read(self) -> None:
        """Block until a read token is available (if limiter configured)."""
        if self._limiter:
            self._limiter.acquire_read_sync()

    def _rate_write(self) -> None:
        """Block until a write token is available (if limiter configured)."""
        if self._limiter:
            self._limiter.acquire_write_sync()

    # ── Market data (read) ──────────────────────────────────────

    def search_markets(
        self,
        *,
        query: str | None = None,
        status: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> dict[str, Any]:
        self._rate_read()
        params: dict[str, Any] = {"limit": limit, "offset": offset}
        if status:
            params["active"] = status == "open"
        if query:
            params["query"] = query
        result = self._client.markets.list(params)  # type: ignore[arg-type]
        return self._to_dict(result)

    def get_market(self, slug: str) -> dict[str, Any]:
        self._rate_read()
        return self._to_dict(self._client.markets.retrieve_by_slug(slug))

    def get_orderbook(self, slug: str) -> dict[str, Any]:
        self._rate_read()
        return self._to_dict(self._client.markets.book(slug))

    def get_bbo(self, slug: str) -> dict[str, Any]:
        self._rate_read()
        return self._to_dict(self._client.markets.bbo(slug))

    def get_event(self, slug: str) -> dict[str, Any]:
        self._rate_read()
        return self._to_dict(self._client.events.retrieve_by_slug(slug))

    def list_events(
        self,
        *,
        active: bool = True,
        limit: int = 50,
        offset: int = 0,
    ) -> dict[str, Any]:
        self._rate_read()
        return self._to_dict(
            self._client.events.list({"active": active, "limit": limit, "offset": offset})
        )

    def get_trades(
        self,
        slug: str,
        *,
        limit: int = 50,
    ) -> dict[str, Any]:
        self._rate_read()
        # Trades may be accessible via market detail or a dedicated endpoint
        # The SDK may expose this through markets or a trades resource
        return self._to_dict(self._client.markets.retrieve_by_slug(slug))

    # ── Portfolio (read) ────────────────────────────────────────

    def get_balance(self) -> dict[str, Any]:
        self._rate_read()
        return self._to_dict(self._client.account.balances())

    def get_positions(self) -> dict[str, Any]:
        self._rate_read()
        return self._to_dict(self._client.portfolio.positions())

    # ── Orders (write) ──────────────────────────────────────────

    def create_order(
        self,
        *,
        slug: str,
        intent: str,
        order_type: str = "ORDER_TYPE_LIMIT",
        price: str = "0.50",
        quantity: int = 1,
        tif: str = "TIME_IN_FORCE_GOOD_TILL_CANCEL",
    ) -> dict[str, Any]:
        self._rate_write()
        order_params: dict[str, Any] = {
            "marketSlug": slug,
            "intent": intent,
            "type": order_type,
            "price": {"value": price, "currency": "USD"},
            "quantity": quantity,
            "tif": tif,
        }
        return self._to_dict(self._client.orders.create(order_params))  # type: ignore[arg-type]

    def cancel_order(self, order_id: str, slug: str = "") -> dict[str, Any]:
        self._rate_write()
        params: dict[str, str] = {}
        if slug:
            params["marketSlug"] = slug
        self._client.orders.cancel(order_id, params)  # type: ignore[arg-type]
        return {"status": "cancelled", "order_id": order_id}
