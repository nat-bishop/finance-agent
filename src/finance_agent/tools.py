"""Unified MCP tool factories for market access and database."""

from __future__ import annotations

import json
from typing import Any

from claude_agent_sdk import tool

from .config import TradingConfig
from .database import AgentDatabase
from .fees import best_price_and_depth, compute_arb_edge, leg_fee
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
        if polymarket is None:
            raise RuntimeError("polymarket client is unexpectedly None")
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
        if polymarket is None:
            raise RuntimeError("polymarket client is unexpectedly None")
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
        if polymarket is None:
            raise RuntimeError("polymarket client is unexpectedly None")
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
        if polymarket is None:
            raise RuntimeError("polymarket client is unexpectedly None")
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


def _determine_direction_2leg(enriched_legs: list[dict[str, Any]]) -> str | None:
    """Assign action/side/price/depth to a 2-leg cross-platform arb.

    Buys YES on the cheaper exchange, buys NO on the expensive exchange.
    Mutates legs in-place. Returns error string or None on success.
    """
    leg_a, leg_b = enriched_legs
    a_yes = leg_a.get("yes_ask")
    b_yes = leg_b.get("yes_ask")

    if a_yes is None or b_yes is None:
        empty_id = leg_a["market_id"] if a_yes is None else leg_b["market_id"]
        return f"No executable price — empty orderbook for {empty_id}"

    if a_yes <= b_yes:
        leg_a["action"], leg_a["side"] = "buy", "yes"
        leg_a["price_cents"] = a_yes
        leg_a["depth"] = leg_a["yes_depth"]
        leg_b["action"], leg_b["side"] = "buy", "no"
        if not leg_b.get("no_ask"):
            return f"No executable NO price for {leg_b['market_id']} — NO orderbook is empty"
        leg_b["price_cents"] = leg_b["no_ask"]
        leg_b["depth"] = leg_b.get("no_depth", 0)
    else:
        leg_b["action"], leg_b["side"] = "buy", "yes"
        leg_b["price_cents"] = b_yes
        leg_b["depth"] = leg_b["yes_depth"]
        leg_a["action"], leg_a["side"] = "buy", "no"
        if not leg_a.get("no_ask"):
            return f"No executable NO price for {leg_a['market_id']} — NO orderbook is empty"
        leg_a["price_cents"] = leg_a["no_ask"]
        leg_a["depth"] = leg_a.get("no_depth", 0)

    for leg in enriched_legs:
        if not leg.get("price_cents") or not (1 <= leg["price_cents"] <= 99):
            return (
                f"No executable price for {leg['market_id']} "
                f"({leg['side']} side) — orderbook may be empty"
            )
    return None


def _determine_direction_bracket(enriched_legs: list[dict[str, Any]]) -> str | None:
    """Assign action/side/price/depth to an N-leg bracket arb (same exchange).

    Compares buying all YES vs all NO, picks the profitable direction.
    Mutates legs in-place. Returns error string or None on success.
    """
    leg_exchanges = {leg["exchange"] for leg in enriched_legs}
    if len(leg_exchanges) != 1:
        return (
            "Multi-leg arbs with mixed exchanges are not supported. "
            "Use 2-leg cross-platform arbs or N-leg bracket arbs on one exchange."
        )

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

    for leg in enriched_legs:
        if not leg.get("price_cents") or not (1 <= leg["price_cents"] <= 99):
            return (
                f"No executable price for {leg['market_id']} "
                f"({leg['side']} side) — orderbook may be empty"
            )
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
        cost = leg["price_cents"] * contracts / 100.0
        fee = leg_fee(leg["exchange"], contracts, leg["price_cents"], maker=leg["is_maker"])
        cost_with_fee = cost + fee
        if leg["exchange"] == "kalshi" and cost_with_fee > cfg.kalshi_max_position_usd:
            return (
                f"Kalshi leg ${cost_with_fee:.2f} (incl ${fee:.4f} fee) "
                f"exceeds limit ${cfg.kalshi_max_position_usd:.2f}"
            )
        if leg["exchange"] == "polymarket" and cost_with_fee > cfg.polymarket_max_position_usd:
            return (
                f"Polymarket leg ${cost_with_fee:.2f} (incl ${fee:.4f} fee) "
                f"exceeds limit ${cfg.polymarket_max_position_usd:.2f}"
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
                "quantity": contracts,
                "price_cents": leg["price_cents"],
                "is_maker": leg["is_maker"],
                "orderbook_snapshot_json": json.dumps(ob_snapshot),
            }
        )

    group_id, expires_at = db.log_recommendation_group(
        session_id=session_id,
        thesis=args.get("thesis"),
        estimated_edge_pct=edge_result["net_edge_pct"],
        equivalence_notes=args.get("equivalence_notes"),
        signal_id=args.get("signal_id"),
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
                    "quantity": contracts,
                    "price_cents": leg["price_cents"],
                    "is_maker": leg["is_maker"],
                }
                for leg in enriched_legs
            ],
        }
    )


def create_db_tools(
    db: AgentDatabase,
    session_id: str,
    kalshi: KalshiAPIClient,
    polymarket: PolymarketAPIClient | None,
    trading_config: Any = None,
    recommendation_ttl_minutes: int = 60,
) -> list:
    """Database tools for agent persistence.

    Exchange clients are needed to fetch orderbooks at recommendation time
    for auto-pricing and balanced sizing.
    """
    cfg: TradingConfig = trading_config or TradingConfig()

    def _get_client(exchange: str) -> KalshiAPIClient | PolymarketAPIClient:
        if exchange == "kalshi":
            return kalshi
        if exchange == "polymarket":
            if polymarket is None:
                raise ValueError("Polymarket is not enabled")
            return polymarket
        raise ValueError(f"Unknown exchange: {exchange}")

    def _fetch_orderbook(exchange: str, market_id: str) -> dict[str, Any]:
        client = _get_client(exchange)
        return client.get_orderbook(market_id)

    def _fetch_market_title(exchange: str, market_id: str) -> str:
        client = _get_client(exchange)
        market = client.get_market(market_id)
        if isinstance(market, dict):
            # Kalshi nests under "market" key, Polymarket may not
            inner = market.get("market", market)
            return str(inner.get("title", inner.get("question", market_id)))
        return market_id

    @tool(
        "recommend_trade",
        (
            "Record an arbitrage recommendation. Provide market pairs and total exposure "
            "— the system computes direction, prices, quantities, and fees from live orderbooks."
        ),
        {
            "type": "object",
            "required": ["thesis", "equivalence_notes", "total_exposure_usd", "legs"],
            "properties": {
                "thesis": {
                    "type": "string",
                    "description": "1-3 sentences explaining the arbitrage opportunity",
                    "minLength": 10,
                },
                "equivalence_notes": {
                    "type": "string",
                    "description": (
                        "How you verified the markets settle identically: "
                        "resolution source, timing, boundary conditions"
                    ),
                    "minLength": 10,
                },
                "total_exposure_usd": {
                    "type": "number",
                    "description": "Total capital to deploy across all legs (USD)",
                    "minimum": 1,
                    "maximum": 1000,
                },
                "signal_id": {
                    "type": "integer",
                    "description": "Signal ID that prompted this investigation, if any",
                    "minimum": 1,
                },
                "legs": {
                    "type": "array",
                    "description": "Market pairs to arb (2+ required). Just identify markets.",
                    "minItems": 2,
                    "maxItems": 6,
                    "items": {
                        "type": "object",
                        "required": ["exchange", "market_id"],
                        "properties": {
                            "exchange": {
                                "type": "string",
                                "enum": ["kalshi", "polymarket"],
                            },
                            "market_id": {
                                "type": "string",
                                "minLength": 1,
                            },
                        },
                    },
                },
            },
        },
    )
    async def recommend_trade(args: dict) -> dict:
        legs_input = args.get("legs", [])
        total_exposure = args.get("total_exposure_usd", 0)

        # ── Validation ──────────────────────────────────────────
        errors: list[str] = []
        if len(legs_input) < 2:
            errors.append("Arbitrage requires 2+ legs")
        if not args.get("equivalence_notes"):
            errors.append("Missing equivalence_notes — explain settlement verification")

        exchanges = {leg["exchange"] for leg in legs_input}
        if len(exchanges) < 2 and len(legs_input) == 2:
            errors.append(
                "Cross-platform arb requires legs on different exchanges "
                f"(both legs are on {exchanges.pop()})"
            )

        if errors:
            return _text({"error": "; ".join(errors)})

        # ── Fetch orderbooks and market titles ──────────────────
        enriched_legs: list[dict[str, Any]] = []
        for i, leg in enumerate(legs_input):
            exchange = leg["exchange"]
            market_id = leg["market_id"]

            try:
                ob = _fetch_orderbook(exchange, market_id)
            except Exception as e:
                return _text({"error": f"Failed to fetch orderbook for {market_id}: {e}"})

            try:
                title = _fetch_market_title(exchange, market_id)
            except Exception:
                title = market_id

            enriched_legs.append(
                {
                    "exchange": exchange,
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

        # ── Determine direction ─────────────────────────────────
        if len(enriched_legs) == 2:
            direction_error = _determine_direction_2leg(enriched_legs)
        else:
            direction_error = _determine_direction_bracket(enriched_legs)
        if direction_error:
            return _text({"error": direction_error})

        # ── Compute balanced quantities ─────────────────────────
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

        # ── Compute fees (leg-in: harder side maker, easier side taker) ──
        sorted_legs = sorted(enriched_legs, key=lambda lg: lg.get("depth", 0))
        sorted_legs[0]["is_maker"] = True
        for leg in sorted_legs[1:]:
            leg["is_maker"] = False

        fee_legs = [
            {
                "exchange": leg["exchange"],
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

        # ── Validate position limits ─────────────────────────────
        limit_error = _validate_position_limits(enriched_legs, contracts, cfg)
        if limit_error:
            return _text({"error": limit_error})

        # ── Store and respond ────────────────────────────────────
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

    return [recommend_trade]
