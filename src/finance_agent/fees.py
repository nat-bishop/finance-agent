"""Real fee calculations for Kalshi.

Kalshi uses a P(1-P) parabolic formula — highest fees at 50c, near-zero at extremes.
"""

from __future__ import annotations

import json
import math
from typing import Any

from .constants import (
    ACTION_BUY,
    BINARY_PAYOUT_CENTS,
    EXCHANGE_KALSHI,
    SIDE_YES,
    STRATEGY_BRACKET,
)


def kalshi_fee(contracts: int, price_cents: int, *, maker: bool = False) -> float:
    """Kalshi fee using P(1-P) formula. Returns fee in USD.

    Taker: ceil(0.07 * contracts * P * (1-P)), capped at $0.02/contract
    Maker: ceil(0.0175 * contracts * P * (1-P)), capped at $0.02/contract
    """
    if contracts <= 0 or not (1 <= price_cents <= 99):
        return 0.0
    p = price_cents / 100.0
    rate = 0.0175 if maker else 0.07
    raw = math.ceil(100 * rate * contracts * p * (1 - p)) / 100  # ceil to nearest cent
    cap = 0.02 * contracts
    return min(raw, cap)


def best_price_and_depth(orderbook: dict[str, Any], side: str) -> tuple[int | None, int]:
    """Extract best executable price (cents) and total depth at that level.

    Handles Kalshi format ({yes: [[price, qty], ...], no: [...]}).
    """
    ob = orderbook.get("orderbook", orderbook)
    asks = ob.get("yes", []) if side == SIDE_YES else ob.get("no", [])

    if not asks:
        return None, 0

    first = asks[0]
    if isinstance(first, list | tuple):
        return int(first[0]), int(first[1])
    if isinstance(first, dict):
        return int(first.get("price", 0)), int(first.get("quantity", 0))
    return None, 0


def compute_arb_edge(
    legs: list[dict[str, Any]],
    contracts: int,
) -> dict[str, Any]:
    """Compute net edge for a balanced arb (equal contracts on all legs).

    Each leg dict must have: exchange, price_cents, maker (bool).

    For bracket N-leg (same exchange): edge = sum of prices - $1 per set.
    """
    if not legs or contracts <= 0:
        return {
            "gross_edge_usd": 0.0,
            "total_fees_usd": 0.0,
            "net_edge_usd": 0.0,
            "net_edge_pct": 0.0,
            "profitable": False,
            "fee_breakdown": [],
        }

    cost_per_pair_cents = sum(leg["price_cents"] for leg in legs)

    # Bracket: selling all outcomes at sum > 100c, guaranteed cost = 100c per set
    payout_per_pair_cents = cost_per_pair_cents
    cost_per_pair_cents = BINARY_PAYOUT_CENTS  # you collect the sum, pay out $1
    total_cost_usd = contracts * BINARY_PAYOUT_CENTS / 100.0

    gross_edge_per_pair = abs(payout_per_pair_cents - cost_per_pair_cents) / 100.0
    gross_edge_usd = contracts * gross_edge_per_pair

    fee_breakdown = []
    total_fees = 0.0
    for leg in legs:
        fee = kalshi_fee(contracts, leg["price_cents"], maker=leg.get("maker", False))
        fee_breakdown.append(
            {
                "exchange": leg.get("exchange", EXCHANGE_KALSHI),
                "price_cents": leg["price_cents"],
                "maker": leg.get("maker", False),
                "fee_usd": round(fee, 4),
            }
        )
        total_fees += fee

    net_edge_usd = gross_edge_usd - total_fees
    # Express as % of total capital deployed
    net_edge_pct = (net_edge_usd / total_cost_usd * 100) if total_cost_usd > 0 else 0.0

    return {
        "gross_edge_usd": round(gross_edge_usd, 4),
        "total_fees_usd": round(total_fees, 4),
        "net_edge_usd": round(net_edge_usd, 4),
        "net_edge_pct": round(net_edge_pct, 2),
        "profitable": net_edge_usd > 0,
        "fee_breakdown": fee_breakdown,
    }


# ── Hypothetical P&L ─────────────────────────────────────────────


def compute_hypothetical_pnl(group: dict[str, Any]) -> float:
    """Compute hypothetical P&L in USD for a fully-settled recommendation group."""
    strategy = group.get("strategy", STRATEGY_BRACKET)
    legs = group.get("legs", [])
    if strategy == STRATEGY_BRACKET:
        return _pnl_bracket(legs)
    return _pnl_manual(legs)


def _pnl_bracket(legs: list[dict[str, Any]]) -> float:
    """P&L for bracket arb: guaranteed payout minus cost minus fees.

    Buy all N outcomes at combined cost < $1 per set. One settles at 100c, rest at 0c.
    Payout is always 100c x quantity regardless of which outcome wins.
    """
    if not legs:
        return 0.0

    quantity = legs[0].get("quantity", 0)
    total_cost_cents = sum(
        leg.get("price_cents", 0) * leg.get("quantity", quantity) for leg in legs
    )
    payout_cents = BINARY_PAYOUT_CENTS * quantity

    total_fees = sum(
        kalshi_fee(
            leg.get("quantity", quantity),
            leg.get("price_cents", 0),
            maker=leg.get("is_maker", False),
        )
        for leg in legs
    )

    return round((payout_cents - total_cost_cents) / 100.0 - total_fees, 4)


def _pnl_manual(legs: list[dict[str, Any]]) -> float:
    """P&L for manual strategy: per-leg directional P&L minus fees."""
    total_pnl_cents = 0
    total_fees = 0.0

    for leg in legs:
        settlement = leg.get("settlement_value")
        price = leg.get("price_cents", 0)
        quantity = leg.get("quantity", 0)
        action = leg.get("action", ACTION_BUY)
        side = leg.get("side", SIDE_YES)

        if settlement is None:
            continue

        # For NO-side: invert settlement (YES=100 means NO=0 and vice versa)
        effective_settlement = (
            settlement if side == SIDE_YES else (BINARY_PAYOUT_CENTS - settlement)
        )

        if action == ACTION_BUY:
            leg_pnl = (effective_settlement - price) * quantity
        else:
            leg_pnl = (price - effective_settlement) * quantity

        total_pnl_cents += leg_pnl
        total_fees += kalshi_fee(quantity, price, maker=leg.get("is_maker", False))

    return round(total_pnl_cents / 100.0 - total_fees, 4)


def assess_depth_concern(leg: dict[str, Any]) -> str | None:
    """Return a warning if orderbook depth was less than quantity, or None."""
    snapshot_json = leg.get("orderbook_snapshot_json")
    if not snapshot_json:
        return None
    try:
        snapshot = json.loads(snapshot_json) if isinstance(snapshot_json, str) else snapshot_json
    except (json.JSONDecodeError, TypeError):
        return None

    quantity = leg.get("quantity", 0)
    side = leg.get("side", SIDE_YES)
    depth = snapshot.get(f"{side}_depth", 0) or 0

    if quantity > 0 and depth < quantity:
        return f"Depth {depth} < qty {quantity} on {side} side"
    return None
