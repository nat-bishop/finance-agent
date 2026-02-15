#!/usr/bin/env python3
"""Compare prices across Kalshi and Polymarket, compute fee-adjusted edge.

Uses real fee formulas:
- Kalshi: ceil(rate * contracts * P * (1-P)), capped at $0.02/contract
  - Taker rate: 0.07, Maker rate: 0.0175
- Polymarket US: 0.10% of total premium (taker), free for makers
"""
import argparse
import json
import math


def _kalshi_fee(contracts: int, price_cents: int, maker: bool = False) -> float:
    """Kalshi P(1-P) fee. Returns USD."""
    if contracts <= 0 or not (1 <= price_cents <= 99):
        return 0.0
    p = price_cents / 100.0
    rate = 0.0175 if maker else 0.07
    raw = math.ceil(100 * rate * contracts * p * (1 - p)) / 100
    return min(raw, 0.02 * contracts)


def _polymarket_fee(contracts: int, price_cents: int, maker: bool = False) -> float:
    """Polymarket US fee. Returns USD."""
    if maker or contracts <= 0 or not (1 <= price_cents <= 99):
        return 0.0
    premium = contracts * price_cents / 100.0
    return max(premium * 0.001, 0.001)


def compare(kalshi_cents, poly_cents, contracts=100, maker=False):
    k = kalshi_cents / 100.0
    p = poly_cents / 100.0

    gross = abs(k - p)

    k_fee_taker = _kalshi_fee(contracts, kalshi_cents, maker=False)
    k_fee_maker = _kalshi_fee(contracts, kalshi_cents, maker=True)
    p_fee_taker = _polymarket_fee(contracts, poly_cents, maker=False)
    p_fee_maker = _polymarket_fee(contracts, poly_cents, maker=True)

    # Leg-in strategy: hard side as maker, easy side as taker
    fees_legin = k_fee_maker + p_fee_taker  # Kalshi maker + Poly taker
    fees_legin_alt = k_fee_taker + p_fee_maker  # Kalshi taker + Poly maker
    fees_both_taker = k_fee_taker + p_fee_taker

    total_cost = contracts * (k + p)
    gross_edge = contracts * gross

    return {
        "kalshi_prob": round(k, 4),
        "polymarket_prob": round(p, 4),
        "contracts": contracts,
        "gross_edge_pct": round(gross * 100, 2),
        "gross_edge_usd": round(gross_edge, 4),
        "fees": {
            "kalshi_taker": round(k_fee_taker, 4),
            "kalshi_maker": round(k_fee_maker, 4),
            "polymarket_taker": round(p_fee_taker, 4),
            "polymarket_maker": round(p_fee_maker, 4),
        },
        "scenarios": {
            "legin_kalshi_maker": {
                "total_fees": round(fees_legin, 4),
                "net_edge_usd": round(gross_edge - fees_legin, 4),
                "net_edge_pct": round((gross_edge - fees_legin) / total_cost * 100, 2)
                if total_cost
                else 0,
                "profitable": gross_edge > fees_legin,
            },
            "legin_poly_maker": {
                "total_fees": round(fees_legin_alt, 4),
                "net_edge_usd": round(gross_edge - fees_legin_alt, 4),
                "net_edge_pct": round(
                    (gross_edge - fees_legin_alt) / total_cost * 100, 2
                )
                if total_cost
                else 0,
                "profitable": gross_edge > fees_legin_alt,
            },
            "both_taker": {
                "total_fees": round(fees_both_taker, 4),
                "net_edge_usd": round(gross_edge - fees_both_taker, 4),
                "net_edge_pct": round(
                    (gross_edge - fees_both_taker) / total_cost * 100, 2
                )
                if total_cost
                else 0,
                "profitable": gross_edge > fees_both_taker,
            },
        },
        "direction": "buy_poly_sell_kalshi" if k > p else "buy_kalshi_sell_poly",
    }


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="Cross-platform price comparison with real fees")
    ap.add_argument("--kalshi-price", type=int, required=True, help="Kalshi price in cents")
    ap.add_argument(
        "--polymarket-price", type=int, required=True, help="Polymarket price in cents"
    )
    ap.add_argument("--contracts", type=int, default=100, help="Number of contracts (default 100)")
    a = ap.parse_args()
    print(json.dumps(compare(a.kalshi_price, a.polymarket_price, a.contracts), indent=2))
