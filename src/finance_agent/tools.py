"""Unified MCP tool factories for market access and database."""

from __future__ import annotations

import json
from typing import Any

from claude_agent_sdk import tool

from .config import TradingConfig
from .database import AgentDatabase
from .fees import best_price_and_depth, compute_arb_edge, kalshi_fee
from .kalshi_client import KalshiAPIClient


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


def _validate_leg_prices(enriched_legs: list[dict[str, Any]]) -> str | None:
    """Check all legs have executable prices in the 1-99c range.

    Returns error string or None on success.
    """
    for leg in enriched_legs:
        if not leg.get("price_cents") or not (1 <= leg["price_cents"] <= 99):
            return (
                f"No executable price for {leg['market_id']} "
                f"({leg.get('side', '?')} side) — orderbook may be empty"
            )
    return None


def _determine_direction_bracket(enriched_legs: list[dict[str, Any]]) -> str | None:
    """Assign action/side/price/depth to an N-leg bracket arb (same exchange).

    Compares buying all YES vs all NO, picks the profitable direction.
    Mutates legs in-place. Returns error string or None on success.
    """
    yes_prices = [leg.get("yes_ask") for leg in enriched_legs]
    no_prices = [leg.get("no_ask") for leg in enriched_legs]

    if any(p is None for p in yes_prices):
        missing = [
            leg["market_id"] for leg, p in zip(enriched_legs, yes_prices, strict=True) if p is None
        ]
        return f"Empty YES orderbook for: {', '.join(missing)}"

    yes_cost = sum(yes_prices)  # type: ignore[arg-type]
    buy_yes_edge = 100 - yes_cost

    if all(p is not None for p in no_prices):
        no_cost = sum(no_prices)  # type: ignore[arg-type]
        buy_no_edge = 100 - no_cost
    else:
        no_cost = None
        buy_no_edge = -999

    if buy_yes_edge > 0 and buy_yes_edge >= buy_no_edge:
        for leg in enriched_legs:
            leg["action"], leg["side"] = "buy", "yes"
            leg["price_cents"] = leg["yes_ask"]
            leg["depth"] = leg["yes_depth"]
    elif buy_no_edge > 0:
        for leg in enriched_legs:
            leg["action"], leg["side"] = "buy", "no"
            leg["price_cents"] = leg["no_ask"]
            leg["depth"] = leg["no_depth"]
    else:
        return (
            f"No bracket arb edge at executable prices: "
            f"YES sum {yes_cost}c"
            + (f", NO sum {no_cost}c" if no_cost is not None else "")
            + " (need sum < 100c on one side)"
        )

    return _validate_leg_prices(enriched_legs)


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
        # For sells: use bid price on the specified side (inverse)
        if action == "buy":
            enriched["price_cents"] = enriched.get(f"{side}_ask")
        else:
            # sell YES → someone buys YES from us → yes_bid is the executable price
            enriched["price_cents"] = enriched.get(f"{side}_bid")
        enriched["depth"] = enriched.get(f"{side}_depth", 0)
        if not enriched["price_cents"]:
            return f"No executable {side} price for {raw['market_id']}"
    return None


def _validate_position_limits(
    enriched_legs: list[dict[str, Any]],
    contracts: int,
    cfg: TradingConfig,
) -> str | None:
    """Check fee-inclusive cost per leg against exchange position limits.

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


def _build_recommendation_response(
    *,
    enriched_legs: list[dict[str, Any]],
    contracts: int,
    cost_per_pair_usd: float,
    edge_result: dict[str, Any],
    args: dict[str, Any],
    db: AgentDatabase,
    session_id: str,
    recommendation_ttl_minutes: int,
    total_exposure: float,
) -> dict:
    """Store recommendation to DB and build the MCP response."""
    db_legs = []
    for leg in enriched_legs:
        ob_snapshot = {
            "yes_ask": leg.get("yes_ask"),
            "no_ask": leg.get("no_ask"),
            "yes_depth": leg.get("yes_depth"),
            "no_depth": leg.get("no_depth"),
        }
        db_legs.append(
            {
                "exchange": leg["exchange"],
                "market_id": leg["market_id"],
                "market_title": leg["market_title"],
                "action": leg["action"],
                "side": leg["side"],
                "quantity": leg.get("quantity", contracts),
                "price_cents": leg["price_cents"],
                "is_maker": leg.get("is_maker", False),
                "orderbook_snapshot_json": json.dumps(ob_snapshot),
            }
        )

    group_id, expires_at = db.log_recommendation_group(
        session_id=session_id,
        thesis=args.get("thesis"),
        estimated_edge_pct=edge_result["net_edge_pct"],
        equivalence_notes=args.get("equivalence_notes"),
        legs=db_legs,
        ttl_minutes=recommendation_ttl_minutes,
        total_exposure_usd=total_exposure,
        computed_edge_pct=edge_result["net_edge_pct"],
        computed_fees_usd=edge_result["total_fees_usd"],
    )

    return _text(
        {
            "group_id": group_id,
            "status": "pending",
            "expires_at": expires_at,
            "computed": {
                "contracts_per_leg": contracts,
                "cost_per_pair_usd": round(cost_per_pair_usd, 4),
                "total_cost_usd": round(contracts * cost_per_pair_usd, 2),
                "gross_edge_usd": edge_result["gross_edge_usd"],
                "total_fees_usd": edge_result["total_fees_usd"],
                "net_edge_usd": edge_result["net_edge_usd"],
                "net_edge_pct": edge_result["net_edge_pct"],
                "fee_breakdown": edge_result["fee_breakdown"],
            },
            "legs": [
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
            ],
        }
    )


def _build_manual_recommendation_response(
    *,
    enriched_legs: list[dict[str, Any]],
    args: dict[str, Any],
    db: AgentDatabase,
    session_id: str,
    recommendation_ttl_minutes: int,
) -> dict:
    """Store a manual recommendation to DB and build the MCP response."""
    db_legs = []
    total_cost = 0.0
    total_fees = 0.0
    for leg in enriched_legs:
        qty = leg["quantity"]
        fee = kalshi_fee(qty, leg["price_cents"], maker=leg.get("is_maker", False))
        cost = leg["price_cents"] * qty / 100.0
        total_cost += cost
        total_fees += fee

        ob_snapshot = {
            "yes_ask": leg.get("yes_ask"),
            "no_ask": leg.get("no_ask"),
            "yes_depth": leg.get("yes_depth"),
            "no_depth": leg.get("no_depth"),
        }
        db_legs.append(
            {
                "exchange": leg["exchange"],
                "market_id": leg["market_id"],
                "market_title": leg["market_title"],
                "action": leg["action"],
                "side": leg["side"],
                "quantity": qty,
                "price_cents": leg["price_cents"],
                "is_maker": leg.get("is_maker", False),
                "orderbook_snapshot_json": json.dumps(ob_snapshot),
            }
        )

    group_id, expires_at = db.log_recommendation_group(
        session_id=session_id,
        thesis=args.get("thesis"),
        estimated_edge_pct=0.0,
        equivalence_notes=args.get("equivalence_notes"),
        legs=db_legs,
        ttl_minutes=recommendation_ttl_minutes,
        total_exposure_usd=total_cost,
        computed_edge_pct=0.0,
        computed_fees_usd=round(total_fees, 4),
    )

    return _text(
        {
            "group_id": group_id,
            "status": "pending",
            "expires_at": expires_at,
            "strategy": "manual",
            "computed": {
                "total_cost_usd": round(total_cost, 2),
                "total_fees_usd": round(total_fees, 4),
            },
            "legs": [
                {
                    "exchange": leg["exchange"],
                    "market_id": leg["market_id"],
                    "market_title": leg["market_title"],
                    "action": leg["action"],
                    "side": leg["side"],
                    "quantity": leg["quantity"],
                    "price_cents": leg["price_cents"],
                    "is_maker": leg.get("is_maker", False),
                }
                for leg in enriched_legs
            ],
        }
    )


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

    async def _fetch_orderbook(market_id: str) -> dict[str, Any]:
        return await kalshi.get_orderbook(market_id)

    async def _fetch_market_title(market_id: str) -> str:
        market = await kalshi.get_market(market_id)
        if isinstance(market, dict):
            inner = market.get("market", market)
            return str(inner.get("title", inner.get("question", market_id)))
        return market_id

    @tool(
        "recommend_trade",
        (
            "Record a trade recommendation. Two strategies: 'bracket' for mutually exclusive "
            "events (auto-computes direction, sizing, edge), 'manual' for correlated market "
            "trades (you specify action, side, quantity per leg)."
        ),
        {
            "type": "object",
            "required": ["thesis", "strategy", "legs"],
            "properties": {
                "thesis": {
                    "type": "string",
                    "description": "1-3 sentences explaining the opportunity",
                    "minLength": 10,
                },
                "equivalence_notes": {
                    "type": "string",
                    "description": "Explain the relationship between these markets",
                },
                "strategy": {
                    "type": "string",
                    "enum": ["bracket", "manual"],
                    "description": (
                        "'bracket' for mutually exclusive events (auto-computed), "
                        "'manual' for correlated/calendar trades (agent-specified)"
                    ),
                },
                "total_exposure_usd": {
                    "type": "number",
                    "description": "Total capital to deploy (required for bracket, ignored for manual)",
                    "minimum": 1,
                    "maximum": 1000,
                },
                "legs": {
                    "type": "array",
                    "description": "Markets to trade (2+ required)",
                    "minItems": 2,
                    "maxItems": 10,
                    "items": {
                        "type": "object",
                        "required": ["market_id"],
                        "properties": {
                            "market_id": {
                                "type": "string",
                                "minLength": 1,
                            },
                            "action": {
                                "type": "string",
                                "enum": ["buy", "sell"],
                                "description": "Required for manual strategy",
                            },
                            "side": {
                                "type": "string",
                                "enum": ["yes", "no"],
                                "description": "Required for manual strategy",
                            },
                            "quantity": {
                                "type": "integer",
                                "description": "Contracts per leg (required for manual strategy)",
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
        strategy = args.get("strategy", "bracket")
        total_exposure = args.get("total_exposure_usd", 0)

        # ── Validation ──────────────────────────────────────────
        errors: list[str] = []
        if len(legs_input) < 2:
            errors.append("Requires 2+ legs")

        if strategy == "bracket" and not total_exposure:
            errors.append("Bracket strategy requires total_exposure_usd")

        if errors:
            return _text({"error": "; ".join(errors)})

        # ── Fetch orderbooks and market titles ──────────────────
        enriched_legs: list[dict[str, Any]] = []
        for i, leg in enumerate(legs_input):
            market_id = leg["market_id"]

            try:
                ob = await _fetch_orderbook(market_id)
            except Exception as e:
                return _text({"error": f"Failed to fetch orderbook for {market_id}: {e}"})

            try:
                title = await _fetch_market_title(market_id)
            except Exception:
                title = market_id

            enriched_legs.append(
                {
                    "exchange": "kalshi",
                    "market_id": market_id,
                    "market_title": title,
                    "orderbook": ob,
                    "leg_index": i,
                }
            )

        # ── Extract prices from orderbooks ──────────────────────
        for leg in enriched_legs:
            ob = leg["orderbook"]
            yes_price, yes_depth = best_price_and_depth(ob, "yes")
            no_price, no_depth = best_price_and_depth(ob, "no")
            leg["yes_ask"] = yes_price
            leg["yes_depth"] = yes_depth
            leg["no_ask"] = no_price
            leg["no_depth"] = no_depth
            # Also extract bid prices for sell orders (manual strategy)
            yes_bid_price, _ = best_price_and_depth(ob, "yes")
            no_bid_price, _ = best_price_and_depth(ob, "no")
            leg["yes_bid"] = yes_bid_price
            leg["no_bid"] = no_bid_price

        # ── Strategy routing ──────────────────────────────────────
        if strategy == "bracket":
            return await _handle_bracket(enriched_legs, args, total_exposure, cfg, db, session_id)
        else:
            return await _handle_manual(enriched_legs, legs_input, args, cfg, db, session_id)

    async def _handle_bracket(
        enriched_legs: list[dict[str, Any]],
        args: dict[str, Any],
        total_exposure: float,
        cfg: TradingConfig,
        db: AgentDatabase,
        session_id: str,
    ) -> dict:
        """Bracket strategy: mutually exclusive outcomes, auto-computed."""
        direction_error = _determine_direction_bracket(enriched_legs)
        if direction_error:
            return _text({"error": direction_error})

        # Compute balanced quantities
        cost_per_pair_cents = sum(leg["price_cents"] for leg in enriched_legs)
        if cost_per_pair_cents <= 0:
            return _text({"error": "Invalid prices — cost per pair is zero"})

        cost_per_pair_usd = cost_per_pair_cents / 100.0
        contracts = int(total_exposure / cost_per_pair_usd)
        if contracts < 1:
            return _text(
                {
                    "error": f"total_exposure_usd ${total_exposure} too low for one contract pair "
                    f"(cost per pair: ${cost_per_pair_usd:.2f})"
                }
            )

        # Check depth
        for leg in enriched_legs:
            if leg.get("depth", 0) < 5:
                return _text(
                    {
                        "error": f"Orderbook depth too thin for {leg['market_id']} "
                        f"({leg['side']} side): only {leg.get('depth', 0)} contracts available"
                    }
                )

        # Compute fees (leg-in: harder side maker, easier side taker)
        sorted_legs = sorted(enriched_legs, key=lambda lg: lg.get("depth", 0))
        sorted_legs[0]["is_maker"] = True
        for leg in sorted_legs[1:]:
            leg["is_maker"] = False

        fee_legs = [
            {
                "exchange": "kalshi",
                "price_cents": leg["price_cents"],
                "maker": leg["is_maker"],
            }
            for leg in enriched_legs
        ]
        edge_result = compute_arb_edge(fee_legs, contracts)

        if edge_result["net_edge_pct"] < cfg.min_edge_pct:
            return _text(
                {
                    "error": f"Net edge {edge_result['net_edge_pct']:.1f}% after fees "
                    f"is below minimum {cfg.min_edge_pct}%",
                    "details": edge_result,
                }
            )

        # Validate position limits
        limit_error = _validate_position_limits(enriched_legs, contracts, cfg)
        if limit_error:
            return _text({"error": limit_error})

        # Store and respond
        return _build_recommendation_response(
            enriched_legs=enriched_legs,
            contracts=contracts,
            cost_per_pair_usd=cost_per_pair_usd,
            edge_result=edge_result,
            args=args,
            db=db,
            session_id=session_id,
            recommendation_ttl_minutes=recommendation_ttl_minutes,
            total_exposure=total_exposure,
        )

    async def _handle_manual(
        enriched_legs: list[dict[str, Any]],
        legs_input: list[dict[str, Any]],
        args: dict[str, Any],
        cfg: TradingConfig,
        db: AgentDatabase,
        session_id: str,
    ) -> dict:
        """Manual strategy: agent-specified positions, no guaranteed edge."""
        direction_error = _apply_manual_direction(enriched_legs, legs_input)
        if direction_error:
            return _text({"error": direction_error})

        # Assign maker/taker by depth (shallowest = maker)
        sorted_legs = sorted(enriched_legs, key=lambda lg: lg.get("depth", 0))
        sorted_legs[0]["is_maker"] = True
        for leg in sorted_legs[1:]:
            leg["is_maker"] = False

        # Validate aggregate position limits
        limit_error = _validate_aggregate_limits(enriched_legs, cfg)
        if limit_error:
            return _text({"error": limit_error})

        # Per-leg position limits
        for leg in enriched_legs:
            qty = leg["quantity"]
            cost = leg["price_cents"] * qty / 100.0
            fee = kalshi_fee(qty, leg["price_cents"], maker=leg.get("is_maker", False))
            if cost + fee > cfg.kalshi_max_position_usd:
                return _text(
                    {
                        "error": f"Leg {leg['market_id']} cost ${cost + fee:.2f} "
                        f"exceeds limit ${cfg.kalshi_max_position_usd:.2f}"
                    }
                )

        # Store and respond
        return _build_manual_recommendation_response(
            enriched_legs=enriched_legs,
            args=args,
            db=db,
            session_id=session_id,
            recommendation_ttl_minutes=recommendation_ttl_minutes,
        )

    return [recommend_trade]
