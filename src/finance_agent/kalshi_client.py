"""Thin wrapper around the kalshi-python SDK."""

from __future__ import annotations

from typing import Any

from kalshi_python import Configuration, KalshiClient
from kalshi_python.models import CreateOrderRequest

from .config import TradingConfig


class KalshiAPIClient:
    """Convenience wrapper providing typed methods around the Kalshi SDK."""

    def __init__(self, config: TradingConfig) -> None:
        self._config = config
        self._client = self._build_client(config)

    @staticmethod
    def _build_client(config: TradingConfig) -> KalshiClient:
        cfg = Configuration(host=config.kalshi_api_url)
        cfg.api_key_id = config.kalshi_api_key_id

        with open(config.kalshi_private_key_path, "r") as f:
            cfg.private_key_pem = f.read()

        return KalshiClient(cfg)

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
        return resp.to_dict() if hasattr(resp, "to_dict") else resp

    def get_market(self, ticker: str) -> dict[str, Any]:
        resp = self._client.get_market(ticker)
        return resp.to_dict() if hasattr(resp, "to_dict") else resp

    def get_orderbook(self, ticker: str, depth: int = 10) -> dict[str, Any]:
        resp = self._client.get_market_orderbook(ticker, depth=depth)
        return resp.to_dict() if hasattr(resp, "to_dict") else resp

    def get_event(self, event_ticker: str, with_nested_markets: bool = True) -> dict[str, Any]:
        resp = self._client.get_event(event_ticker, with_nested_markets=with_nested_markets)
        return resp.to_dict() if hasattr(resp, "to_dict") else resp

    def get_trades(
        self,
        ticker: str | None = None,
        *,
        limit: int = 50,
        cursor: str | None = None,
    ) -> dict[str, Any]:
        kwargs: dict[str, Any] = {"limit": limit}
        if ticker:
            kwargs["ticker"] = ticker
        if cursor:
            kwargs["cursor"] = cursor
        resp = self._client.get_trades(**kwargs)
        return resp.to_dict() if hasattr(resp, "to_dict") else resp

    def get_candlesticks(
        self,
        ticker: str,
        *,
        start_ts: int | None = None,
        end_ts: int | None = None,
        period_interval: int = 60,
    ) -> dict[str, Any]:
        kwargs: dict[str, Any] = {
            "ticker": ticker,
            "market_ticker": ticker,
            "period_interval": period_interval,
        }
        if start_ts is not None:
            kwargs["start_ts"] = start_ts
        if end_ts is not None:
            kwargs["end_ts"] = end_ts
        resp = self._client.get_market_candlesticks(**kwargs)
        return resp.to_dict() if hasattr(resp, "to_dict") else resp

    # ── Portfolio (read) ────────────────────────────────────────────

    def get_balance(self) -> dict[str, Any]:
        resp = self._client.get_balance()
        return resp.to_dict() if hasattr(resp, "to_dict") else resp

    def get_positions(
        self,
        *,
        ticker: str | None = None,
        event_ticker: str | None = None,
        limit: int = 100,
        cursor: str | None = None,
    ) -> dict[str, Any]:
        kwargs: dict[str, Any] = {"limit": limit, "settlement_status": "unsettled"}
        if ticker:
            kwargs["ticker"] = ticker
        if event_ticker:
            kwargs["event_ticker"] = event_ticker
        if cursor:
            kwargs["cursor"] = cursor
        resp = self._client.get_positions(**kwargs)
        return resp.to_dict() if hasattr(resp, "to_dict") else resp

    def get_fills(
        self,
        *,
        ticker: str | None = None,
        limit: int = 100,
        cursor: str | None = None,
    ) -> dict[str, Any]:
        kwargs: dict[str, Any] = {"limit": limit}
        if ticker:
            kwargs["ticker"] = ticker
        if cursor:
            kwargs["cursor"] = cursor
        resp = self._client.get_fills(**kwargs)
        return resp.to_dict() if hasattr(resp, "to_dict") else resp

    def get_settlements(
        self,
        *,
        limit: int = 100,
        cursor: str | None = None,
    ) -> dict[str, Any]:
        kwargs: dict[str, Any] = {"limit": limit}
        if cursor:
            kwargs["cursor"] = cursor
        resp = self._client.get_settlements(**kwargs)
        return resp.to_dict() if hasattr(resp, "to_dict") else resp

    # ── Orders (write) ──────────────────────────────────────────────

    def get_orders(
        self,
        *,
        ticker: str | None = None,
        status: str | None = None,
        limit: int = 100,
    ) -> dict[str, Any]:
        kwargs: dict[str, Any] = {"limit": limit}
        if ticker:
            kwargs["ticker"] = ticker
        if status:
            kwargs["status"] = status
        resp = self._client.get_orders(**kwargs)
        return resp.to_dict() if hasattr(resp, "to_dict") else resp

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
        kwargs: dict[str, Any] = {
            "ticker": ticker,
            "action": action,
            "side": side,
            "count": count,
            "type": order_type,
        }
        if yes_price is not None:
            kwargs["yes_price"] = yes_price
        if no_price is not None:
            kwargs["no_price"] = no_price
        if client_order_id:
            kwargs["client_order_id"] = client_order_id
        if expiration_ts is not None:
            kwargs["expiration_ts"] = expiration_ts

        resp = self._client.create_order(CreateOrderRequest(**kwargs))
        return resp.to_dict() if hasattr(resp, "to_dict") else resp

    def cancel_order(self, order_id: str) -> dict[str, Any]:
        resp = self._client.cancel_order(order_id)
        return resp.to_dict() if hasattr(resp, "to_dict") else resp
