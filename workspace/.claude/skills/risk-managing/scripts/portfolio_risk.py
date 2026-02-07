#!/usr/bin/env python3
"""Portfolio risk analysis for prediction market positions.

Usage:
    python portfolio_risk.py --positions '[{"ticker":"A","prob":0.6,"size":10,"cost_per":0.45,"category":"fed"}]'
    python portfolio_risk.py --positions-file data/positions.json --portfolio-value 500
"""

import argparse
import json
import sys
from collections import defaultdict

import numpy as np


def analyze_portfolio_risk(
    positions: list[dict],
    portfolio_value: float = 500.0,
    correlation_groups: dict[str, list[str]] | None = None,
) -> dict:
    """Analyze portfolio-level risk metrics.

    Args:
        positions: List of dicts with: ticker, prob, size, cost_per, category (optional)
        portfolio_value: Total portfolio value in USD
        correlation_groups: Dict mapping group name to list of tickers

    Returns:
        Risk analysis dict.
    """
    if not positions:
        return {"error": "No positions provided"}

    n = len(positions)
    tickers = [p["ticker"] for p in positions]
    sizes = np.array([p["size"] for p in positions])
    costs = np.array([p["cost_per"] for p in positions])
    probs = np.array([p["prob"] for p in positions])

    # Position values and weights
    position_values = sizes * costs
    total_invested = float(position_values.sum())
    weights = position_values / portfolio_value if portfolio_value > 0 else position_values

    # Expected P&L per position
    expected_pnl = sizes * (probs * (1 - costs) - (1 - probs) * costs)
    total_expected_pnl = float(expected_pnl.sum())

    # Max loss (all positions lose)
    max_loss = float(position_values.sum())

    # ── Concentration Analysis ──────────────────────────────────────
    concentration = {
        "positions": [],
        "warnings": [],
    }

    for i, p in enumerate(positions):
        weight = float(weights[i])
        concentration["positions"].append(
            {
                "ticker": p["ticker"],
                "value_usd": round(float(position_values[i]), 2),
                "weight_pct": round(weight * 100, 2),
                "expected_pnl": round(float(expected_pnl[i]), 2),
            }
        )
        if weight > 0.30:
            concentration["warnings"].append(
                f"{p['ticker']}: {weight * 100:.1f}% of portfolio (>30% limit)"
            )

    # Top 3 concentration
    sorted_weights = sorted(weights, reverse=True)
    top3_weight = float(sum(sorted_weights[:3]))
    if top3_weight > 0.60:
        concentration["warnings"].append(
            f"Top 3 positions = {top3_weight * 100:.1f}% (>60% warning)"
        )

    # Cash reserve
    cash_pct = (portfolio_value - total_invested) / portfolio_value * 100
    if cash_pct < 20:
        concentration["warnings"].append(f"Cash reserve {cash_pct:.1f}% (<20% warning)")

    concentration["total_invested_usd"] = round(total_invested, 2)
    concentration["cash_reserve_pct"] = round(cash_pct, 2)

    # ── Correlation Analysis ────────────────────────────────────────
    correlation_flags = []

    if correlation_groups:
        for group_name, group_tickers in correlation_groups.items():
            group_positions = [i for i, p in enumerate(positions) if p["ticker"] in group_tickers]
            if len(group_positions) >= 2:
                group_value = sum(float(position_values[i]) for i in group_positions)
                group_weight = group_value / portfolio_value
                correlation_flags.append(
                    {
                        "group": group_name,
                        "tickers": [tickers[i] for i in group_positions],
                        "combined_value_usd": round(group_value, 2),
                        "combined_weight_pct": round(group_weight * 100, 2),
                        "warning": group_weight > 0.40,
                    }
                )

    # Also check by category if provided
    category_groups: dict[str, list[int]] = defaultdict(list)
    for i, p in enumerate(positions):
        cat = p.get("category", "uncategorized")
        category_groups[cat].append(i)

    for cat, indices in category_groups.items():
        if len(indices) >= 2:
            group_value = sum(float(position_values[i]) for i in indices)
            group_weight = group_value / portfolio_value
            if group_weight > 0.30:
                correlation_flags.append(
                    {
                        "group": f"category:{cat}",
                        "tickers": [tickers[i] for i in indices],
                        "combined_value_usd": round(group_value, 2),
                        "combined_weight_pct": round(group_weight * 100, 2),
                        "warning": group_weight > 0.40,
                    }
                )

    # ── VaR Estimate (analytical, assuming independence) ────────────
    # For binary positions: variance = p*(1-p) per outcome
    position_vars = sizes**2 * costs**2 * probs * (1 - probs)
    portfolio_var = float(np.sqrt(position_vars.sum()))  # std dev
    var_95 = total_expected_pnl - 1.645 * portfolio_var
    var_99 = total_expected_pnl - 2.326 * portfolio_var

    # ── Suggested Actions ───────────────────────────────────────────
    suggestions = []

    if max_loss > portfolio_value * 0.30:
        suggestions.append("Total exposure exceeds 30% drawdown threshold — consider reducing")

    for flag in correlation_flags:
        if flag.get("warning"):
            suggestions.append(
                f"Correlated group '{flag['group']}' at {flag['combined_weight_pct']:.1f}% — reduce or hedge"
            )

    if not suggestions:
        suggestions.append("Portfolio within risk limits")

    return {
        "summary": {
            "n_positions": n,
            "portfolio_value_usd": portfolio_value,
            "total_invested_usd": round(total_invested, 2),
            "total_expected_pnl": round(total_expected_pnl, 2),
            "max_loss_usd": round(max_loss, 2),
            "var_95_usd": round(var_95, 2),
            "var_99_usd": round(var_99, 2),
            "portfolio_std_usd": round(portfolio_var, 2),
        },
        "concentration": concentration,
        "correlation_flags": correlation_flags,
        "suggestions": suggestions,
    }


def main():
    parser = argparse.ArgumentParser(description="Portfolio risk analysis")
    parser.add_argument("--positions", type=str, help="JSON array of positions")
    parser.add_argument("--positions-file", type=str, help="Path to positions JSON")
    parser.add_argument("--portfolio-value", type=float, default=500.0, help="Total portfolio USD")
    parser.add_argument("--correlations", type=str, default=None, help="Correlation groups JSON")

    args = parser.parse_args()

    if args.positions_file:
        with open(args.positions_file) as f:
            positions = json.load(f)
    elif args.positions:
        positions = json.loads(args.positions)
    else:
        print(json.dumps({"error": "Provide --positions or --positions-file"}))
        sys.exit(1)

    corr_groups = None
    if args.correlations:
        corr_groups = json.loads(args.correlations)

    result = analyze_portfolio_risk(
        positions=positions,
        portfolio_value=args.portfolio_value,
        correlation_groups=corr_groups,
    )

    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
