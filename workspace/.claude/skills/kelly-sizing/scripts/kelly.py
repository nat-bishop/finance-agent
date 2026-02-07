#!/usr/bin/env python3
"""Kelly Criterion position sizing for binary prediction markets.

Usage:
    python kelly.py --true-prob 0.65 --market-price 55 --bankroll 500
    python kelly.py --true-prob 0.65 --market-price 55 --bankroll 500 --fraction 0.5 --fee-rate 0.03
"""

import argparse
import json
import math
import sys


def kelly_fraction(true_prob: float, market_price_cents: int, fee_rate: float = 0.0) -> dict:
    """Compute Kelly optimal fraction for a YES buy at given price.

    Args:
        true_prob: Estimated true probability (0-1)
        market_price_cents: Market YES price in cents (1-99)
        fee_rate: Fee rate as decimal (e.g. 0.03 for 3%)

    Returns:
        Dict with kelly_fraction, edge, expected_growth, etc.
    """
    c = market_price_cents / 100  # convert to dollars
    p = true_prob
    q = 1 - p

    # Effective payout after fees
    gross_payout = 1.0  # $1 per contract if YES wins
    net_payout = gross_payout * (1 - fee_rate)

    # Net odds: profit / cost
    if c <= 0 or c >= 1:
        return {"error": "Market price must be between 1 and 99 cents"}

    b = (net_payout - c) / c  # net odds ratio

    # Edge: expected value per dollar wagered
    edge = p * b - q
    edge_pct = edge * 100

    # Kelly fraction
    if b <= 0:
        return {"error": "Negative odds after fees — no profitable trade"}

    f_star = (p * b - q) / b

    # Expected log growth rate
    if f_star > 0:
        growth = p * math.log(1 + f_star * b) + q * math.log(1 - f_star)
    else:
        growth = 0.0

    # Risk of ruin estimate (simplified — assumes repeated independent bets)
    # P(ruin) ≈ (q/p)^(bankroll/bet_size) for even-money bets
    # For general odds, use: (q/(p*b))^n approximation
    if f_star > 0 and p > 0 and b > 0:
        ruin_base = q / (p * b) if p * b > 0 else 1.0
        ruin_base = min(ruin_base, 0.999)  # cap for numerical stability
    else:
        ruin_base = 1.0

    return {
        "kelly_fraction_full": round(f_star, 6),
        "edge_pct": round(edge_pct, 4),
        "net_odds": round(b, 4),
        "expected_log_growth": round(growth, 6),
        "ruin_base_per_bet": round(ruin_base, 6),
        "implied_prob": c,
        "true_prob": p,
        "fee_rate": fee_rate,
    }


def size_position(
    true_prob: float,
    market_price_cents: int,
    bankroll: float,
    fraction: float = 0.25,
    fee_rate: float = 0.0,
) -> dict:
    """Full position sizing recommendation.

    Args:
        true_prob: Estimated true probability
        market_price_cents: Market YES price in cents
        bankroll: Available bankroll in dollars
        fraction: Kelly fraction multiplier (default 0.25 = quarter Kelly)
        fee_rate: Fee rate as decimal

    Returns:
        Complete sizing recommendation dict.
    """
    kf = kelly_fraction(true_prob, market_price_cents, fee_rate)
    if "error" in kf:
        return kf

    f_full = kf["kelly_fraction_full"]
    f_used = f_full * fraction

    if f_used <= 0:
        return {
            **kf,
            "recommendation": "NO TRADE",
            "reason": "Negative or zero edge after fees",
            "kelly_fraction_used": 0,
            "fraction_multiplier": fraction,
            "bet_size_usd": 0,
            "contracts": 0,
        }

    bet_size = bankroll * f_used
    cost_per_contract = market_price_cents / 100
    contracts = int(bet_size / cost_per_contract)

    return {
        **kf,
        "kelly_fraction_used": round(f_used, 6),
        "fraction_multiplier": fraction,
        "bet_size_usd": round(bet_size, 2),
        "contracts": contracts,
        "total_cost_usd": round(contracts * cost_per_contract, 2),
        "max_profit_usd": round(contracts * (1 - cost_per_contract) * (1 - fee_rate), 2),
        "max_loss_usd": round(contracts * cost_per_contract, 2),
        "recommendation": "TRADE" if contracts > 0 else "NO TRADE (too small)",
    }


def main():
    parser = argparse.ArgumentParser(description="Kelly Criterion position sizing")
    parser.add_argument("--true-prob", type=float, required=True, help="True probability (0-1)")
    parser.add_argument("--market-price", type=int, required=True, help="Market YES price in cents (1-99)")
    parser.add_argument("--bankroll", type=float, required=True, help="Available bankroll in USD")
    parser.add_argument("--fraction", type=float, default=0.25, help="Kelly fraction (default 0.25)")
    parser.add_argument("--fee-rate", type=float, default=0.0, help="Fee rate as decimal (default 0)")

    args = parser.parse_args()

    if not 0 < args.true_prob < 1:
        print(json.dumps({"error": "true_prob must be between 0 and 1"}))
        sys.exit(1)
    if not 1 <= args.market_price <= 99:
        print(json.dumps({"error": "market_price must be between 1 and 99 cents"}))
        sys.exit(1)

    result = size_position(
        true_prob=args.true_prob,
        market_price_cents=args.market_price,
        bankroll=args.bankroll,
        fraction=args.fraction,
        fee_rate=args.fee_rate,
    )

    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
