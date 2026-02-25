"""Unified MCP tool factories for market access and database."""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

from claude_agent_sdk import tool

from .config import TradingConfig
from .constants import (
    ACTION_BUY,
    ACTION_SELL,
    BINARY_PAYOUT_CENTS,
    EXCHANGE_KALSHI,
    SIDE_NO,
    SIDE_YES,
    STATUS_PENDING,
    STRATEGY_MANUAL,
)
from .database import AgentDatabase
from .fees import best_price_and_depth, kalshi_fee
from .kalshi_client import KalshiAPIClient

logger = logging.getLogger(__name__)


def _text(data: Any) -> dict:
    """Wrap data as MCP text content."""
    return {"content": [{"type": "text", "text": json.dumps(data, default=str)}]}


def create_market_tools(kalshi: KalshiAPIClient) -> list:
    """Kalshi market tools (read-only, 5 tools)."""

    @tool(
        "get_market",
        "Get full details for a single market: rules, prices, volume, settlement source.",
        {
            "market_id": {
                "type": "string",
                "description": "Kalshi market ticker",
            },
        },
    )
    async def get_market(args: dict) -> dict:
        return _text(await kalshi.get_market(args["market_id"]))

    @tool(
        "get_orderbook",
        "Get the current orderbook: bid/ask levels, spread, depth.",
        {
            "market_id": {"type": "string", "description": "Kalshi market ticker"},
            "depth": {
                "type": "integer",
                "description": "Price levels (default 10)",
                "optional": True,
            },
        },
    )
    async def get_orderbook(args: dict) -> dict:
        return _text(await kalshi.get_orderbook(args["market_id"], depth=args.get("depth", 10)))

    @tool(
        "get_trades",
        "Get recent trade executions. Check activity levels and recent prices.",
        {
            "market_id": {"type": "string", "description": "Kalshi market ticker"},
            "limit": {
                "type": "integer",
                "description": "Max trades (default 50)",
                "optional": True,
            },
        },
    )
    async def get_trades(args: dict) -> dict:
        return _text(await kalshi.get_trades(args["market_id"], limit=args.get("limit", 50)))

    @tool(
        "get_portfolio",
        "Get portfolio: balances, positions, optional fills/settlements.",
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
        data: dict[str, Any] = {
            "balance": await kalshi.get_balance(),
            "positions": await kalshi.get_positions(),
        }
        if args.get("include_fills"):
            data["fills"] = await kalshi.get_fills()
        if args.get("include_settlements"):
            data["settlements"] = await kalshi.get_settlements()
        return _text(data)

    @tool(
        "get_orders",
        "List resting orders.",
        {
            "market_id": {
                "type": "string",
                "description": "Filter by market ticker",
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
        return _text(
            await kalshi.get_orders(
                ticker=args.get("market_id"), status=args.get("status", "resting")
            )
        )

    return [get_market, get_orderbook, get_trades, get_portfolio, get_orders]


# ── Recommendation helpers ──────────────────────────────────────────


def _apply_manual_direction(
    enriched_legs: list[dict[str, Any]], input_legs: list[dict[str, Any]]
) -> str | None:
    """Assign action/side/price/depth from agent-specified inputs for manual strategy.

    Mutates enriched_legs in-place. Returns error string or None on success.
    """
    for enriched, raw in zip(enriched_legs, input_legs, strict=True):
        action = raw.get("action")
        side = raw.get("side")
        quantity = raw.get("quantity")
        if not action or not side:
            return (
                f"Manual strategy requires action+side for each leg "
                f"(missing on {raw['market_id']})"
            )
        if not quantity or quantity < 1:
            return (
                f"Manual strategy requires quantity >= 1 for each leg "
                f"(missing on {raw['market_id']})"
            )
        enriched["action"] = action
        enriched["side"] = side
        enriched["quantity"] = quantity
        # For buys: use ask price on the specified side
        # For sells: use bid price on the specified side
        if action == ACTION_BUY:
            enriched["price_cents"] = enriched.get(f"{side}_ask")
        else:
            enriched["price_cents"] = enriched.get(f"{side}_bid")
        enriched["depth"] = enriched.get(f"{side}_depth", 0)
        if not enriched["price_cents"]:
            return f"No executable {side} price for {raw['market_id']}"
    return None


def _assign_maker_taker(enriched_legs: list[dict[str, Any]]) -> None:
    """Assign maker/taker roles by depth (shallowest = maker). Mutates in-place."""
    sorted_legs = sorted(enriched_legs, key=lambda lg: lg.get("depth", 0))
    sorted_legs[0]["is_maker"] = True
    for leg in sorted_legs[1:]:
        leg["is_maker"] = False


def _validate_position_limits(
    enriched_legs: list[dict[str, Any]],
    contracts: int,
    cfg: TradingConfig,
) -> str | None:
    """Check fee-inclusive cost per leg against position limits.

    Returns error string or None on success.
    """
    for leg in enriched_legs:
        qty = leg.get("quantity", contracts)
        cost = leg["price_cents"] * qty / 100.0
        fee = kalshi_fee(qty, leg["price_cents"], maker=leg.get("is_maker", False))
        cost_with_fee = cost + fee
        if cost_with_fee > cfg.kalshi_max_position_usd:
            return (
                f"Kalshi leg ${cost_with_fee:.2f} (incl ${fee:.4f} fee) "
                f"exceeds limit ${cfg.kalshi_max_position_usd:.2f}"
            )
    return None


def _validate_aggregate_limits(
    enriched_legs: list[dict[str, Any]],
    cfg: TradingConfig,
) -> str | None:
    """Check total exposure doesn't exceed platform limits."""
    total = sum(leg["price_cents"] * leg.get("quantity", 0) / 100.0 for leg in enriched_legs)
    if total > cfg.kalshi_max_position_usd:
        return (
            f"Aggregate Kalshi exposure ${total:.2f} "
            f"exceeds limit ${cfg.kalshi_max_position_usd:.2f}"
        )
    return None


def _build_db_legs(enriched_legs: list[dict[str, Any]], contracts: int) -> list[dict[str, Any]]:
    """Build leg dicts for DB storage from enriched legs."""
    return [
        {
            "exchange": leg["exchange"],
            "market_id": leg["market_id"],
            "market_title": leg["market_title"],
            "action": leg["action"],
            "side": leg["side"],
            "quantity": leg.get("quantity", contracts),
            "price_cents": leg["price_cents"],
            "is_maker": leg.get("is_maker", False),
            "orderbook_snapshot_json": json.dumps(
                {
                    "yes_ask": leg.get("yes_ask"),
                    "no_ask": leg.get("no_ask"),
                    "yes_depth": leg.get("yes_depth"),
                    "no_depth": leg.get("no_depth"),
                    "close_time": leg.get("close_time"),
                }
            ),
        }
        for leg in enriched_legs
    ]


def _build_response_legs(enriched_legs: list[dict[str, Any]], contracts: int) -> list[dict]:
    """Build leg dicts for the MCP response."""
    return [
        {
            "exchange": leg["exchange"],
            "market_id": leg["market_id"],
            "market_title": leg["market_title"],
            "action": leg["action"],
            "side": leg["side"],
            "quantity": leg.get("quantity", contracts),
            "price_cents": leg["price_cents"],
            "is_maker": leg.get("is_maker", False),
        }
        for leg in enriched_legs
    ]


# ── DB tool factory ─────────────────────────────────────────────────


def create_db_tools(
    db: AgentDatabase,
    session_id: str,
    kalshi: KalshiAPIClient,
    trading_config: Any = None,
    recommendation_ttl_minutes: int = 60,
) -> list:
    """Database tools for agent persistence.

    Exchange clients are needed to fetch orderbooks at recommendation time
    for auto-pricing and balanced sizing.
    """
    cfg: TradingConfig = trading_config or TradingConfig()

    @tool(
        "recommend_trade",
        (
            "Record a trade recommendation. Specify action, side, and quantity per leg. "
            "System validates position limits and computes fees."
        ),
        {
            "type": "object",
            "required": ["thesis", "legs"],
            "properties": {
                "thesis": {
                    "type": "string",
                    "description": "Explain the semantic reasoning for this trade",
                    "minLength": 10,
                },
                "equivalence_notes": {
                    "type": "string",
                    "description": "Explain the relationship between these markets",
                },
                "legs": {
                    "type": "array",
                    "description": "Markets to trade (1+ required)",
                    "minItems": 1,
                    "maxItems": 10,
                    "items": {
                        "type": "object",
                        "required": ["market_id", "action", "side", "quantity"],
                        "properties": {
                            "market_id": {
                                "type": "string",
                                "minLength": 1,
                            },
                            "action": {
                                "type": "string",
                                "enum": [ACTION_BUY, ACTION_SELL],
                            },
                            "side": {
                                "type": "string",
                                "enum": [SIDE_YES, SIDE_NO],
                            },
                            "quantity": {
                                "type": "integer",
                                "minimum": 1,
                            },
                        },
                    },
                },
            },
        },
    )
    async def recommend_trade(args: dict) -> dict:
        legs_input = args.get("legs", [])

        if not legs_input:
            return _text({"error": "Requires at least 1 leg"})

        # ── Batch-fetch market data + concurrent orderbooks ────
        all_tickers = [leg["market_id"] for leg in legs_input]

        # Single batch call for titles/close_times
        market_map: dict[str, dict[str, Any]] = {}
        try:
            markets_resp = await kalshi.search_markets(tickers=",".join(all_tickers), limit=1000)
            for m in markets_resp.get("markets", []):
                t = m.get("ticker")
                if t:
                    market_map[t] = m
        except Exception:
            logger.debug("Batch market fetch failed, falling back to ticker as title")

        # Concurrent orderbook fetches
        ob_results = await asyncio.gather(
            *[kalshi.get_orderbook(leg["market_id"]) for leg in legs_input],
            return_exceptions=True,
        )

        enriched_legs: list[dict[str, Any]] = []
        for i, leg in enumerate(legs_input):
            market_id = leg["market_id"]

            ob = ob_results[i]
            if isinstance(ob, BaseException):
                return _text({"error": f"Failed to fetch orderbook for {market_id}: {ob}"})

            mkt = market_map.get(market_id, {})
            title = str(mkt.get("title", mkt.get("question", market_id)))
            close_time = mkt.get("close_time") or mkt.get("expected_expiration_time")

            yes_price, yes_depth = best_price_and_depth(ob, SIDE_YES)
            no_price, no_depth = best_price_and_depth(ob, SIDE_NO)

            enriched_legs.append(
                {
                    "exchange": EXCHANGE_KALSHI,
                    "market_id": market_id,
                    "market_title": title,
                    "close_time": str(close_time) if close_time else None,
                    "orderbook": ob,
                    "leg_index": i,
                    "yes_ask": yes_price,
                    "yes_depth": yes_depth,
                    "no_ask": no_price,
                    "no_depth": no_depth,
                    "yes_bid": (BINARY_PAYOUT_CENTS - no_price) if no_price else None,
                    "no_bid": (BINARY_PAYOUT_CENTS - yes_price) if yes_price else None,
                }
            )

        # ── Apply direction and validate ─────────────────────────
        direction_error = _apply_manual_direction(enriched_legs, legs_input)
        if direction_error:
            return _text({"error": direction_error})

        _assign_maker_taker(enriched_legs)

        # Validate position limits (aggregate + per-leg)
        limit_error = _validate_aggregate_limits(enriched_legs, cfg)
        if limit_error:
            return _text({"error": limit_error})
        limit_error = _validate_position_limits(enriched_legs, 0, cfg)
        if limit_error:
            return _text({"error": limit_error})

        # Compute totals for response
        total_cost = 0.0
        total_fees = 0.0
        for leg in enriched_legs:
            qty = leg["quantity"]
            total_cost += leg["price_cents"] * qty / 100.0
            total_fees += kalshi_fee(qty, leg["price_cents"], maker=leg.get("is_maker", False))

        # Store and respond
        group_id, expires_at = db.log_recommendation_group(
            session_id=session_id,
            thesis=args.get("thesis"),
            estimated_edge_pct=0.0,
            equivalence_notes=args.get("equivalence_notes"),
            legs=_build_db_legs(enriched_legs, 0),
            ttl_minutes=recommendation_ttl_minutes,
            total_exposure_usd=total_cost,
            computed_edge_pct=0.0,
            computed_fees_usd=round(total_fees, 4),
            strategy=STRATEGY_MANUAL,
        )

        return _text(
            {
                "group_id": group_id,
                "status": STATUS_PENDING,
                "expires_at": expires_at,
                "computed": {
                    "total_cost_usd": round(total_cost, 2),
                    "total_fees_usd": round(total_fees, 4),
                },
                "legs": _build_response_legs(enriched_legs, 0),
            }
        )

    return [recommend_trade]
