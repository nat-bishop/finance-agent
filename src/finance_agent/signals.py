"""Signal generator -- quantitative scans on market data.

Standalone script, no LLM. Run via `make signals` or `python -m finance_agent.signals`.

Reads from SQLite (market_snapshots, events), writes to signals table.

Scans:
- Arbitrage: bracket price sums != ~100%
- Spread: wide spreads with volume
- Cross-platform mismatch: same market, different prices on Kalshi vs Polymarket
- Structural arb: Kalshi brackets vs Polymarket individual markets
"""

from __future__ import annotations

import json
import time
from difflib import SequenceMatcher
from typing import Any

from .config import load_configs
from .database import AgentDatabase


def _norm_title(title: str) -> str:
    """Normalize a market title for fuzzy matching."""
    return title.lower().strip().replace("?", "").replace("will ", "")


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

        # Flag if sum deviates by more than 2 cents
        if deviation > 2:
            signals.append(
                {
                    "scan_type": "arbitrage",
                    "ticker": event["event_ticker"],
                    "event_ticker": event["event_ticker"],
                    "signal_strength": min(1.0, deviation / 10),
                    "estimated_edge_pct": deviation,
                    "details_json": {
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
                }
            )

    return signals


def _generate_spread_signals(db: AgentDatabase) -> list[dict[str, Any]]:
    """Find markets with wide spreads and decent volume -- market-making opportunities."""
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
            {
                "scan_type": "spread",
                "ticker": m["ticker"],
                "signal_strength": min(1.0, liq_score),
                "estimated_edge_pct": spread / 2,
                "details_json": {
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
            }
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
                {
                    "scan_type": "cross_platform_mismatch",
                    "ticker": km["ticker"],
                    "exchange": "cross_platform",
                    "signal_strength": min(1.0, diff_pct / 15),
                    "estimated_edge_pct": round(diff_pct, 2),
                    "details_json": {
                        "kalshi_ticker": km["ticker"],
                        "polymarket_slug": pm["ticker"],
                        "kalshi_prob": round(k_prob, 4),
                        "polymarket_prob": round(p_prob, 4),
                        "diff_pct": round(diff_pct, 2),
                        "direction": "kalshi_high" if k_prob > p_prob else "polymarket_high",
                    },
                }
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
            {
                "scan_type": "structural_arb",
                "ticker": event["event_ticker"],
                "event_ticker": event["event_ticker"],
                "exchange": "cross_platform",
                "signal_strength": min(1.0, diff / 15),
                "estimated_edge_pct": round(diff / len(matched), 2),
                "details_json": {
                    "event_title": event["title"],
                    "kalshi_sum": round(k_sum, 1),
                    "polymarket_sum": round(p_sum, 1),
                    "diff_cents": round(diff, 1),
                    "matched_legs": len(matched),
                    "total_legs": len(k_markets),
                },
            }
        )
    return signals


_SCANS: list[tuple[str, Any]] = [
    ("arbitrage", _generate_arbitrage_signals),
    ("spread", _generate_spread_signals),
    ("cross_platform_mismatch", _generate_cross_platform_mismatch_signals),
    ("structural_arb", _generate_structural_arb_signals),
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
