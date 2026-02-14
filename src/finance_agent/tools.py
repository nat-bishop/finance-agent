"""MCP tool factories for Kalshi API access and database."""

from __future__ import annotations

import json
from typing import Any

from claude_agent_sdk import tool

from .config import TradingConfig
from .database import AgentDatabase
from .kalshi_client import KalshiAPIClient
from .polymarket_client import PolymarketAPIClient


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


def create_polymarket_tools(
    client: PolymarketAPIClient,
    trading_config: TradingConfig,
) -> list:
    """Create MCP tool definitions bound to a Polymarket client via closure."""

    @tool(
        "search_markets",
        "Search Polymarket US markets by keyword or category. "
        "Returns matching markets with slugs, titles, prices, and volumes.",
        {
            "query": {"type": "string", "description": "Search keyword"},
            "limit": {
                "type": "integer",
                "description": "Max results (default 50)",
                "optional": True,
            },
        },
    )
    async def search_markets(args: dict) -> dict:
        return _text(client.search_markets(query=args.get("query"), limit=args.get("limit", 50)))

    @tool(
        "get_market_details",
        "Get full details for a single Polymarket US market by slug: rules, "
        "current prices, volume, and resolution criteria.",
        {"slug": {"type": "string", "description": "Market slug (e.g. btc-100k-2025)"}},
    )
    async def get_market_details(args: dict) -> dict:
        return _text(client.get_market(args["slug"]))

    @tool(
        "get_orderbook",
        "Get the current orderbook for a Polymarket market: bids, offers, depth.",
        {"slug": {"type": "string", "description": "Market slug"}},
    )
    async def get_orderbook(args: dict) -> dict:
        return _text(client.get_orderbook(args["slug"]))

    @tool(
        "get_event",
        "Get a Polymarket event and all its nested markets by event slug.",
        {"slug": {"type": "string", "description": "Event slug"}},
    )
    async def get_event(args: dict) -> dict:
        return _text(client.get_event(args["slug"]))

    @tool(
        "get_trades",
        "Get recent trade data for a Polymarket market.",
        {
            "slug": {"type": "string", "description": "Market slug"},
            "limit": {
                "type": "integer",
                "description": "Max trades to return (default 50)",
                "optional": True,
            },
        },
    )
    async def get_trades(args: dict) -> dict:
        return _text(client.get_trades(args["slug"], limit=args.get("limit", 50)))

    @tool(
        "get_portfolio",
        "Get Polymarket portfolio: cash balance and open positions.",
        {},
    )
    async def get_portfolio(args: dict) -> dict:
        data: dict[str, Any] = {}
        data["balance"] = client.get_balance()
        data["positions"] = client.get_positions()
        return _text(data)

    @tool(
        "place_order",
        "Place an order on Polymarket US. Requires user approval. "
        "Prices in USD decimals (e.g. '0.55'). "
        "Intents: ORDER_INTENT_BUY_LONG, ORDER_INTENT_SELL_LONG, "
        "ORDER_INTENT_BUY_SHORT, ORDER_INTENT_SELL_SHORT. "
        f"Max ${trading_config.polymarket_max_position_usd} per position.",
        {
            "slug": {"type": "string", "description": "Market slug"},
            "intent": {
                "type": "string",
                "description": "Order intent: ORDER_INTENT_BUY_LONG, SELL_LONG, BUY_SHORT, SELL_SHORT",
            },
            "price": {
                "type": "string",
                "description": "Limit price in USD (e.g. '0.55')",
            },
            "quantity": {"type": "integer", "description": "Number of contracts"},
            "order_type": {
                "type": "string",
                "description": "'ORDER_TYPE_LIMIT' or 'ORDER_TYPE_MARKET' (default LIMIT)",
                "optional": True,
            },
            "tif": {
                "type": "string",
                "description": "Time-in-force: GTC, GTD, IOC, FOK (default GTC)",
                "optional": True,
            },
        },
    )
    async def place_order(args: dict) -> dict:
        return _text(
            client.create_order(
                slug=args["slug"],
                intent=args["intent"],
                price=args["price"],
                quantity=args["quantity"],
                order_type=args.get("order_type", "ORDER_TYPE_LIMIT"),
                tif=args.get("tif", "TIME_IN_FORCE_GOOD_TILL_CANCEL"),
            )
        )

    @tool(
        "cancel_order",
        "Cancel an open order on Polymarket US by order ID.",
        {
            "order_id": {"type": "string", "description": "Order ID to cancel"},
            "slug": {
                "type": "string",
                "description": "Market slug for the order",
                "optional": True,
            },
        },
    )
    async def cancel_order(args: dict) -> dict:
        return _text(client.cancel_order(args["order_id"], slug=args.get("slug", "")))

    return [
        search_markets,
        get_market_details,
        get_orderbook,
        get_event,
        get_trades,
        get_portfolio,
        place_order,
        cancel_order,
    ]


def create_db_tools(db: AgentDatabase) -> list:
    """Create MCP tool definitions for database access."""

    @tool(
        "db_query",
        "Execute a read-only SQL SELECT query against the agent database. "
        "Tables: market_snapshots, events, signals, trades, predictions, "
        "portfolio_snapshots, sessions, watchlist. Returns list of row dicts.",
        {
            "sql": {
                "type": "string",
                "description": "SQL SELECT query to execute",
            },
        },
    )
    async def db_query(args: dict) -> dict:
        rows = db.query(args["sql"])
        return _text(rows)

    @tool(
        "db_log_prediction",
        "Log a probability prediction for a market. Used for calibration tracking.",
        {
            "market_ticker": {
                "type": "string",
                "description": "Kalshi market ticker",
            },
            "prediction": {
                "type": "number",
                "description": "Predicted probability (0.0 to 1.0)",
            },
            "market_price_cents": {
                "type": "integer",
                "description": "Current market price in cents",
                "optional": True,
            },
            "methodology": {
                "type": "string",
                "description": "How you arrived at this prediction",
                "optional": True,
            },
            "notes": {
                "type": "string",
                "description": "Additional context",
                "optional": True,
            },
        },
    )
    async def db_log_prediction(args: dict) -> dict:
        pred_id = db.log_prediction(
            market_ticker=args["market_ticker"],
            prediction=args["prediction"],
            market_price_cents=args.get("market_price_cents"),
            methodology=args.get("methodology"),
            notes=args.get("notes"),
        )
        return _text({"prediction_id": pred_id, "status": "logged"})

    @tool(
        "db_resolve_predictions",
        "Resolve predictions by checking settled markets. "
        "Pass a list of {prediction_id, outcome} pairs.",
        {
            "resolutions": {
                "type": "array",
                "description": "List of {prediction_id: int, outcome: int (1=yes, 0=no)}",
            },
        },
    )
    async def db_resolve_predictions(args: dict) -> dict:
        resolved = 0
        for r in args.get("resolutions", []):
            db.resolve_prediction(r["prediction_id"], r["outcome"])
            resolved += 1
        return _text({"resolved": resolved})

    @tool(
        "db_get_session_state",
        "Get session state for startup: last session summary, pending signals, "
        "unresolved predictions, watchlist, portfolio delta, recent trades.",
        {},
    )
    async def db_get_session_state(args: dict) -> dict:
        return _text(db.get_session_state())

    @tool(
        "db_add_watchlist",
        "Add a market to the watchlist for tracking across sessions.",
        {
            "ticker": {"type": "string", "description": "Market ticker to watch"},
            "reason": {
                "type": "string",
                "description": "Why you're watching this market",
                "optional": True,
            },
            "alert_condition": {
                "type": "string",
                "description": "Condition to alert on (e.g. 'price_below_30')",
                "optional": True,
            },
        },
    )
    async def db_add_watchlist(args: dict) -> dict:
        db.add_to_watchlist(
            ticker=args["ticker"],
            reason=args.get("reason"),
            alert_condition=args.get("alert_condition"),
        )
        return _text({"status": "added", "ticker": args["ticker"]})

    @tool(
        "db_remove_watchlist",
        "Remove a market from the watchlist.",
        {"ticker": {"type": "string", "description": "Market ticker to remove"}},
    )
    async def db_remove_watchlist(args: dict) -> dict:
        db.remove_from_watchlist(args["ticker"])
        return _text({"status": "removed", "ticker": args["ticker"]})

    return [
        db_query,
        db_log_prediction,
        db_resolve_predictions,
        db_get_session_state,
        db_add_watchlist,
        db_remove_watchlist,
    ]
