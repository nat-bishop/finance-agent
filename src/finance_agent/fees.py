"""Real fee calculations for Kalshi.

Kalshi uses a P(1-P) parabolic formula — highest fees at 50c, near-zero at extremes.
"""

from __future__ import annotations

import math
from typing import Any


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


def leg_fee(exchange: str, contracts: int, price_cents: int, *, maker: bool = False) -> float:
    """Dispatch to exchange-specific fee function."""
    if exchange == "kalshi":
        return kalshi_fee(contracts, price_cents, maker=maker)
    raise ValueError(f"Unknown exchange: {exchange}")


def best_price_and_depth(orderbook: dict[str, Any], side: str) -> tuple[int | None, int]:
    """Extract best executable price (cents) and total depth at that level.

    Handles Kalshi format ({yes: [[price, qty], ...], no: [...]}).
    """
    ob = orderbook.get("orderbook", orderbook)
    asks = ob.get("yes", []) if side == "yes" else ob.get("no", [])

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
    cost_per_pair_cents = 100  # you collect the sum, pay out $1
    total_cost_usd = contracts * 100 / 100.0

    gross_edge_per_pair = abs(payout_per_pair_cents - cost_per_pair_cents) / 100.0
    gross_edge_usd = contracts * gross_edge_per_pair

    fee_breakdown = []
    total_fees = 0.0
    for leg in legs:
        fee = kalshi_fee(contracts, leg["price_cents"], maker=leg.get("maker", False))
        fee_breakdown.append(
            {
                "exchange": leg.get("exchange", "kalshi"),
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
