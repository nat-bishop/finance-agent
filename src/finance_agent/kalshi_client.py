"""Thin wrapper around the kalshi-python SDK."""

from __future__ import annotations

from typing import Any

from kalshi_python import Configuration, KalshiClient
from kalshi_python.models import CreateOrderRequest

from .config import TradingConfig
from .rate_limiter import RateLimiter


class KalshiAPIClient:
    """Convenience wrapper providing typed methods around the Kalshi SDK."""

    def __init__(
        self,
        config: TradingConfig,
        rate_limiter: RateLimiter | None = None,
    ) -> None:
        self._config = config
        self._client = self._build_client(config)
        self._limiter = rate_limiter

    @staticmethod
    def _build_client(config: TradingConfig) -> KalshiClient:
        cfg = Configuration(host=config.kalshi_api_url)
        cfg.api_key_id = config.kalshi_api_key_id

        with open(config.kalshi_private_key_path) as f:
            cfg.private_key_pem = f.read()

        return KalshiClient(cfg)

    def _to_dict(self, resp: Any) -> dict[str, Any]:
        """Convert SDK response to dict."""
        return resp.to_dict() if hasattr(resp, "to_dict") else resp

    def _rate_read(self) -> None:
        """Block until a read token is available (if limiter configured)."""
        if self._limiter:
            self._limiter.acquire_read_sync()

    def _rate_write(self) -> None:
        """Block until a write token is available (if limiter configured)."""
        if self._limiter:
            self._limiter.acquire_write_sync()

    # ── Market data (read) ──────────────────────────────────────────

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
        kwargs: dict[str, Any] = {"limit": limit}
        if query:
            kwargs["tickers"] = query  # SDK uses tickers param for search
        if status:
            kwargs["status"] = status
        if series_ticker:
            kwargs["series_ticker"] = series_ticker
        if event_ticker:
            kwargs["event_ticker"] = event_ticker
        if cursor:
            kwargs["cursor"] = cursor
        resp = self._client.get_markets(**kwargs)
        return self._to_dict(resp)

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
        kwargs: dict[str, Any] = {"limit": limit}
        if ticker:
            kwargs["ticker"] = ticker
        if cursor:
            kwargs["cursor"] = cursor
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
            **({"start_ts": start_ts} if start_ts is not None else {}),
            **({"end_ts": end_ts} if end_ts is not None else {}),
        }
        return self._to_dict(self._client.get_market_candlesticks(**kwargs))

    # ── Portfolio (read) ────────────────────────────────────────────

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
        kwargs: dict[str, Any] = {"limit": limit, "settlement_status": "unsettled"}
        if ticker:
            kwargs["ticker"] = ticker
        if event_ticker:
            kwargs["event_ticker"] = event_ticker
        if cursor:
            kwargs["cursor"] = cursor
        return self._to_dict(self._client.get_positions(**kwargs))

    def get_fills(
        self,
        *,
        ticker: str | None = None,
        limit: int = 100,
        cursor: str | None = None,
    ) -> dict[str, Any]:
        self._rate_read()
        kwargs: dict[str, Any] = {"limit": limit}
        if ticker:
            kwargs["ticker"] = ticker
        if cursor:
            kwargs["cursor"] = cursor
        return self._to_dict(self._client.get_fills(**kwargs))

    def get_settlements(
        self,
        *,
        limit: int = 100,
        cursor: str | None = None,
    ) -> dict[str, Any]:
        self._rate_read()
        kwargs: dict[str, Any] = {"limit": limit}
        if cursor:
            kwargs["cursor"] = cursor
        return self._to_dict(self._client.get_settlements(**kwargs))

    # ── Orders (write) ──────────────────────────────────────────────

    def get_orders(
        self,
        *,
        ticker: str | None = None,
        status: str | None = None,
        limit: int = 100,
    ) -> dict[str, Any]:
        self._rate_read()
        kwargs: dict[str, Any] = {"limit": limit}
        if ticker:
            kwargs["ticker"] = ticker
        if status:
            kwargs["status"] = status
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
            **({"yes_price": yes_price} if yes_price is not None else {}),
            **({"no_price": no_price} if no_price is not None else {}),
            **({"client_order_id": client_order_id} if client_order_id else {}),
            **({"expiration_ts": expiration_ts} if expiration_ts is not None else {}),
        }
        return self._to_dict(self._client.create_order(CreateOrderRequest(**kwargs)))

    def cancel_order(self, order_id: str) -> dict[str, Any]:
        self._rate_write()
        return self._to_dict(self._client.cancel_order(order_id))
