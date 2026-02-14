#!/usr/bin/env python3
"""Kelly criterion position sizing for prediction market arb."""
import argparse
import json
import math


def kelly(edge, odds, bankroll, fraction=0.25):
    b = odds
    p = 0.5 + edge / 2  # convert edge to implied win prob
    q = 1 - p
    f = (b * p - q) / b
    f_adj = f * fraction  # fractional Kelly
    bet = bankroll * max(0, f_adj)
    ror = math.exp(-2 * edge * bankroll * f_adj) if f_adj > 0 else 1.0
    return {
        "full_kelly": round(f, 4),
        "fractional_kelly": round(f_adj, 4),
        "bet_size_usd": round(bet, 2),
        "risk_of_ruin": round(min(1, ror), 6),
    }


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="Kelly criterion position sizing")
    ap.add_argument("--edge", type=float, required=True, help="Edge as decimal (0.07 = 7%%)")
    ap.add_argument("--odds", type=float, default=1.0, help="Net odds (payout/cost - 1)")
    ap.add_argument("--bankroll", type=float, required=True, help="Available capital USD")
    ap.add_argument("--fraction", type=float, default=0.25, help="Kelly fraction (0.25 = quarter)")
    a = ap.parse_args()
    print(json.dumps(kelly(a.edge, a.odds, a.bankroll, a.fraction), indent=2))
