"""Unified MCP tool factories for market access and database."""

from __future__ import annotations

import json
from typing import Any

from claude_agent_sdk import tool

from .config import TradingConfig
from .database import AgentDatabase
from .kalshi_client import KalshiAPIClient
from .polymarket_client import PolymarketAPIClient

# Map agent action+side to Polymarket intent
_PM_INTENT_MAP = {
    ("buy", "yes"): "ORDER_INTENT_BUY_LONG",
    ("sell", "yes"): "ORDER_INTENT_SELL_LONG",
    ("buy", "no"): "ORDER_INTENT_BUY_SHORT",
    ("sell", "no"): "ORDER_INTENT_SELL_SHORT",
}

# Map Polymarket intent back to action+side for audit
_PM_INTENT_REVERSE = {v: k for k, v in _PM_INTENT_MAP.items()}


def _text(data: Any) -> dict:
    """Wrap data as MCP text content."""
    return {"content": [{"type": "text", "text": json.dumps(data, default=str)}]}


def _cents_to_usd(cents: int) -> str:
    """Convert price in cents (1-99) to USD string for Polymarket."""
    return f"{cents / 100:.2f}"


def _require_exchange(args: dict, polymarket: PolymarketAPIClient | None) -> str:
    """Validate and return exchange param. Raises ValueError if invalid."""
    exchange = args.get("exchange", "").lower()
    if exchange not in ("kalshi", "polymarket"):
        raise ValueError("exchange must be 'kalshi' or 'polymarket'")
    if exchange == "polymarket" and polymarket is None:
        raise ValueError("Polymarket is not enabled in this configuration")
    return exchange


def create_market_tools(
    kalshi: KalshiAPIClient,
    polymarket: PolymarketAPIClient | None,
    config: TradingConfig,
) -> list:
    """Unified market tools. Exchange param routes to correct client."""

    @tool(
        "search_markets",
        "Search markets by keyword, status, or event. Omit exchange to search both platforms.",
        {
            "exchange": {
                "type": "string",
                "description": "'kalshi' or 'polymarket'. Omit to search both.",
                "optional": True,
            },
            "query": {
                "type": "string",
                "description": "Search keyword",
                "optional": True,
            },
            "status": {
                "type": "string",
                "description": "Filter: open, closed, settled",
                "optional": True,
            },
            "event_id": {
                "type": "string",
                "description": "Filter by event ticker/slug",
                "optional": True,
            },
            "limit": {
                "type": "integer",
                "description": "Max results per exchange (default 50)",
                "optional": True,
            },
        },
    )
    async def search_markets(args: dict) -> dict:
        exchange = args.get("exchange", "").lower()
        query = args.get("query")
        status = args.get("status")
        limit = args.get("limit", 50)
        results: dict[str, Any] = {}

        if exchange in ("kalshi", ""):
            results["kalshi"] = kalshi.search_markets(
                query=query,
                status=status,
                event_ticker=args.get("event_id"),
                limit=limit,
            )
        if exchange in ("polymarket", "") and polymarket:
            results["polymarket"] = polymarket.search_markets(
                query=query,
                status=status,
                limit=limit,
            )
        return _text(results)

    def _dispatch(args: dict, k_fn, pm_fn):
        exchange = _require_exchange(args, polymarket)
        return _text(k_fn() if exchange == "kalshi" else pm_fn())

    @tool(
        "get_market",
        "Get full details for a single market: rules, prices, volume, settlement source.",
        {
            "exchange": {"type": "string", "description": "'kalshi' or 'polymarket'"},
            "market_id": {
                "type": "string",
                "description": "Market ticker (Kalshi) or slug (Polymarket)",
            },
        },
    )
    async def get_market(args: dict) -> dict:
        mid = args["market_id"]
        return _dispatch(args, lambda: kalshi.get_market(mid), lambda: polymarket.get_market(mid))

    @tool(
        "get_orderbook",
        "Get the current orderbook: bid/ask levels, spread, depth.",
        {
            "exchange": {"type": "string", "description": "'kalshi' or 'polymarket'"},
            "market_id": {"type": "string", "description": "Market ticker or slug"},
            "depth": {
                "type": "integer",
                "description": "Price levels (default 10)",
                "optional": True,
            },
        },
    )
    async def get_orderbook(args: dict) -> dict:
        exchange = _require_exchange(args, polymarket)
        mid = args["market_id"]
        if exchange == "kalshi":
            return _text(kalshi.get_orderbook(mid, depth=args.get("depth", 10)))
        if args.get("depth", 10) <= 1:
            return _text(polymarket.get_bbo(mid))
        return _text(polymarket.get_orderbook(mid))

    @tool(
        "get_event",
        "Get an event and all its nested markets.",
        {
            "exchange": {"type": "string", "description": "'kalshi' or 'polymarket'"},
            "event_id": {"type": "string", "description": "Event ticker or slug"},
        },
    )
    async def get_event(args: dict) -> dict:
        eid = args["event_id"]
        return _dispatch(args, lambda: kalshi.get_event(eid), lambda: polymarket.get_event(eid))

    @tool(
        "get_price_history",
        "Get OHLC candlestick price history. Kalshi only — "
        "use for investigating signals and checking 24-48h trends.",
        {
            "market_id": {"type": "string", "description": "Kalshi market ticker"},
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
            "interval": {
                "type": "integer",
                "description": "Candle interval in minutes (default 60)",
                "optional": True,
            },
        },
    )
    async def get_price_history(args: dict) -> dict:
        return _text(
            kalshi.get_candlesticks(
                args["market_id"],
                start_ts=args.get("start_ts"),
                end_ts=args.get("end_ts"),
                period_interval=args.get("interval", 60),
            )
        )

    @tool(
        "get_trades",
        "Get recent trade executions. Check before placing limit orders — "
        "recent trades at your target price indicate quick fills.",
        {
            "exchange": {"type": "string", "description": "'kalshi' or 'polymarket'"},
            "market_id": {"type": "string", "description": "Market ticker or slug"},
            "limit": {
                "type": "integer",
                "description": "Max trades (default 50)",
                "optional": True,
            },
        },
    )
    async def get_trades(args: dict) -> dict:
        mid, limit = args["market_id"], args.get("limit", 50)
        return _dispatch(
            args,
            lambda: kalshi.get_trades(mid, limit=limit),
            lambda: polymarket.get_trades(mid, limit=limit),
        )

    @tool(
        "get_portfolio",
        "Get portfolio: balances, positions, optional fills/settlements. "
        "Omit exchange to get both platforms combined.",
        {
            "exchange": {
                "type": "string",
                "description": "'kalshi' or 'polymarket'. Omit for both.",
                "optional": True,
            },
            "include_fills": {
                "type": "boolean",
                "description": "Include recent fills (Kalshi only, default false)",
                "optional": True,
            },
            "include_settlements": {
                "type": "boolean",
                "description": "Include settlements (Kalshi only, default false)",
                "optional": True,
            },
        },
    )
    async def get_portfolio(args: dict) -> dict:
        exchange = args.get("exchange", "").lower()
        data: dict[str, Any] = {}

        if exchange in ("kalshi", ""):
            kalshi_data: dict[str, Any] = {
                "balance": kalshi.get_balance(),
                "positions": kalshi.get_positions(),
            }
            if args.get("include_fills"):
                kalshi_data["fills"] = kalshi.get_fills()
            if args.get("include_settlements"):
                kalshi_data["settlements"] = kalshi.get_settlements()
            data["kalshi"] = kalshi_data

        if exchange in ("polymarket", "") and polymarket:
            data["polymarket"] = {
                "balance": polymarket.get_balance(),
                "positions": polymarket.get_positions(),
            }
        return _text(data)

    @tool(
        "get_orders",
        "List resting orders. Check after placing to verify status. "
        "Omit exchange for all platforms.",
        {
            "exchange": {
                "type": "string",
                "description": "'kalshi' or 'polymarket'. Omit for all.",
                "optional": True,
            },
            "market_id": {
                "type": "string",
                "description": "Filter by market ticker/slug",
                "optional": True,
            },
            "status": {
                "type": "string",
                "description": "Order status filter (default 'resting')",
                "optional": True,
            },
        },
    )
    async def get_orders(args: dict) -> dict:
        exchange = args.get("exchange", "").lower()
        status = args.get("status", "resting")
        data: dict[str, Any] = {}

        if exchange in ("kalshi", ""):
            data["kalshi"] = kalshi.get_orders(ticker=args.get("market_id"), status=status)
        if exchange in ("polymarket", "") and polymarket:
            data["polymarket"] = polymarket.get_orders(
                market_slug=args.get("market_id"), status=status
            )
        return _text(data)

    @tool(
        "place_order",
        "Place order(s) on an exchange. Pass multiple orders for batch execution. "
        "All prices in cents (1-99), action is 'buy'/'sell', side is 'yes'/'no'. "
        f"Kalshi max ${config.kalshi_max_position_usd}/position, "
        f"Polymarket max ${config.polymarket_max_position_usd}/position.",
        {
            "exchange": {"type": "string", "description": "'kalshi' or 'polymarket'"},
            "orders": {
                "type": "array",
                "description": (
                    "Array of orders. Each: {market_id, action, side, quantity, "
                    "price_cents, type?}. type defaults to 'limit'."
                ),
            },
        },
    )
    async def place_order(args: dict) -> dict:
        exchange = _require_exchange(args, polymarket)
        orders = args.get("orders", [])
        if not orders:
            raise ValueError("orders array cannot be empty")

        if exchange == "kalshi":
            if len(orders) == 1:
                o = orders[0]
                return _text(
                    kalshi.create_order(
                        ticker=o["market_id"],
                        action=o["action"],
                        side=o["side"],
                        count=o["quantity"],
                        order_type=o.get("type", "limit"),
                        yes_price=o["price_cents"] if o["side"] == "yes" else None,
                        no_price=o["price_cents"] if o["side"] == "no" else None,
                    )
                )
            # Batch create for multiple orders
            batch = []
            for o in orders:
                batch.append(
                    {
                        "ticker": o["market_id"],
                        "action": o["action"],
                        "side": o["side"],
                        "count": o["quantity"],
                        "type": o.get("type", "limit"),
                        **(
                            {"yes_price": o["price_cents"]}
                            if o["side"] == "yes"
                            else {"no_price": o["price_cents"]}
                        ),
                    }
                )
            return _text(kalshi.batch_create_orders(batch))

        # Polymarket
        if len(orders) > 1:
            raise ValueError("Polymarket does not support batch orders — submit one at a time")
        o = orders[0]
        intent_key = (o["action"].lower(), o["side"].lower())
        intent = _PM_INTENT_MAP.get(intent_key)
        if not intent:
            raise ValueError(
                f"Invalid action+side: {o['action']}+{o['side']}. Use buy/sell + yes/no."
            )
        return _text(
            polymarket.create_order(
                slug=o["market_id"],
                intent=intent,
                price=_cents_to_usd(o["price_cents"]),
                quantity=o["quantity"],
                order_type=o.get("type", "ORDER_TYPE_LIMIT"),
            )
        )

    @tool(
        "amend_order",
        "Amend a resting order's price or quantity. Kalshi only — preserves FIFO queue position.",
        {
            "order_id": {"type": "string", "description": "Order ID to amend"},
            "price_cents": {
                "type": "integer",
                "description": "New price in cents",
                "optional": True,
            },
            "quantity": {
                "type": "integer",
                "description": "New quantity",
                "optional": True,
            },
        },
    )
    async def amend_order(args: dict) -> dict:
        return _text(
            kalshi.amend_order(
                args["order_id"],
                price=args.get("price_cents"),
                count=args.get("quantity"),
            )
        )

    @tool(
        "cancel_order",
        "Cancel order(s). Pass multiple IDs for batch cancel.",
        {
            "exchange": {"type": "string", "description": "'kalshi' or 'polymarket'"},
            "order_ids": {
                "type": "array",
                "description": "Array of order ID strings to cancel",
            },
        },
    )
    async def cancel_order(args: dict) -> dict:
        exchange = _require_exchange(args, polymarket)
        ids = args.get("order_ids", [])
        if not ids:
            raise ValueError("order_ids cannot be empty")

        if exchange == "kalshi":
            if len(ids) == 1:
                return _text(kalshi.cancel_order(ids[0]))
            return _text(kalshi.batch_cancel_orders(ids))

        return _text([polymarket.cancel_order(oid) for oid in ids])

    return [
        search_markets,
        get_market,
        get_orderbook,
        get_event,
        get_price_history,
        get_trades,
        get_portfolio,
        get_orders,
        place_order,
        amend_order,
        cancel_order,
    ]


def create_db_tools(db: AgentDatabase) -> list:
    """Database tools for agent persistence."""

    @tool(
        "db_query",
        "Execute a read-only SQL SELECT against the agent database. "
        "Tables: market_snapshots, events, signals, trades, predictions, "
        "portfolio_snapshots, sessions, watchlist.",
        {
            "sql": {"type": "string", "description": "SQL SELECT query"},
        },
    )
    async def db_query(args: dict) -> dict:
        return _text(db.query(args["sql"]))

    @tool(
        "db_log_prediction",
        "Record a probability prediction for calibration tracking.",
        {
            "market_ticker": {"type": "string", "description": "Market ticker or slug"},
            "exchange": {
                "type": "string",
                "description": "'kalshi' or 'polymarket'",
                "optional": True,
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
        "db_add_watchlist",
        "Add a market to the watchlist for tracking across sessions.",
        {
            "market_id": {"type": "string", "description": "Market ticker or slug"},
            "exchange": {"type": "string", "description": "'kalshi' or 'polymarket'"},
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
            ticker=args["market_id"],
            exchange=args.get("exchange", "kalshi"),
            reason=args.get("reason"),
            alert_condition=args.get("alert_condition"),
        )
        return _text({"status": "added", "market_id": args["market_id"]})

    @tool(
        "db_remove_watchlist",
        "Remove a market from the watchlist.",
        {
            "market_id": {"type": "string", "description": "Market ticker or slug"},
            "exchange": {
                "type": "string",
                "description": "'kalshi' or 'polymarket'. Omit to remove from all.",
                "optional": True,
            },
        },
    )
    async def db_remove_watchlist(args: dict) -> dict:
        exchange = args.get("exchange")
        if exchange:
            db.remove_from_watchlist(args["market_id"], exchange=exchange)
        else:
            db.remove_from_watchlist(args["market_id"])
        return _text({"status": "removed", "market_id": args["market_id"]})

    return [
        db_query,
        db_log_prediction,
        db_add_watchlist,
        db_remove_watchlist,
    ]
