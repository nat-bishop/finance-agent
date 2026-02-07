#!/usr/bin/env python3
"""GARCH volatility forecasting for prediction markets.

Usage:
    python garch_volatility.py --data-file data/prices.csv --column close
    python garch_volatility.py --data-file data/prices.csv --column close --forecast-horizon 10
"""

import argparse
import json
import sys
import warnings

import numpy as np
import pandas as pd
from arch import arch_model

warnings.filterwarnings("ignore")


def fit_garch(
    series: pd.Series,
    forecast_horizon: int = 10,
) -> dict:
    """Fit GARCH(1,1) and forecast volatility.

    Args:
        series: Price or return series
        forecast_horizon: Number of periods to forecast volatility

    Returns:
        Dict with model parameters, current vol, forecast, regime classification.
    """
    if len(series) < 30:
        return {"error": "Need at least 30 observations for GARCH"}

    # Compute returns (percentage)
    returns = series.pct_change().dropna() * 100

    if len(returns) < 20:
        return {"error": "Insufficient return observations after differencing"}

    # Fit GARCH(1,1)
    model = arch_model(returns, vol="Garch", p=1, q=1, mean="Constant", dist="Normal")
    fit = model.fit(disp="off")

    # Extract parameters
    omega = float(fit.params.get("omega", 0))
    alpha = float(fit.params.get("alpha[1]", 0))
    beta = float(fit.params.get("beta[1]", 0))
    persistence = alpha + beta

    # Long-run variance
    if persistence < 1:
        long_run_var = omega / (1 - persistence)
        long_run_vol = float(np.sqrt(long_run_var))
    else:
        long_run_var = None
        long_run_vol = None

    # Current conditional volatility
    conditional_vol = float(fit.conditional_volatility.iloc[-1])

    # Forecast
    fc = fit.forecast(horizon=forecast_horizon)
    vol_forecast = []
    for h in range(forecast_horizon):
        vol_forecast.append({
            "step": h + 1,
            "variance_forecast": round(float(fc.variance.iloc[-1, h]), 6),
            "volatility_forecast": round(float(np.sqrt(fc.variance.iloc[-1, h])), 4),
        })

    # Regime classification
    if long_run_vol is not None:
        ratio = conditional_vol / long_run_vol
        if ratio < 0.7:
            regime = "low_volatility"
            regime_action = "Normal position sizes, tighter stops"
        elif ratio < 1.3:
            regime = "normal_volatility"
            regime_action = "Normal operations"
        elif ratio < 2.0:
            regime = "high_volatility"
            regime_action = "Reduce position sizes by 50%, widen stops"
        else:
            regime = "extreme_volatility"
            regime_action = "Minimal trading, preserve capital"
    else:
        regime = "unstable"
        ratio = None
        regime_action = "Model unstable — use caution"

    return {
        "model": "GARCH(1,1)",
        "n_observations": len(returns),
        "parameters": {
            "omega": round(omega, 6),
            "alpha": round(alpha, 6),
            "beta": round(beta, 6),
            "persistence": round(persistence, 6),
        },
        "current_state": {
            "conditional_volatility_pct": round(conditional_vol, 4),
            "long_run_volatility_pct": round(long_run_vol, 4) if long_run_vol else None,
            "vol_ratio": round(ratio, 4) if ratio else None,
            "regime": regime,
            "regime_action": regime_action,
        },
        "forecast": vol_forecast,
        "model_fit": {
            "log_likelihood": round(float(fit.loglikelihood), 2),
            "aic": round(float(fit.aic), 2),
            "bic": round(float(fit.bic), 2),
        },
    }


def main():
    parser = argparse.ArgumentParser(description="GARCH volatility forecast")
    parser.add_argument("--data-file", type=str, required=True, help="CSV file path")
    parser.add_argument("--column", type=str, required=True, help="Price column name")
    parser.add_argument("--forecast-horizon", type=int, default=10, help="Forecast horizon")

    args = parser.parse_args()

    try:
        df = pd.read_csv(args.data_file)
    except FileNotFoundError:
        print(json.dumps({"error": f"File not found: {args.data_file}"}))
        sys.exit(1)

    if args.column not in df.columns:
        print(json.dumps({"error": f"Column '{args.column}' not found. Available: {list(df.columns)}"}))
        sys.exit(1)

    series = df[args.column].dropna()
    result = fit_garch(series, forecast_horizon=args.forecast_horizon)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
