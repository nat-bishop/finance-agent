"""Thin wrapper around the polymarket-us SDK."""

from __future__ import annotations

from typing import Any

from polymarket_us import PolymarketUS

from .api_base import BaseAPIClient
from .config import Credentials, TradingConfig

# Map agent action+side to Polymarket intent
PM_INTENT_MAP = {
    ("buy", "yes"): "ORDER_INTENT_BUY_LONG",
    ("sell", "yes"): "ORDER_INTENT_SELL_LONG",
    ("buy", "no"): "ORDER_INTENT_BUY_SHORT",
    ("sell", "no"): "ORDER_INTENT_SELL_SHORT",
}

# Map Polymarket intent back to action+side
PM_INTENT_REVERSE = {v: k for k, v in PM_INTENT_MAP.items()}


def cents_to_usd(cents: int) -> str:
    """Convert price in cents (1-99) to USD string for Polymarket."""
    return f"{cents / 100:.2f}"


class PolymarketAPIClient(BaseAPIClient):
    """Convenience wrapper providing typed methods around the Polymarket US SDK."""

    def __init__(self, credentials: Credentials, config: TradingConfig) -> None:
        super().__init__(
            reads_per_sec=config.polymarket_rate_limit_reads_per_sec,
            writes_per_sec=config.polymarket_rate_limit_writes_per_sec,
        )
        self._config = config
        self._client = PolymarketUS(
            key_id=credentials.polymarket_key_id,
            secret_key=credentials.polymarket_secret_key,
        )

    # -- Market data (read) --

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
        return self._to_dict(self._client.markets.list(params))  # type: ignore[arg-type]

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
        return self._to_dict(self._client.markets.trades(slug, {"limit": limit}))  # type: ignore[attr-defined]

    # -- Portfolio (read) --

    def get_balance(self) -> dict[str, Any]:
        self._rate_read()
        return self._to_dict(self._client.account.balances())

    def get_positions(self) -> dict[str, Any]:
        self._rate_read()
        return self._to_dict(self._client.portfolio.positions())

    def get_orders(
        self,
        *,
        market_slug: str | None = None,
        status: str | None = None,
    ) -> dict[str, Any]:
        self._rate_read()
        params: dict[str, Any] = {}
        if market_slug:
            params["marketSlug"] = market_slug
        if status:
            params["status"] = status
        return self._to_dict(self._client.orders.list(params))  # type: ignore[arg-type]

    # -- Orders (write) --

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
        params = {"marketSlug": slug} if slug else {}
        self._client.orders.cancel(order_id, params)  # type: ignore[arg-type]
        return {"status": "cancelled", "order_id": order_id}
