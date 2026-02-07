#!/usr/bin/env python3
"""Binary option pricing and Greeks for prediction markets.

Usage:
    python pricing.py --market-price 55 --time-to-expiry-days 30 --model-prob 0.62
    python pricing.py --market-price 55 --time-to-expiry-days 30 --historical-prices '[50,52,55,53]'
"""

import argparse
import json
import math
import sys

import numpy as np
from scipy import stats as sp_stats


def estimate_volatility(prices: list[float]) -> dict:
    """Estimate volatility from a price series (in cents).

    Returns annualized and daily volatility.
    """
    if len(prices) < 3:
        return {"error": "Need at least 3 price observations"}

    prices_arr = np.array(prices, dtype=float)
    # Clamp prices to [1, 99] to avoid log(0)
    prices_arr = np.clip(prices_arr, 1, 99)

    # Log returns
    log_returns = np.diff(np.log(prices_arr / 100))

    daily_vol = float(np.std(log_returns, ddof=1))
    annual_vol = daily_vol * math.sqrt(252)

    return {
        "daily_vol": round(daily_vol, 6),
        "annual_vol": round(annual_vol, 6),
        "n_observations": len(prices),
        "mean_return": round(float(np.mean(log_returns)), 6),
    }


def binary_option_greeks(
    market_price_cents: int,
    time_to_expiry_days: float,
    volatility: float | None = None,
    model_prob: float | None = None,
) -> dict:
    """Compute Greeks analogues for a binary prediction market.

    Args:
        market_price_cents: Current YES price (1-99)
        time_to_expiry_days: Days until settlement
        volatility: Annual volatility of the price process
        model_prob: Independent probability estimate (0-1)

    Returns:
        Greeks and pricing analysis dict.
    """
    p_implied = market_price_cents / 100
    T = max(time_to_expiry_days / 365, 0.001)  # in years

    if volatility is None:
        volatility = 0.5  # default assumption

    # Greeks require non-extreme probabilities
    if 0.01 < p_implied < 0.99:
        z = sp_stats.norm.ppf(p_implied)
        phi_z = sp_stats.norm.pdf(z)
        sqrt_T = math.sqrt(T)

        delta = float(phi_z / (volatility * sqrt_T))
        gamma = float(-z * phi_z / (volatility**2 * T))
        theta_daily = float(phi_z * z * volatility / (2 * sqrt_T) / 365)
        vega = float(-phi_z * z * sqrt_T)
    else:
        delta = 0.0
        gamma = 0.0
        theta_daily = 0.0
        vega = 0.0

    result = {
        "implied_probability": round(p_implied, 4),
        "time_to_expiry_days": time_to_expiry_days,
        "volatility_annual": round(volatility, 4),
        "greeks": {
            "delta": round(delta, 4),
            "gamma": round(gamma, 4),
            "theta_daily_cents": round(theta_daily * 100, 4),
            "vega": round(vega, 4),
        },
        "time_analysis": {
            "optionality_remaining": round(volatility * math.sqrt(T), 4),
            "days_to_half_life": round(T * 365 / 4, 1),  # rough half-life estimate
        },
    }

    # Edge assessment
    if model_prob is not None:
        edge = model_prob - p_implied
        edge_pct = edge * 100

        result["edge_analysis"] = {
            "model_probability": round(model_prob, 4),
            "edge": round(edge, 4),
            "edge_pct": round(edge_pct, 2),
            "direction": "BUY YES" if edge > 0 else "BUY NO" if edge < 0 else "NO EDGE",
            "edge_after_3pct_fee": round(edge_pct - 3.0, 2),
        }

    return result


def main():
    parser = argparse.ArgumentParser(description="Binary option pricing for prediction markets")
    parser.add_argument("--market-price", type=int, required=True, help="YES price in cents (1-99)")
    parser.add_argument("--time-to-expiry-days", type=float, required=True, help="Days to settlement")
    parser.add_argument("--historical-prices", type=str, default=None, help="JSON array of historical prices")
    parser.add_argument("--model-prob", type=float, default=None, help="Your probability estimate (0-1)")
    parser.add_argument("--volatility", type=float, default=None, help="Override annual volatility")

    args = parser.parse_args()

    vol = args.volatility
    vol_data = None

    if args.historical_prices and vol is None:
        prices = json.loads(args.historical_prices)
        vol_data = estimate_volatility(prices)
        if "error" not in vol_data:
            vol = vol_data["annual_vol"]

    result = binary_option_greeks(
        market_price_cents=args.market_price,
        time_to_expiry_days=args.time_to_expiry_days,
        volatility=vol,
        model_prob=args.model_prob,
    )

    if vol_data:
        result["volatility_estimation"] = vol_data

    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
