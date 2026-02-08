"""Signal generator — quantitative scans on market data.

Standalone script, no LLM. Run via `make signals` or `python -m finance_agent.signals`.

Reads from SQLite (market_snapshots, events), writes to signals table.

Scans:
- Arbitrage: bracket price sums != ~100%
- Spread: wide spreads with volume
- Mean reversion: z-score of recent price moves
- Theta decay: near-expiry markets with unresolved prices
- Calibration: systematic bias in predictions vs outcomes
- Time-series: ARIMA forecast vs current price
"""

from __future__ import annotations

import json
import time
from typing import Any

import numpy as np

from .config import load_configs
from .database import AgentDatabase


def _generate_arbitrage_signals(db: AgentDatabase) -> list[dict[str, Any]]:
    """Find events where bracket YES prices don't sum to ~100%.

    For mutually exclusive events, sum of all YES prices should be ~100.
    Deviations indicate arbitrage opportunity.
    """
    signals = []

    events = db.query(
        """SELECT event_ticker, title, category, mutually_exclusive, markets_json
           FROM events WHERE mutually_exclusive = 1 AND markets_json IS NOT NULL"""
    )

    for event in events:
        try:
            markets = json.loads(event["markets_json"])
        except (json.JSONDecodeError, TypeError):
            continue

        if len(markets) < 2:
            continue

        # Use mid-price (average of bid/ask) for each market
        prices = []
        tickers = []
        for m in markets:
            bid = m.get("yes_bid") or 0
            ask = m.get("yes_ask") or 0
            if bid and ask:
                prices.append((bid + ask) / 2)
                tickers.append(m.get("ticker", ""))
            elif bid or ask:
                prices.append(bid or ask)
                tickers.append(m.get("ticker", ""))

        if len(prices) < 2:
            continue

        price_sum = sum(prices)
        deviation = abs(price_sum - 100)

        # Flag if sum deviates by more than 2 cents
        if deviation > 2:
            edge_pct = deviation / 100.0 * 100  # as percentage
            signals.append(
                {
                    "scan_type": "arbitrage",
                    "ticker": event["event_ticker"],
                    "event_ticker": event["event_ticker"],
                    "signal_strength": min(1.0, deviation / 10),
                    "estimated_edge_pct": edge_pct,
                    "details_json": {
                        "title": event["title"],
                        "price_sum": round(price_sum, 1),
                        "deviation_cents": round(deviation, 1),
                        "direction": "overpriced" if price_sum > 100 else "underpriced",
                        "legs": [
                            {"ticker": t, "mid_price": round(p, 1)}
                            for t, p in zip(tickers, prices, strict=True)
                        ],
                        "num_markets": len(prices),
                    },
                }
            )

    return signals


def _generate_spread_signals(db: AgentDatabase) -> list[dict[str, Any]]:
    """Find markets with wide spreads and decent volume — market-making opportunities."""
    signals = []

    # Get latest snapshot for each market with meaningful spread
    markets = db.query(
        """SELECT ticker, title, yes_bid, yes_ask, spread_cents, volume,
                  volume_24h, open_interest, mid_price_cents
           FROM market_snapshots
           WHERE spread_cents IS NOT NULL
             AND spread_cents > 5
             AND volume > 0
             AND status = 'open'
           GROUP BY ticker
           HAVING captured_at = MAX(captured_at)
           ORDER BY spread_cents DESC
           LIMIT 50"""
    )

    for m in markets:
        spread = m["spread_cents"]
        volume = m["volume"] or 0
        volume_24h = m["volume_24h"] or 0

        # Liquidity score: combination of volume and spread
        # Higher volume + wider spread = better opportunity
        liq_score = min(1.0, (volume_24h / 100) * (spread / 20))
        if liq_score < 0.1:
            continue

        signals.append(
            {
                "scan_type": "spread",
                "ticker": m["ticker"],
                "signal_strength": min(1.0, liq_score),
                "estimated_edge_pct": spread / 2,  # half-spread as edge estimate
                "details_json": {
                    "title": m["title"],
                    "spread_cents": spread,
                    "yes_bid": m["yes_bid"],
                    "yes_ask": m["yes_ask"],
                    "mid_price": m["mid_price_cents"],
                    "volume": volume,
                    "volume_24h": volume_24h,
                    "open_interest": m["open_interest"],
                    "liquidity_score": round(liq_score, 3),
                },
            }
        )

    return signals


def _generate_mean_reversion_signals(db: AgentDatabase) -> list[dict[str, Any]]:
    """Find markets where recent price moves are extreme vs historical vol.

    Z-score of recent move relative to price history standard deviation.
    """
    signals = []

    # Get tickers with enough history (at least 10 snapshots)
    tickers = db.query(
        """SELECT ticker, COUNT(*) as cnt
           FROM market_snapshots
           WHERE mid_price_cents IS NOT NULL AND status = 'open'
           GROUP BY ticker
           HAVING cnt >= 10
           ORDER BY cnt DESC
           LIMIT 200"""
    )

    for row in tickers:
        ticker = row["ticker"]
        prices = db.query(
            """SELECT mid_price_cents, captured_at
               FROM market_snapshots
               WHERE ticker = ? AND mid_price_cents IS NOT NULL
               ORDER BY captured_at DESC
               LIMIT 50""",
            (ticker,),
        )

        if len(prices) < 10:
            continue

        price_series = [p["mid_price_cents"] for p in prices]
        current = price_series[0]
        mean = np.mean(price_series)
        std = np.std(price_series)

        if std < 1:  # No meaningful volatility
            continue

        z_score = (current - mean) / std

        if abs(z_score) > 1.5:
            # Get title from latest snapshot
            latest = db.query(
                "SELECT title FROM market_snapshots WHERE ticker = ? ORDER BY captured_at DESC LIMIT 1",
                (ticker,),
            )
            title = latest[0]["title"] if latest else ticker

            signals.append(
                {
                    "scan_type": "mean_reversion",
                    "ticker": ticker,
                    "signal_strength": min(1.0, abs(z_score) / 3),
                    "estimated_edge_pct": abs(current - mean) / 100 * 100,
                    "details_json": {
                        "title": title,
                        "current_price": current,
                        "mean_price": round(float(mean), 1),
                        "std_dev": round(float(std), 1),
                        "z_score": round(float(z_score), 2),
                        "direction": "high" if z_score > 0 else "low",
                        "data_points": len(price_series),
                    },
                }
            )

    return signals


def _generate_theta_signals(db: AgentDatabase) -> list[dict[str, Any]]:
    """Find markets near expiry with unresolved prices (20-80 range).

    These have high time-value decay — price must converge to 0 or 100.
    """
    signals = []

    markets = db.query(
        """SELECT ticker, title, mid_price_cents, days_to_expiration,
                  volume, open_interest, close_time
           FROM market_snapshots
           WHERE days_to_expiration IS NOT NULL
             AND days_to_expiration < 7
             AND days_to_expiration > 0
             AND mid_price_cents BETWEEN 20 AND 80
             AND status = 'open'
           GROUP BY ticker
           HAVING captured_at = MAX(captured_at)
           ORDER BY days_to_expiration ASC
           LIMIT 30"""
    )

    for m in markets:
        mid = m["mid_price_cents"]
        days = m["days_to_expiration"]

        # Time value: how far from 0 or 100, weighted by time pressure
        distance_from_resolution = min(mid, 100 - mid)
        time_pressure = max(0, 1 - days / 7)
        time_value_estimate = distance_from_resolution * time_pressure

        if time_value_estimate < 5:
            continue

        signals.append(
            {
                "scan_type": "theta_decay",
                "ticker": m["ticker"],
                "signal_strength": min(1.0, time_value_estimate / 30),
                "estimated_edge_pct": time_value_estimate / 100 * 100,
                "details_json": {
                    "title": m["title"],
                    "mid_price": mid,
                    "days_to_expiration": round(days, 2),
                    "time_value_estimate": round(time_value_estimate, 1),
                    "distance_from_resolution": distance_from_resolution,
                    "close_time": m["close_time"],
                    "volume": m["volume"],
                    "open_interest": m["open_interest"],
                },
            }
        )

    return signals


def _generate_calibration_signals(db: AgentDatabase) -> list[dict[str, Any]]:
    """Compare past predictions vs outcomes to find systematic biases."""
    signals: list[dict[str, Any]] = []

    # Need resolved predictions to analyze
    resolved = db.query(
        """SELECT market_ticker, prediction, market_price_cents, outcome, methodology
           FROM predictions
           WHERE outcome IS NOT NULL
           ORDER BY resolved_at DESC
           LIMIT 200"""
    )

    if len(resolved) < 10:
        return signals

    # Bin predictions by price range and check calibration
    bins: dict[int, dict[str, list]] = {}  # price_bin -> list of outcomes
    for r in resolved:
        price = r["market_price_cents"] or 50
        bin_key = (price // 10) * 10  # 0-9, 10-19, ..., 90-99
        if bin_key not in bins:
            bins[bin_key] = {"outcomes": [], "prices": []}
        bins[bin_key]["outcomes"].append(r["outcome"])
        bins[bin_key]["prices"].append(price)

    for bin_key, data in bins.items():
        if len(data["outcomes"]) < 5:
            continue

        actual_rate = np.mean(data["outcomes"])
        expected_rate = np.mean(data["prices"]) / 100
        bias = actual_rate - expected_rate

        if abs(bias) > 0.1:  # 10%+ systematic bias
            signals.append(
                {
                    "scan_type": "calibration",
                    "ticker": f"CALIBRATION-{bin_key}-{bin_key + 9}",
                    "signal_strength": min(1.0, abs(bias) * 2),
                    "estimated_edge_pct": abs(bias) * 100,
                    "details_json": {
                        "price_range": f"{bin_key}-{bin_key + 9}¢",
                        "actual_outcome_rate": round(float(actual_rate), 3),
                        "expected_rate": round(float(expected_rate), 3),
                        "bias_direction": "market_underprices"
                        if bias > 0
                        else "market_overprices",
                        "sample_size": len(data["outcomes"]),
                        "brier_score": round(
                            float(
                                np.mean(
                                    [
                                        (o - p / 100) ** 2
                                        for o, p in zip(
                                            data["outcomes"], data["prices"], strict=True
                                        )
                                    ]
                                )
                            ),
                            4,
                        ),
                    },
                }
            )

    return signals


def _generate_timeseries_signals(db: AgentDatabase) -> list[dict[str, Any]]:
    """Simple trend-following: linear regression on recent price data.

    Full ARIMA/GARCH requires statsmodels; using simple linear fit as baseline.
    """
    signals = []

    tickers = db.query(
        """SELECT ticker, COUNT(*) as cnt
           FROM market_snapshots
           WHERE mid_price_cents IS NOT NULL AND status = 'open'
           GROUP BY ticker
           HAVING cnt >= 20
           ORDER BY cnt DESC
           LIMIT 100"""
    )

    for row in tickers:
        ticker = row["ticker"]
        prices = db.query(
            """SELECT mid_price_cents, captured_at
               FROM market_snapshots
               WHERE ticker = ? AND mid_price_cents IS NOT NULL
               ORDER BY captured_at ASC""",
            (ticker,),
        )

        if len(prices) < 20:
            continue

        price_arr = np.array([p["mid_price_cents"] for p in prices], dtype=float)
        x = np.arange(len(price_arr), dtype=float)

        # Simple linear regression
        coeffs = np.polyfit(x, price_arr, 1)
        slope = coeffs[0]
        current = price_arr[-1]

        # Forecast 5 steps ahead
        forecast = np.polyval(coeffs, len(price_arr) + 5)
        forecast = float(np.clip(forecast, 1, 99))  # clamp to valid range

        divergence = abs(forecast - current)
        if divergence < 3:  # Less than 3 cents divergence
            continue

        # Get title
        latest = db.query(
            "SELECT title FROM market_snapshots WHERE ticker = ? ORDER BY captured_at DESC LIMIT 1",
            (ticker,),
        )
        title = latest[0]["title"] if latest else ticker

        # Residual std for confidence
        predicted = np.polyval(coeffs, x)
        residual_std = float(np.std(price_arr - predicted))

        signals.append(
            {
                "scan_type": "time_series",
                "ticker": ticker,
                "signal_strength": min(1.0, divergence / 15),
                "estimated_edge_pct": divergence / 100 * 100,
                "details_json": {
                    "title": title,
                    "current_price": float(current),
                    "forecast_price": round(float(forecast), 1),
                    "slope_per_step": round(float(slope), 3),
                    "direction": "up" if slope > 0 else "down",
                    "residual_std": round(residual_std, 2),
                    "confidence_band": [
                        round(float(forecast - 2 * residual_std), 1),
                        round(float(forecast + 2 * residual_std), 1),
                    ],
                    "data_points": len(price_arr),
                },
            }
        )

    return signals


def run_signals() -> None:
    """Main entry point for the signal generator."""
    _, trading_config = load_configs()
    db = AgentDatabase(trading_config.db_path)

    start = time.time()
    print("Signal generator starting")
    print(f"DB: {trading_config.db_path}")

    # Expire old signals first
    expired = db.expire_old_signals(max_age_hours=48)
    if expired:
        print(f"Expired {expired} old signals")

    all_signals: list[dict[str, Any]] = []

    scan_funcs = [
        ("arbitrage", _generate_arbitrage_signals),
        ("spread", _generate_spread_signals),
        ("mean_reversion", _generate_mean_reversion_signals),
        ("theta_decay", _generate_theta_signals),
        ("calibration", _generate_calibration_signals),
        ("time_series", _generate_timeseries_signals),
    ]

    for name, func in scan_funcs:
        try:
            results = func(db)
            all_signals.extend(results)
            print(f"  {name}: {len(results)} signals")
        except Exception as e:
            print(f"  {name}: ERROR — {e}")

    if all_signals:
        count = db.insert_signals(all_signals)
        print(f"\nInserted {count} signals")
    else:
        print("\nNo signals generated (need data — run `make collect` first)")

    elapsed = time.time() - start
    print(f"Signal generation complete in {elapsed:.1f}s")
    db.close()


if __name__ == "__main__":
    run_signals()
