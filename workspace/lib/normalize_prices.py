#!/usr/bin/env python3
"""Compare prices across Kalshi and Polymarket, compute fee-adjusted edge."""
import argparse
import json


def compare(kalshi_cents, poly_usd, kalshi_fee=0.03, poly_fee=0.001):
    k = kalshi_cents / 100.0
    p = poly_usd
    gross = abs(k - p)
    fees = k * kalshi_fee + p * poly_fee
    net = gross - fees
    return {
        "kalshi_prob": round(k, 4),
        "polymarket_prob": round(p, 4),
        "gross_edge_pct": round(gross * 100, 2),
        "fees_pct": round(fees * 100, 2),
        "net_edge_pct": round(net * 100, 2),
        "profitable": net > 0,
        "direction": "buy_poly_sell_kalshi" if k > p else "buy_kalshi_sell_poly",
    }


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="Cross-platform price comparison")
    ap.add_argument("--kalshi-price", type=int, required=True, help="Kalshi price in cents")
    ap.add_argument("--polymarket-price", type=float, required=True, help="Polymarket USD price")
    ap.add_argument("--kalshi-fee", type=float, default=0.03)
    ap.add_argument("--polymarket-fee", type=float, default=0.001)
    a = ap.parse_args()
    print(
        json.dumps(
            compare(a.kalshi_price, a.polymarket_price, a.kalshi_fee, a.polymarket_fee), indent=2
        )
    )
