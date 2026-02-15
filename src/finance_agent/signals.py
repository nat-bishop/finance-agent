"""Signal generator -- quantitative scans on market data.

Standalone script, no LLM. Run via `make signals` or `python -m finance_agent.signals`.

Reads from SQLite (market_snapshots, events), writes to signals table.

Scans:
- Arbitrage: bracket price sums != ~100%
- Cross-platform candidate: title-matched pairs with price gaps across exchanges
"""

from __future__ import annotations

import json
import re
import time
from difflib import SequenceMatcher
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


def _norm_title(t: str) -> str:
    """Normalize market title for fuzzy matching."""
    t = t.lower().strip()
    t = re.sub(r'[?!.,;:\'"()]', "", t)
    t = re.sub(r"\b(will|the|be|a|an|to|in|on|by|of)\b", "", t)
    return re.sub(r"\s+", " ", t).strip()


def _generate_cross_platform_signals(db: AgentDatabase) -> list[dict[str, Any]]:
    """Find cross-platform pairs with similar titles and price gaps.

    Matches Kalshi and Polymarket markets by normalized title similarity,
    then filters by price gap and volume. These are CANDIDATES only — the
    agent must verify settlement equivalence before recommending.
    """
    signals: list[dict[str, Any]] = []

    kalshi_markets = db.query(
        """SELECT ticker, title, mid_price_cents, volume_24h, volume
           FROM market_snapshots
           WHERE exchange = 'kalshi' AND status = 'open'
             AND mid_price_cents IS NOT NULL
           GROUP BY ticker
           HAVING captured_at = MAX(captured_at)"""
    )

    poly_markets = db.query(
        """SELECT ticker, title, mid_price_cents, volume_24h, volume
           FROM market_snapshots
           WHERE exchange = 'polymarket' AND status = 'open'
             AND mid_price_cents IS NOT NULL
           GROUP BY ticker
           HAVING captured_at = MAX(captured_at)"""
    )

    if not kalshi_markets or not poly_markets:
        return signals

    # Pre-normalize polymarket titles
    poly_normed = [(m, _norm_title(m["title"] or "")) for m in poly_markets]

    for km in kalshi_markets:
        kn = _norm_title(km["title"] or "")
        if not kn:
            continue

        best_score = 0.0
        best_pm: dict[str, Any] | None = None
        for pm, pn in poly_normed:
            score = SequenceMatcher(None, kn, pn).ratio()
            if score > best_score:
                best_score, best_pm = score, pm

        if best_score < 0.7 or best_pm is None:
            continue

        k_mid = km["mid_price_cents"]
        p_mid = best_pm["mid_price_cents"]
        gap = abs(k_mid - p_mid)

        if gap < 3:
            continue

        # At least one market should have some volume
        k_vol = km["volume_24h"] or km["volume"] or 0
        p_vol = best_pm["volume_24h"] or best_pm["volume"] or 0
        if k_vol == 0 and p_vol == 0:
            continue

        # Strength: weighted combination of similarity, gap, and liquidity
        liq_score = min(1.0, (k_vol + p_vol) / 200)
        strength = best_score * (gap / 20) * (0.5 + 0.5 * liq_score)

        direction = "buy_kalshi" if k_mid < p_mid else "buy_polymarket"

        signals.append(
            _signal(
                "cross_platform_candidate",
                km["ticker"],
                strength,
                gap,  # Gross gap, not fee-adjusted
                {
                    "kalshi_ticker": km["ticker"],
                    "kalshi_title": km["title"],
                    "kalshi_mid": k_mid,
                    "polymarket_slug": best_pm["ticker"],
                    "polymarket_title": best_pm["title"],
                    "polymarket_mid": p_mid,
                    "price_gap_cents": gap,
                    "title_similarity": round(best_score, 3),
                    "needs_verification": best_score < 0.9,
                    "direction": direction,
                },
            )
        )

    # Return top 20 by estimated edge (gap)
    signals.sort(key=lambda s: s["estimated_edge_pct"], reverse=True)
    return signals[:20]


_SCANS: list[tuple[str, Any]] = [
    ("arbitrage", _generate_arbitrage_signals),
    ("cross_platform_candidate", _generate_cross_platform_signals),
]


def run_signals() -> None:
    """Main entry point for the signal generator."""
    _, _, trading_config = load_configs()
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
