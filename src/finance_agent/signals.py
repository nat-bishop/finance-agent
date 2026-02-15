"""Signal generator -- quantitative scans on market data.

Standalone script, no LLM. Run via `make signals` or `python -m finance_agent.signals`.

Reads from SQLite (market_snapshots, events), writes to signals table.

Scans:
- Arbitrage: bracket price sums != ~100%
- Wide spread: wide spreads with volume (limit order at mid captures half-spread)
- Theta decay: near-expiry markets with uncertain prices
- Momentum: consistent directional price movement
"""

from __future__ import annotations

import json
import time
from typing import Any

from .config import load_configs
from .database import AgentDatabase


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


_SCANS: list[tuple[str, Any]] = [
    ("arbitrage", _generate_arbitrage_signals),
    ("wide_spread", _generate_wide_spread_signals),
    ("theta_decay", _generate_theta_decay_signals),
    ("momentum", _generate_momentum_signals),
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
