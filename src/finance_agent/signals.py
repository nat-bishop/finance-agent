"""Signal generator -- quantitative scans on market data.

Standalone script, no LLM. Run via `make signals` or `python -m finance_agent.signals`.

Reads from SQLite (market_snapshots, events), writes to signals table.

Scans:
- Arbitrage: bracket price sums != ~100%
- Wide spread: wide spreads with volume (limit order at mid captures half-spread)
- Cross-platform mismatch: same market, different prices on Kalshi vs Polymarket
- Structural arb: Kalshi brackets vs Polymarket individual markets
- Theta decay: near-expiry markets with uncertain prices
- Momentum: consistent directional price movement
- Calibration: meta-signal from prediction accuracy (10+ resolved required)
"""

from __future__ import annotations

import json
import time
from difflib import SequenceMatcher
from typing import Any

from .config import load_configs
from .database import AgentDatabase


def _norm_title(title: str) -> str:
    return title.lower().strip().replace("?", "").replace("will ", "")


def _signal(
    scan_type: str,
    ticker: str,
    strength: float,
    edge_pct: float,
    details: dict[str, Any],
    **extra: Any,
) -> dict[str, Any]:
    return {
        "scan_type": scan_type,
        "ticker": ticker,
        "signal_strength": min(1.0, round(strength, 3)),
        "estimated_edge_pct": round(edge_pct, 2),
        "details_json": details,
        **extra,
    }


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
        legs = []
        for m in markets:
            bid = m.get("yes_bid") or 0
            ask = m.get("yes_ask") or 0
            if bid or ask:
                mid_price = (bid + ask) / 2 if bid and ask else (bid or ask)
                legs.append({"ticker": m.get("ticker", ""), "mid_price": mid_price})

        if len(legs) < 2:
            continue

        price_sum = sum(leg["mid_price"] for leg in legs)
        deviation = abs(price_sum - 100)

        if deviation > 2:
            signals.append(
                _signal(
                    "arbitrage",
                    event["event_ticker"],
                    deviation / 10,
                    deviation,
                    {
                        "title": event["title"],
                        "price_sum": round(price_sum, 1),
                        "deviation_cents": round(deviation, 1),
                        "direction": "overpriced" if price_sum > 100 else "underpriced",
                        "legs": [
                            {"ticker": leg["ticker"], "mid_price": round(leg["mid_price"], 1)}
                            for leg in legs
                        ],
                        "num_markets": len(legs),
                    },
                    event_ticker=event["event_ticker"],
                )
            )

    return signals


def _generate_wide_spread_signals(db: AgentDatabase) -> list[dict[str, Any]]:
    """Find markets with wide spreads and decent volume.

    Strategy: place limit order at mid to capture half-spread as edge.
    Not market-making — single directional limit order.
    """
    signals = []

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
        volume_24h = m["volume_24h"] or 0

        # Liquidity score: combination of volume and spread
        liq_score = min(1.0, (volume_24h / 100) * (spread / 20))
        if liq_score < 0.1:
            continue

        signals.append(
            _signal(
                "wide_spread",
                m["ticker"],
                liq_score,
                spread / 2,
                {
                    "title": m["title"],
                    "spread_cents": spread,
                    "yes_bid": m["yes_bid"],
                    "yes_ask": m["yes_ask"],
                    "mid_price": m["mid_price_cents"],
                    "volume": m["volume"] or 0,
                    "volume_24h": volume_24h,
                    "open_interest": m["open_interest"],
                    "liquidity_score": round(liq_score, 3),
                },
            )
        )

    return signals


def _latest_open_markets(db: AgentDatabase, exchange: str) -> list[dict[str, Any]]:
    """Fetch the latest snapshot per market for an exchange."""
    return db.query(
        """SELECT ticker, title, mid_price_cents, implied_probability,
                  yes_bid, yes_ask, volume
           FROM market_snapshots
           WHERE exchange = ? AND status = 'open'
             AND mid_price_cents IS NOT NULL
           GROUP BY ticker HAVING captured_at = MAX(captured_at)""",
        (exchange,),
    )


def _generate_cross_platform_mismatch_signals(db: AgentDatabase) -> list[dict[str, Any]]:
    """Find equivalent markets on Kalshi and Polymarket with price discrepancies."""
    kalshi = _latest_open_markets(db, "kalshi")
    polymarket = _latest_open_markets(db, "polymarket")
    if not kalshi or not polymarket:
        return []

    # Build Polymarket lookup by normalized title
    pm_lookup: dict[str, list[dict]] = {}
    for pm in polymarket:
        n = _norm_title(pm["title"] or "")
        if n:
            pm_lookup.setdefault(n, []).append(pm)

    signals: list[dict[str, Any]] = []
    for km in kalshi:
        kn = _norm_title(km["title"] or "")
        if not kn:
            continue

        # Try exact match first, then fuzzy
        matches = pm_lookup.get(kn, [])
        if not matches:
            for pn, pms in pm_lookup.items():
                if SequenceMatcher(None, kn, pn).ratio() > 0.8:
                    matches = pms
                    break

        for pm in matches:
            k_prob = km["implied_probability"] or km["mid_price_cents"] / 100
            p_prob = pm["implied_probability"] or pm["mid_price_cents"] / 100
            diff_pct = abs(k_prob - p_prob) * 100

            if diff_pct < 2.0:
                continue

            signals.append(
                _signal(
                    "cross_platform_mismatch",
                    km["ticker"],
                    diff_pct / 15,
                    diff_pct,
                    {
                        "kalshi_ticker": km["ticker"],
                        "polymarket_slug": pm["ticker"],
                        "kalshi_prob": round(k_prob, 4),
                        "polymarket_prob": round(p_prob, 4),
                        "diff_pct": round(diff_pct, 2),
                        "direction": "kalshi_high" if k_prob > p_prob else "polymarket_high",
                    },
                    exchange="cross_platform",
                )
            )
    return signals


def _generate_structural_arb_signals(db: AgentDatabase) -> list[dict[str, Any]]:
    """Find structural arb between Kalshi brackets and Polymarket individual markets."""
    events = db.query(
        "SELECT event_ticker, title, markets_json FROM events WHERE mutually_exclusive = 1"
    )
    pm_markets = _latest_open_markets(db, "polymarket")
    if not events or not pm_markets:
        return []

    pm_by_title = {_norm_title(m["title"] or ""): m for m in pm_markets if m["title"]}

    signals: list[dict[str, Any]] = []
    for event in events:
        try:
            k_markets = json.loads(event["markets_json"])
        except (json.JSONDecodeError, TypeError):
            continue
        if len(k_markets) < 2:
            continue

        matched = [
            {"kalshi": km, "polymarket": pm_by_title[_norm_title(km.get("title", ""))]}
            for km in k_markets
            if _norm_title(km.get("title", "")) in pm_by_title
        ]

        if len(matched) < 2:
            continue

        k_sum = sum(
            ((m["kalshi"].get("yes_bid", 0) or 0) + (m["kalshi"].get("yes_ask", 0) or 0)) / 2
            for m in matched
        )
        p_sum = sum(m["polymarket"]["mid_price_cents"] for m in matched)

        diff = abs(k_sum - p_sum)
        if diff < 3:
            continue

        signals.append(
            _signal(
                "structural_arb",
                event["event_ticker"],
                diff / 15,
                diff / len(matched),
                {
                    "event_title": event["title"],
                    "kalshi_sum": round(k_sum, 1),
                    "polymarket_sum": round(p_sum, 1),
                    "diff_cents": round(diff, 1),
                    "matched_legs": len(matched),
                    "total_legs": len(k_markets),
                },
                event_ticker=event["event_ticker"],
                exchange="cross_platform",
            )
        )
    return signals


def _generate_theta_decay_signals(db: AgentDatabase) -> list[dict[str, Any]]:
    """Find near-expiry markets with uncertain prices.

    Markets with <3 days to expiration and mid_price between 20-80 cents
    are converging rapidly. Signal strength = proximity to expiry * distance from 50%.
    """
    signals = []

    markets = db.query(
        """SELECT ticker, exchange, title, mid_price_cents, days_to_expiration,
                  yes_bid, yes_ask, volume
           FROM market_snapshots
           WHERE status = 'open'
             AND days_to_expiration IS NOT NULL
             AND days_to_expiration < 3
             AND mid_price_cents BETWEEN 20 AND 80
           GROUP BY ticker HAVING captured_at = MAX(captured_at)
           ORDER BY days_to_expiration ASC
           LIMIT 30"""
    )

    for m in markets:
        dte = m["days_to_expiration"]
        mid = m["mid_price_cents"]
        dist_from_50 = abs(mid - 50) / 50  # 0 at 50, 1 at 0/100

        strength = (1 - dte / 3) * dist_from_50 * 2
        if strength < 0.2:
            continue

        signals.append(
            _signal(
                "theta_decay",
                m["ticker"],
                strength,
                dist_from_50 * 10,
                {
                    "title": m["title"],
                    "mid_price_cents": mid,
                    "days_to_expiration": round(dte, 2),
                    "dist_from_50": round(dist_from_50, 3),
                    "yes_bid": m["yes_bid"],
                    "yes_ask": m["yes_ask"],
                    "volume": m["volume"],
                },
                exchange=m["exchange"],
            )
        )

    return signals


def _generate_momentum_signals(db: AgentDatabase) -> list[dict[str, Any]]:
    """Find markets with consistent directional price movement.

    Markets with 3+ snapshots in 48h showing >5 cent consistent direction.
    Useful for confirming/rejecting cross-platform mismatches.
    """
    signals = []

    # Get markets with multiple recent snapshots
    candidates = db.query(
        """SELECT ticker, exchange, title,
                  GROUP_CONCAT(mid_price_cents) as prices,
                  COUNT(*) as snap_count,
                  MIN(mid_price_cents) as min_price,
                  MAX(mid_price_cents) as max_price
           FROM market_snapshots
           WHERE status = 'open'
             AND mid_price_cents IS NOT NULL
             AND captured_at > datetime('now', '-48 hours')
           GROUP BY ticker
           HAVING COUNT(*) >= 3
           ORDER BY (MAX(mid_price_cents) - MIN(mid_price_cents)) DESC
           LIMIT 30"""
    )

    for m in candidates:
        prices_str = m["prices"]
        if not prices_str:
            continue
        prices = [int(p) for p in prices_str.split(",") if p.strip()]
        if len(prices) < 3:
            continue

        move = prices[-1] - prices[0]
        abs_move = abs(move)

        if abs_move < 5:
            continue

        # Check consistency: are most moves in the same direction?
        same_dir = sum(1 for i in range(1, len(prices)) if (prices[i] - prices[i - 1]) * move > 0)
        consistency = same_dir / (len(prices) - 1)

        if consistency < 0.6:
            continue

        signals.append(
            _signal(
                "momentum",
                m["ticker"],
                abs_move / 20 * consistency,
                abs_move / 2,
                {
                    "title": m["title"],
                    "direction": "up" if move > 0 else "down",
                    "move_cents": move,
                    "snapshots": len(prices),
                    "consistency": round(consistency, 2),
                    "first_price": prices[0],
                    "last_price": prices[-1],
                },
                exchange=m["exchange"],
            )
        )

    return signals


def _generate_calibration_signals(db: AgentDatabase) -> list[dict[str, Any]]:
    """Meta-signal from prediction accuracy.

    Only runs when 10+ predictions have been resolved. Reports Brier score
    and per-bucket calibration so the agent can adjust its confidence.
    """
    resolved = db.query(
        """SELECT prediction, outcome
           FROM predictions
           WHERE outcome IS NOT NULL"""
    )

    if len(resolved) < 10:
        return []

    # Brier score
    brier = sum((r["prediction"] - r["outcome"]) ** 2 for r in resolved) / len(resolved)

    # Bucket calibration (0-0.2, 0.2-0.4, 0.4-0.6, 0.6-0.8, 0.8-1.0)
    buckets: dict[str, dict] = {}
    for label, lo, hi in [
        ("0-20%", 0.0, 0.2),
        ("20-40%", 0.2, 0.4),
        ("40-60%", 0.4, 0.6),
        ("60-80%", 0.6, 0.8),
        ("80-100%", 0.8, 1.01),
    ]:
        in_bucket = [r for r in resolved if lo <= r["prediction"] < hi]
        if in_bucket:
            avg_pred = sum(r["prediction"] for r in in_bucket) / len(in_bucket)
            avg_outcome = sum(r["outcome"] for r in in_bucket) / len(in_bucket)
            buckets[label] = {
                "count": len(in_bucket),
                "avg_prediction": round(avg_pred, 3),
                "avg_outcome": round(avg_outcome, 3),
                "calibration_error": round(abs(avg_pred - avg_outcome), 3),
            }

    strength = max(0.1, 1.0 - brier * 4)
    return [
        _signal(
            "calibration",
            "META_CALIBRATION",
            strength,
            (1 - brier) * 100,
            {
                "brier_score": round(brier, 4),
                "total_predictions": len(resolved),
                "buckets": buckets,
            },
            exchange="meta",
        )
    ]


_SCANS: list[tuple[str, Any]] = [
    ("arbitrage", _generate_arbitrage_signals),
    ("wide_spread", _generate_wide_spread_signals),
    ("cross_platform_mismatch", _generate_cross_platform_mismatch_signals),
    ("structural_arb", _generate_structural_arb_signals),
    ("theta_decay", _generate_theta_decay_signals),
    ("momentum", _generate_momentum_signals),
    ("calibration", _generate_calibration_signals),
]


def run_signals() -> None:
    """Main entry point for the signal generator."""
    _, trading_config = load_configs()
    db = AgentDatabase(trading_config.db_path)

    start = time.time()
    print("Signal generator starting")
    print(f"DB: {trading_config.db_path}")

    expired = db.expire_old_signals(max_age_hours=48)
    if expired:
        print(f"Expired {expired} old signals")

    all_signals: list[dict[str, Any]] = []
    for name, func in _SCANS:
        try:
            results = func(db)
            all_signals.extend(results)
            print(f"  {name}: {len(results)} signals")
        except Exception as e:
            print(f"  {name}: ERROR -- {e}")

    if all_signals:
        count = db.insert_signals(all_signals)
        print(f"\nInserted {count} signals")
    else:
        print("\nNo signals generated (need data -- run `make collect` first)")

    elapsed = time.time() - start
    print(f"Signal generation complete in {elapsed:.1f}s")
    db.close()


if __name__ == "__main__":
    run_signals()
