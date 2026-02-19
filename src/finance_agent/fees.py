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
    SIDE_YES,
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


# ── Hypothetical P&L ─────────────────────────────────────────────


def compute_hypothetical_pnl(group: dict[str, Any]) -> float:
    """Compute hypothetical P&L in USD for a fully-settled recommendation group."""
    return _pnl(group.get("legs", []))


def _pnl(legs: list[dict[str, Any]]) -> float:
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
