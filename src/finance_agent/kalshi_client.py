"""Thin wrapper around the kalshi-python SDK."""

from __future__ import annotations

from typing import Any

from kalshi_python import Configuration, KalshiClient
from kalshi_python.models import CreateOrderRequest

from .api_base import BaseAPIClient
from .config import TradingConfig
from .rate_limiter import RateLimiter


def _optional(**kwargs: Any) -> dict[str, Any]:
    """Return only non-None keyword arguments."""
    return {k: v for k, v in kwargs.items() if v is not None}


class KalshiAPIClient(BaseAPIClient):
    """Convenience wrapper providing typed methods around the Kalshi SDK."""

    def __init__(
        self,
        config: TradingConfig,
        rate_limiter: RateLimiter | None = None,
    ) -> None:
        super().__init__(rate_limiter)
        self._config = config
        self._client = self._build_client(config)

    @staticmethod
    def _build_client(config: TradingConfig) -> KalshiClient:
        cfg = Configuration(host=config.kalshi_api_url)
        cfg.api_key_id = config.kalshi_api_key_id

        with open(config.kalshi_private_key_path) as f:
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
                tickers=query,
                status=status,
                series_ticker=series_ticker,
                event_ticker=event_ticker,
                cursor=cursor,
            ),
        }
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
