"""MCP tool factories for Kalshi API access."""

from __future__ import annotations

import json
from typing import Any

from claude_agent_sdk import tool

from .config import TradingConfig
from .kalshi_client import KalshiAPIClient


def _text(data: Any) -> list[dict]:
    """Wrap data as MCP text content."""
    return {"content": [{"type": "text", "text": json.dumps(data, default=str)}]}


def create_kalshi_tools(
    client: KalshiAPIClient,
    trading_config: TradingConfig,
) -> list:
    """Create MCP tool definitions bound to a Kalshi client via closure."""

    @tool(
        "search_markets",
        "Search Kalshi markets by keyword, status, series, or event ticker. "
        "Returns matching markets with tickers, titles, prices, and volumes.",
        {
            "query": {"type": "string", "description": "Search keyword or ticker pattern"},
            "status": {
                "type": "string",
                "description": "Filter by status: open, closed, settled",
                "optional": True,
            },
            "event_ticker": {
                "type": "string",
                "description": "Filter by event ticker",
                "optional": True,
            },
            "limit": {
                "type": "integer",
                "description": "Max results (default 50)",
                "optional": True,
            },
        },
    )
    async def search_markets(args: dict) -> dict:
        return _text(
            client.search_markets(
                query=args.get("query"),
                status=args.get("status"),
                event_ticker=args.get("event_ticker"),
                limit=args.get("limit", 50),
            )
        )

    @tool(
        "get_market_details",
        "Get full details for a single Kalshi market: rules, current prices, "
        "volume, open interest, settlement source, and close time.",
        {"ticker": {"type": "string", "description": "Market ticker (e.g. FED-25MAR-T4.50)"}},
    )
    async def get_market_details(args: dict) -> dict:
        return _text(client.get_market(args["ticker"]))

    @tool(
        "get_orderbook",
        "Get the current orderbook for a market: bid/ask levels, depth, spread, and mid price.",
        {
            "ticker": {"type": "string", "description": "Market ticker"},
            "depth": {
                "type": "integer",
                "description": "Number of price levels (default 10)",
                "optional": True,
            },
        },
    )
    async def get_orderbook(args: dict) -> dict:
        return _text(client.get_orderbook(args["ticker"], depth=args.get("depth", 10)))

    @tool(
        "get_event",
        "Get an event and all its nested markets. Events group related markets "
        "(e.g. all Fed rate brackets for a given meeting).",
        {"event_ticker": {"type": "string", "description": "Event ticker"}},
    )
    async def get_event(args: dict) -> dict:
        return _text(client.get_event(args["event_ticker"]))

    @tool(
        "get_price_history",
        "Get OHLC candlestick price history for a market. Useful for time-series "
        "analysis and volatility estimation.",
        {
            "ticker": {"type": "string", "description": "Market ticker"},
            "start_ts": {
                "type": "integer",
                "description": "Start timestamp (Unix seconds)",
                "optional": True,
            },
            "end_ts": {
                "type": "integer",
                "description": "End timestamp (Unix seconds)",
                "optional": True,
            },
            "period_interval": {
                "type": "integer",
                "description": "Candle interval in minutes (default 60)",
                "optional": True,
            },
        },
    )
    async def get_price_history(args: dict) -> dict:
        return _text(
            client.get_candlesticks(
                args["ticker"],
                start_ts=args.get("start_ts"),
                end_ts=args.get("end_ts"),
                period_interval=args.get("period_interval", 60),
            )
        )

    @tool(
        "get_recent_trades",
        "Get recent trade executions for a market: price, size, time, taker side.",
        {
            "ticker": {"type": "string", "description": "Market ticker"},
            "limit": {
                "type": "integer",
                "description": "Max trades to return (default 50)",
                "optional": True,
            },
        },
    )
    async def get_recent_trades(args: dict) -> dict:
        return _text(client.get_trades(args.get("ticker"), limit=args.get("limit", 50)))

    @tool(
        "get_portfolio",
        "Get portfolio overview: cash balance, open positions with P&L, "
        "recent fills, and settlements.",
        {
            "include_fills": {
                "type": "boolean",
                "description": "Include recent fills (default false)",
                "optional": True,
            },
            "include_settlements": {
                "type": "boolean",
                "description": "Include settlements (default false)",
                "optional": True,
            },
        },
    )
    async def get_portfolio(args: dict) -> dict:
        data: dict[str, Any] = {}
        data["balance"] = client.get_balance()
        data["positions"] = client.get_positions()
        if args.get("include_fills"):
            data["fills"] = client.get_fills()
        if args.get("include_settlements"):
            data["settlements"] = client.get_settlements()
        return _text(data)

    @tool(
        "get_open_orders",
        "List all resting (open) orders, optionally filtered by market ticker.",
        {
            "ticker": {
                "type": "string",
                "description": "Filter by market ticker",
                "optional": True,
            },
        },
    )
    async def get_open_orders(args: dict) -> dict:
        return _text(client.get_orders(ticker=args.get("ticker"), status="resting"))

    @tool(
        "place_order",
        "Place a limit or market order on a Kalshi market. Requires confirmation. "
        f"Max {trading_config.max_order_count} contracts per order. "
        f"Max ${trading_config.max_position_usd} per position.",
        {
            "ticker": {"type": "string", "description": "Market ticker"},
            "action": {"type": "string", "description": "'buy' or 'sell'"},
            "side": {"type": "string", "description": "'yes' or 'no'"},
            "count": {"type": "integer", "description": "Number of contracts"},
            "order_type": {
                "type": "string",
                "description": "'limit' or 'market' (default 'limit')",
                "optional": True,
            },
            "yes_price": {
                "type": "integer",
                "description": "Limit price in cents for yes side (1-99)",
                "optional": True,
            },
            "no_price": {
                "type": "integer",
                "description": "Limit price in cents for no side (1-99)",
                "optional": True,
            },
        },
    )
    async def place_order(args: dict) -> dict:
        return _text(
            client.create_order(
                ticker=args["ticker"],
                action=args["action"],
                side=args["side"],
                count=args["count"],
                order_type=args.get("order_type", "limit"),
                yes_price=args.get("yes_price"),
                no_price=args.get("no_price"),
            )
        )

    @tool(
        "cancel_order",
        "Cancel a resting order by order ID.",
        {"order_id": {"type": "string", "description": "Order ID to cancel"}},
    )
    async def cancel_order(args: dict) -> dict:
        return _text(client.cancel_order(args["order_id"]))

    return [
        search_markets,
        get_market_details,
        get_orderbook,
        get_event,
        get_price_history,
        get_recent_trades,
        get_portfolio,
        get_open_orders,
        place_order,
        cancel_order,
    ]
