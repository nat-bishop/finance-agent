"""Thin wrapper around the kalshi-python SDK."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from kalshi_python import Configuration, KalshiClient
from kalshi_python.models import CreateOrderRequest

from .api_base import BaseAPIClient
from .config import Credentials, TradingConfig


def _optional(**kwargs: Any) -> dict[str, Any]:
    """Return only non-None keyword arguments."""
    return {k: v for k, v in kwargs.items() if v is not None}


class KalshiAPIClient(BaseAPIClient):
    """Convenience wrapper providing typed methods around the Kalshi SDK."""

    def __init__(self, credentials: Credentials, config: TradingConfig) -> None:
        super().__init__(
            reads_per_sec=config.kalshi_rate_limit_reads_per_sec,
            writes_per_sec=config.kalshi_rate_limit_writes_per_sec,
        )
        self._config = config
        self._client = self._build_client(credentials, config)

    @staticmethod
    def _build_client(credentials: Credentials, config: TradingConfig) -> KalshiClient:
        cfg = Configuration(host=config.kalshi_api_url)
        cfg.api_key_id = credentials.kalshi_api_key_id

        if credentials.kalshi_private_key:
            cfg.private_key_pem = credentials.kalshi_private_key.replace("\\n", "\n")
        else:
            with Path(credentials.kalshi_private_key_path).open() as f:
                cfg.private_key_pem = f.read()

        return KalshiClient(cfg)

    # -- Market data (read) --

    def search_markets(
        self,
        *,
        query: str | None = None,
        status: str | None = None,
        series_ticker: str | None = None,
        event_ticker: str | None = None,
        limit: int = 50,
        cursor: str | None = None,
    ) -> dict[str, Any]:
        self._rate_read()
        kwargs: dict[str, Any] = {
            "limit": limit,
            **_optional(
                status=status,
                series_ticker=series_ticker,
                event_ticker=event_ticker,
                cursor=cursor,
            ),
        }
        # query is a keyword search — NOT the tickers param (which filters by exact ticker)
        if query:
            kwargs["query"] = query
        return self._to_dict(self._client.get_markets(**kwargs))

    def get_market(self, ticker: str) -> dict[str, Any]:
        self._rate_read()
        return self._to_dict(self._client.get_market(ticker))

    def get_orderbook(self, ticker: str, depth: int = 10) -> dict[str, Any]:
        self._rate_read()
        return self._to_dict(self._client.get_market_orderbook(ticker, depth=depth))

    def get_event(self, event_ticker: str, with_nested_markets: bool = True) -> dict[str, Any]:
        self._rate_read()
        return self._to_dict(
            self._client.get_event(event_ticker, with_nested_markets=with_nested_markets)
        )

    def get_trades(
        self,
        ticker: str | None = None,
        *,
        limit: int = 50,
        cursor: str | None = None,
    ) -> dict[str, Any]:
        self._rate_read()
        kwargs: dict[str, Any] = {"limit": limit, **_optional(ticker=ticker, cursor=cursor)}
        return self._to_dict(self._client.get_trades(**kwargs))

    def get_candlesticks(
        self,
        ticker: str,
        *,
        start_ts: int | None = None,
        end_ts: int | None = None,
        period_interval: int = 60,
    ) -> dict[str, Any]:
        self._rate_read()
        kwargs = {
            "ticker": ticker,
            "market_ticker": ticker,
            "period_interval": period_interval,
            **_optional(start_ts=start_ts, end_ts=end_ts),
        }
        return self._to_dict(self._client.get_market_candlesticks(**kwargs))

    # -- Portfolio (read) --

    def get_balance(self) -> dict[str, Any]:
        self._rate_read()
        return self._to_dict(self._client.get_balance())

    def get_positions(
        self,
        *,
        ticker: str | None = None,
        event_ticker: str | None = None,
        limit: int = 100,
        cursor: str | None = None,
    ) -> dict[str, Any]:
        self._rate_read()
        kwargs: dict[str, Any] = {
            "limit": limit,
            "settlement_status": "unsettled",
            **_optional(ticker=ticker, event_ticker=event_ticker, cursor=cursor),
        }
        return self._to_dict(self._client.get_positions(**kwargs))

    def get_fills(
        self,
        *,
        ticker: str | None = None,
        limit: int = 100,
        cursor: str | None = None,
    ) -> dict[str, Any]:
        self._rate_read()
        kwargs: dict[str, Any] = {"limit": limit, **_optional(ticker=ticker, cursor=cursor)}
        return self._to_dict(self._client.get_fills(**kwargs))

    def get_settlements(
        self,
        *,
        limit: int = 100,
        cursor: str | None = None,
    ) -> dict[str, Any]:
        self._rate_read()
        kwargs: dict[str, Any] = {"limit": limit, **_optional(cursor=cursor)}
        return self._to_dict(self._client.get_settlements(**kwargs))

    # -- Orders (write) --

    def get_orders(
        self,
        *,
        ticker: str | None = None,
        status: str | None = None,
        limit: int = 100,
    ) -> dict[str, Any]:
        self._rate_read()
        kwargs: dict[str, Any] = {"limit": limit, **_optional(ticker=ticker, status=status)}
        return self._to_dict(self._client.get_orders(**kwargs))

    def create_order(
        self,
        *,
        ticker: str,
        action: str,
        side: str,
        count: int,
        order_type: str = "limit",
        yes_price: int | None = None,
        no_price: int | None = None,
        client_order_id: str | None = None,
        expiration_ts: int | None = None,
    ) -> dict[str, Any]:
        self._rate_write()
        kwargs = {
            "ticker": ticker,
            "action": action,
            "side": side,
            "count": count,
            "type": order_type,
            **_optional(
                yes_price=yes_price,
                no_price=no_price,
                client_order_id=client_order_id,
                expiration_ts=expiration_ts,
            ),
        }
        return self._to_dict(self._client.create_order(CreateOrderRequest(**kwargs)))

    def cancel_order(self, order_id: str) -> dict[str, Any]:
        self._rate_write()
        return self._to_dict(self._client.cancel_order(order_id))

    # -- Batch operations --

    def batch_create_orders(self, orders: list[dict[str, Any]]) -> dict[str, Any]:
        """Batch create up to 20 orders. Each dict follows CreateOrderRequest fields."""
        self._rate_write()
        reqs = [CreateOrderRequest(**o) for o in orders]
        return self._to_dict(self._client.batch_create_orders(reqs))

    def batch_cancel_orders(self, order_ids: list[str]) -> dict[str, Any]:
        self._rate_write()
        return self._to_dict(self._client.batch_cancel_orders(order_ids))

    def amend_order(
        self,
        order_id: str,
        *,
        price: int | None = None,
        count: int | None = None,
    ) -> dict[str, Any]:
        self._rate_write()
        kwargs = _optional(price=price, count=count)
        return self._to_dict(self._client.amend_order(order_id, **kwargs))

    # -- Exchange status --

    def get_exchange_status(self) -> dict[str, Any]:
        self._rate_read()
        return self._to_dict(self._client.get_exchange_status())

    # -- Events (paginated) --

    def get_events(
        self,
        *,
        status: str | None = None,
        with_nested_markets: bool = True,
        limit: int = 200,
        cursor: str | None = None,
    ) -> dict[str, Any]:
        self._rate_read()
        kwargs: dict[str, Any] = {
            "limit": limit,
            "with_nested_markets": with_nested_markets,
            **_optional(status=status, cursor=cursor),
        }
        return self._to_dict(self._client.get_events(**kwargs))
