"""Signal generator -- quantitative scans on market data.

Standalone script, no LLM. Run via `make signals` or `python -m finance_agent.signals`.

Reads from SQLite (market_snapshots, events), writes to signals table.

Scans:
- Arbitrage: bracket price sums != ~100%
"""

from __future__ import annotations

import json
import logging
import time
from typing import Any

from .config import load_configs
from .database import AgentDatabase
from .fees import kalshi_fee

logger = logging.getLogger(__name__)


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


def _build_legs_from_event(
    event: dict[str, Any], snapshot_map: dict[str, dict[str, Any]]
) -> list[dict[str, Any]] | None:
    """Parse event markets and build enriched legs with mid-prices.

    Returns None if the event should be skipped (bad JSON, <2 legs, all dead).
    """
    try:
        markets = json.loads(event["markets_json"])
    except (json.JSONDecodeError, TypeError):
        return None

    if len(markets) < 2:
        return None

    legs = []
    for m in markets:
        bid = m.get("yes_bid") or 0
        ask = m.get("yes_ask") or 0
        if bid or ask:
            mid_price = (bid + ask) / 2 if bid and ask else (bid or ask)
            ticker = m.get("ticker", "")
            snap = snapshot_map.get(ticker, {})
            legs.append(
                {
                    "ticker": ticker,
                    "mid_price": mid_price,
                    "spread": snap.get("spread_cents"),
                    "volume_24h": snap.get("volume_24h") or snap.get("volume") or 0,
                }
            )

    if len(legs) < 2:
        return None

    # Skip if ALL legs are dead (no volume and wide spread)
    if all(leg["volume_24h"] == 0 and (leg["spread"] or 0) > 20 for leg in legs):
        return None

    return legs


def _compute_arb_edge_and_strength(
    legs: list[dict[str, Any]],
) -> tuple[float, float, float, float, float] | None:
    """Compute fee-adjusted edge and liquidity-weighted strength.

    Returns (price_sum, deviation, net_edge_pct, strength, total_fees_usd)
    or None if not profitable.
    """
    price_sum = sum(leg["mid_price"] for leg in legs)
    deviation = abs(price_sum - 100)

    if deviation <= 2:
        return None

    est_contracts = 100
    total_fees_usd = sum(
        kalshi_fee(est_contracts, round(leg["mid_price"]))
        for leg in legs
        if 1 <= round(leg["mid_price"]) <= 99
    )
    gross_edge_usd = est_contracts * deviation / 100.0
    net_edge_usd = gross_edge_usd - total_fees_usd
    net_edge_pct = (net_edge_usd / est_contracts) * 100

    if net_edge_pct <= 0:
        return None

    min_vol = min(leg["volume_24h"] for leg in legs)
    liquidity_factor = min(1.0, min_vol / 100) if min_vol > 0 else 0.1
    strength = (deviation / 10) * liquidity_factor

    return price_sum, deviation, net_edge_pct, strength, total_fees_usd


def _generate_arbitrage_signals(db: AgentDatabase) -> list[dict[str, Any]]:
    """Find events where bracket YES prices don't sum to ~100%."""
    signals = []

    snapshots = db.get_latest_snapshots(exchange="kalshi", status="open")
    snapshot_map = {s["ticker"]: s for s in snapshots}
    events = db.get_mutually_exclusive_events()

    for event in events:
        legs = _build_legs_from_event(event, snapshot_map)
        if legs is None:
            continue

        result = _compute_arb_edge_and_strength(legs)
        if result is None:
            continue

        price_sum, deviation, net_edge_pct, strength, total_fees_usd = result

        signals.append(
            _signal(
                "arbitrage",
                event["event_ticker"],
                strength,
                round(net_edge_pct, 2),
                {
                    "title": event["title"],
                    "price_sum": round(price_sum, 1),
                    "deviation_cents": round(deviation, 1),
                    "gross_edge_pct": round(deviation, 2),
                    "estimated_fees_usd": round(total_fees_usd, 4),
                    "direction": "overpriced" if price_sum > 100 else "underpriced",
                    "legs": [
                        {
                            "ticker": leg["ticker"],
                            "mid_price": round(leg["mid_price"], 1),
                            "spread": leg["spread"],
                            "volume_24h": leg["volume_24h"],
                        }
                        for leg in legs
                    ],
                    "num_markets": len(legs),
                    "min_leg_volume_24h": min(leg["volume_24h"] for leg in legs),
                    "max_leg_spread": max((leg["spread"] or 0) for leg in legs),
                },
                event_ticker=event["event_ticker"],
            )
        )

    return signals


_SCANS: list[tuple[str, Any]] = [
    ("arbitrage", _generate_arbitrage_signals),
]


def generate_signals(db: AgentDatabase) -> int:
    """Run signal generation against an existing DB. Returns count inserted.

    Clears pending signals first to avoid duplicates when called from
    both the collector and TUI startup.
    """
    db.expire_old_signals(max_age_hours=48)
    db.clear_pending_signals()

    all_signals: list[dict[str, Any]] = []
    for name, func in _SCANS:
        try:
            results = func(db)
            all_signals.extend(results)
            logger.info("  %s: %d signals", name, len(results))
        except Exception:
            logger.exception("  %s: scan failed", name)

    if all_signals:
        count = db.insert_signals(all_signals)
        logger.info("Inserted %d signals", count)
        return count
    return 0


def run_signals() -> None:
    """Main entry point for the signal generator (standalone `make signals`)."""
    from .logging_config import setup_logging

    setup_logging()

    _, _, trading_config = load_configs()
    db = AgentDatabase(trading_config.db_path)

    start = time.time()
    logger.info("Signal generator starting")
    logger.info("DB: %s", trading_config.db_path)

    count = generate_signals(db)
    if not count:
        logger.info("No signals generated (need data -- run `make collect` first)")

    elapsed = time.time() - start
    logger.info("Signal generation complete in %.1fs", elapsed)
    db.close()


if __name__ == "__main__":
    run_signals()
