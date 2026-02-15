"""Unified MCP tool factories for market access and database."""

from __future__ import annotations

import json
from typing import Any

from claude_agent_sdk import tool

from .database import AgentDatabase
from .kalshi_client import KalshiAPIClient
from .polymarket_client import PolymarketAPIClient


def _text(data: Any) -> dict:
    """Wrap data as MCP text content."""
    return {"content": [{"type": "text", "text": json.dumps(data, default=str)}]}


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
) -> list:
    """Unified market tools (read-only). Exchange param routes to correct client."""

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
        exchange = _require_exchange(args, polymarket)
        mid = args["market_id"]
        if exchange == "kalshi":
            return _text(kalshi.get_market(mid))
        assert polymarket is not None
        return _text(polymarket.get_market(mid))

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
        assert polymarket is not None
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
        exchange = _require_exchange(args, polymarket)
        eid = args["event_id"]
        if exchange == "kalshi":
            return _text(kalshi.get_event(eid))
        assert polymarket is not None
        return _text(polymarket.get_event(eid))

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
        "Get recent trade executions. Check activity levels and recent prices.",
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
        exchange = _require_exchange(args, polymarket)
        mid, limit = args["market_id"], args.get("limit", 50)
        if exchange == "kalshi":
            return _text(kalshi.get_trades(mid, limit=limit))
        assert polymarket is not None
        return _text(polymarket.get_trades(mid, limit=limit))

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
        "List resting orders. Omit exchange for all platforms.",
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

    return [
        search_markets,
        get_market,
        get_orderbook,
        get_event,
        get_price_history,
        get_trades,
        get_portfolio,
        get_orders,
    ]


def create_db_tools(
    db: AgentDatabase,
    session_id: str,
    recommendation_ttl_minutes: int = 60,
) -> list:
    """Database tools for agent persistence."""

    @tool(
        "log_prediction",
        "Record a probability prediction for calibration tracking.",
        {
            "market_ticker": {"type": "string", "description": "Market ticker or slug"},
            "prediction": {
                "type": "number",
                "description": "Predicted probability (0.0 to 1.0)",
            },
            "context": {
                "type": "string",
                "description": "Exchange, current price, methodology, notes (freeform)",
                "optional": True,
            },
        },
    )
    async def log_prediction(args: dict) -> dict:
        pred_id = db.log_prediction(
            market_ticker=args["market_ticker"],
            prediction=args["prediction"],
            notes=args.get("context"),
        )
        return _text({"prediction_id": pred_id, "status": "logged"})

    @tool(
        "recommend_trade",
        "Record a trade recommendation for review and execution by a separate system.",
        {
            "exchange": {"type": "string", "description": "'kalshi' or 'polymarket'"},
            "market_id": {
                "type": "string",
                "description": "Market ticker (Kalshi) or slug (Polymarket)",
            },
            "market_title": {"type": "string", "description": "Human-readable market title"},
            "action": {"type": "string", "description": "'buy' or 'sell'"},
            "side": {"type": "string", "description": "'yes' or 'no'"},
            "quantity": {"type": "integer", "description": "Number of contracts"},
            "price_cents": {
                "type": "integer",
                "description": "Limit price in cents (1-99)",
            },
            "thesis": {
                "type": "string",
                "description": "1-3 sentences explaining reasoning and opportunity",
            },
            "estimated_edge_pct": {
                "type": "number",
                "description": "Fee-adjusted edge percentage",
            },
            "kelly_fraction": {
                "type": "number",
                "description": "Kelly fraction used for sizing",
                "optional": True,
            },
            "confidence": {
                "type": "string",
                "description": "high, medium, or low",
                "optional": True,
            },
            "signal_id": {
                "type": "integer",
                "description": "ID of the signal that prompted this recommendation",
                "optional": True,
            },
            "group_id": {
                "type": "string",
                "description": "Group ID for paired arb legs (same group_id = same trade)",
                "optional": True,
            },
            "leg_index": {
                "type": "integer",
                "description": "Leg index within a group (0, 1, ...)",
                "optional": True,
            },
            "equivalence_notes": {
                "type": "string",
                "description": "How you verified the markets settle identically (for arbs)",
                "optional": True,
            },
        },
    )
    async def recommend_trade(args: dict) -> dict:
        # Forward all matching args; add session_id + ttl + default leg_index
        forwarded = (
            "exchange", "market_id", "market_title", "action", "side",
            "quantity", "price_cents", "thesis", "estimated_edge_pct",
            "kelly_fraction", "confidence", "signal_id", "group_id",
            "equivalence_notes",
        )  # fmt: skip
        kwargs = {k: args[k] for k in forwarded if k in args}
        rec_id = db.log_recommendation(
            session_id=session_id,
            ttl_minutes=recommendation_ttl_minutes,
            leg_index=args.get("leg_index", 0),
            **kwargs,
        )
        rec = db.get_recommendation(rec_id)
        return _text(
            {
                "recommendation_id": rec_id,
                "status": "pending",
                "expires_at": rec["expires_at"] if rec else None,
            }
        )

    return [log_prediction, recommend_trade]
