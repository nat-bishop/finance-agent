#!/usr/bin/env python3
"""ARIMA time series forecasting for prediction markets.

Usage:
    python arima_forecast.py --data-file data/rates.csv --column rate --horizon 5
    python arima_forecast.py --data-file data/rates.csv --column rate --horizon 5 --threshold 4.5
"""

import argparse
import json
import sys
import warnings

import numpy as np
import pandas as pd
from scipy import stats as sp_stats
from statsmodels.tsa.stattools import adfuller
from statsmodels.tsa.arima.model import ARIMA

warnings.filterwarnings("ignore")


def auto_arima(series: pd.Series, max_p: int = 5, max_d: int = 2, max_q: int = 5) -> dict:
    """Auto-select ARIMA(p,d,q) using AIC.

    Args:
        series: Time series data
        max_p, max_d, max_q: Maximum order for each parameter

    Returns:
        Dict with best model parameters and diagnostics.
    """
    # Determine d via ADF test
    best_d = 0
    for d in range(max_d + 1):
        if d == 0:
            test_series = series
        else:
            test_series = series.diff(d).dropna()

        adf_result = adfuller(test_series, autolag="AIC")
        if adf_result[1] < 0.05:  # stationary
            best_d = d
            break
    else:
        best_d = max_d

    # Grid search for best p, q
    best_aic = float("inf")
    best_order = (0, best_d, 0)
    results_log = []

    for p in range(max_p + 1):
        for q in range(max_q + 1):
            if p == 0 and q == 0:
                continue
            try:
                model = ARIMA(series, order=(p, best_d, q))
                fit = model.fit()
                results_log.append({
                    "order": f"({p},{best_d},{q})",
                    "aic": round(fit.aic, 2),
                    "bic": round(fit.bic, 2),
                })
                if fit.aic < best_aic:
                    best_aic = fit.aic
                    best_order = (p, best_d, q)
            except Exception:
                continue

    return {
        "best_order": best_order,
        "best_aic": round(best_aic, 2),
        "stationarity_d": best_d,
        "models_tested": len(results_log),
        "top_models": sorted(results_log, key=lambda x: x["aic"])[:5],
    }


def forecast_arima(
    series: pd.Series,
    horizon: int = 5,
    order: tuple | None = None,
    threshold: float | None = None,
) -> dict:
    """Fit ARIMA and generate forecast with confidence intervals.

    Args:
        series: Time series data
        horizon: Number of periods to forecast
        order: (p,d,q) tuple, or None for auto-selection
        threshold: Optional threshold for binary probability calculation

    Returns:
        Forecast dict with point estimates, intervals, and probability.
    """
    if len(series) < 10:
        return {"error": "Need at least 10 data points for ARIMA"}

    # Auto-select order if not provided
    if order is None:
        selection = auto_arima(series)
        order = selection["best_order"]
    else:
        selection = {"best_order": order}

    # Fit model
    model = ARIMA(series, order=order)
    fit = model.fit()

    # Forecast
    fc = fit.get_forecast(steps=horizon)
    mean_forecast = fc.predicted_mean.values
    conf_int = fc.conf_int(alpha=0.05)  # 95% CI

    forecasts = []
    for i in range(horizon):
        entry = {
            "step": i + 1,
            "forecast": round(float(mean_forecast[i]), 4),
            "ci_lower_95": round(float(conf_int.iloc[i, 0]), 4),
            "ci_upper_95": round(float(conf_int.iloc[i, 1]), 4),
        }

        # If threshold given, compute probability of exceeding it
        if threshold is not None:
            forecast_std = (conf_int.iloc[i, 1] - conf_int.iloc[i, 0]) / (2 * 1.96)
            if forecast_std > 0:
                z = (threshold - mean_forecast[i]) / forecast_std
                prob_above = float(1 - sp_stats.norm.cdf(z))
                entry["prob_above_threshold"] = round(prob_above, 4)
                entry["prob_below_threshold"] = round(1 - prob_above, 4)

        forecasts.append(entry)

    # Model diagnostics
    residuals = fit.resid
    ljung_box = fit.test_serial_correlation("ljungbox", lags=[10])

    return {
        "model_order": list(order),
        "selection": selection,
        "n_observations": len(series),
        "forecasts": forecasts,
        "diagnostics": {
            "aic": round(fit.aic, 2),
            "bic": round(fit.bic, 2),
            "residual_mean": round(float(residuals.mean()), 6),
            "residual_std": round(float(residuals.std()), 6),
        },
        "threshold": threshold,
    }


def main():
    parser = argparse.ArgumentParser(description="ARIMA time series forecast")
    parser.add_argument("--data-file", type=str, required=True, help="CSV file path")
    parser.add_argument("--column", type=str, required=True, help="Column to forecast")
    parser.add_argument("--horizon", type=int, default=5, help="Forecast horizon")
    parser.add_argument("--threshold", type=float, default=None, help="Threshold for probability")
    parser.add_argument("--order", type=str, default=None, help="ARIMA order as 'p,d,q'")

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
    order = None
    if args.order:
        parts = [int(x) for x in args.order.split(",")]
        order = tuple(parts)

    result = forecast_arima(series, horizon=args.horizon, order=order, threshold=args.threshold)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
