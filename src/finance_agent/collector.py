"""Data collector — snapshots market data to SQLite.

Standalone script, no LLM. Run via `make collect` or `python -m finance_agent.collector`.

Collection schedule (all in one run):
- All open markets (paginated) → market_snapshots
- Event structure (paginated) → events
- Recently settled markets → market_snapshots (for calibration)
"""

from __future__ import annotations

import json
import time
from datetime import UTC, datetime
from typing import Any

from .config import load_configs
from .database import AgentDatabase
from .kalshi_client import KalshiAPIClient
from .polymarket_client import PolymarketAPIClient
from .rate_limiter import RateLimiter


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


def _compute_derived(market: dict[str, Any], now: str) -> dict[str, Any]:
    """Compute derived fields from raw market data."""
    yes_bid = market.get("yes_bid") or 0
    yes_ask = market.get("yes_ask") or 0

    spread = yes_ask - yes_bid if yes_ask and yes_bid else None
    mid = (yes_bid + yes_ask) // 2 if yes_ask and yes_bid else None
    implied_prob = mid / 100.0 if mid else None

    # Days to expiration
    days_to_exp = None
    close_time = market.get("close_time") or market.get("expected_expiration_time")
    if close_time:
        try:
            if isinstance(close_time, str):
                close_dt = datetime.fromisoformat(close_time.replace("Z", "+00:00"))
            elif isinstance(close_time, int | float):
                close_dt = datetime.fromtimestamp(close_time, tz=UTC)
            else:
                close_dt = None
            if close_dt:
                days_to_exp = max(0, (close_dt - datetime.now(UTC)).total_seconds() / 86400)
        except (ValueError, TypeError, OSError):
            pass

    return {
        "captured_at": now,
        "source": "collector",
        "exchange": "kalshi",
        "ticker": market.get("ticker", ""),
        "event_ticker": market.get("event_ticker"),
        "series_ticker": market.get("series_ticker"),
        "title": market.get("title"),
        "category": market.get("category"),
        "status": market.get("status"),
        "yes_bid": yes_bid or None,
        "yes_ask": yes_ask or None,
        "no_bid": market.get("no_bid"),
        "no_ask": market.get("no_ask"),
        "last_price": market.get("last_price"),
        "volume": market.get("volume"),
        "volume_24h": market.get("volume_24h"),
        "open_interest": market.get("open_interest"),
        "spread_cents": spread,
        "mid_price_cents": mid,
        "implied_probability": implied_prob,
        "days_to_expiration": days_to_exp,
        "close_time": str(close_time) if close_time else None,
        "settlement_value": market.get("settlement_value"),
        "markets_in_event": None,  # filled later if from event
        "raw_json": json.dumps(market, default=str),
    }


def _collect_markets_by_status(
    client: KalshiAPIClient,
    db: AgentDatabase,
    status: str,
    label: str,
    max_total: int | None = None,
) -> int:
    """Generic market collection with pagination and batching."""
    now = _now_iso()
    cursor = None
    total = 0
    batch: list[dict[str, Any]] = []

    print(f"Collecting {label}...")
    while True:
        resp = client.search_markets(status=status, limit=200, cursor=cursor)
        markets = resp.get("markets", [])
        if not markets:
            break

        for m in markets:
            batch.append(_compute_derived(m, now))

        if len(batch) >= 500:
            total += db.insert_market_snapshots(batch)
            batch.clear()

        cursor = resp.get("cursor")
        if not cursor:
            break
        if max_total and total + len(batch) >= max_total:
            break

    if batch:
        total += db.insert_market_snapshots(batch)

    print(f"  → {total} {label}")
    return total


def collect_open_markets(client: KalshiAPIClient, db: AgentDatabase) -> int:
    """Collect all open markets via pagination."""
    return _collect_markets_by_status(client, db, "open", "open market snapshots")


def collect_settled_markets(client: KalshiAPIClient, db: AgentDatabase) -> int:
    """Collect recently settled markets for calibration data."""
    return _collect_markets_by_status(client, db, "settled", "settled market snapshots", 1000)


def collect_events(
    client: KalshiAPIClient,
    db: AgentDatabase,
) -> int:
    """Collect event structures with nested markets."""
    # Get events that have open markets by searching open markets and extracting
    # unique event tickers, then fetching each event
    print("Collecting events...")

    # First, get distinct event tickers from recent open market snapshots
    event_tickers = db.query(
        """SELECT DISTINCT event_ticker FROM market_snapshots
           WHERE event_ticker IS NOT NULL
           AND source = 'collector'
           ORDER BY captured_at DESC
           LIMIT 500"""
    )

    total = 0
    for row in event_tickers:
        et = row["event_ticker"]
        if not et:
            continue
        try:
            event = client.get_event(et)
            nested = event.get("markets", [])
            markets_summary = [
                {
                    "ticker": m.get("ticker"),
                    "title": m.get("title"),
                    "yes_bid": m.get("yes_bid"),
                    "yes_ask": m.get("yes_ask"),
                    "status": m.get("status"),
                }
                for m in nested
            ]
            db.upsert_event(
                event_ticker=et,
                series_ticker=event.get("series_ticker"),
                title=event.get("title"),
                category=event.get("category"),
                mutually_exclusive=event.get("mutually_exclusive"),
                markets_json=json.dumps(markets_summary, default=str),
            )
            total += 1
        except Exception as e:
            print(f"  Warning: failed to fetch event {et}: {e}")
            continue

    print(f"  → {total} events")
    return total


def _compute_derived_polymarket(market: dict[str, Any], now: str) -> dict[str, Any]:
    """Compute derived fields from Polymarket market data.

    Prices are stored as cents for consistency with Kalshi.
    """
    # Polymarket prices are USD decimals; convert to cents
    yes_price = market.get("yes_price") or market.get("lastTradePrice")

    yes_bid_cents = None
    yes_ask_cents = None
    mid_cents = None
    spread_cents = None
    implied_prob = None

    if yes_price is not None:
        mid_cents = int(float(yes_price) * 100)
        implied_prob = float(yes_price)

    best_bid = market.get("bestBid") or market.get("best_bid")
    best_ask = market.get("bestAsk") or market.get("best_ask")
    if best_bid is not None:
        yes_bid_cents = int(float(best_bid) * 100)
    if best_ask is not None:
        yes_ask_cents = int(float(best_ask) * 100)

    if yes_bid_cents is not None and yes_ask_cents is not None:
        spread_cents = yes_ask_cents - yes_bid_cents
        mid_cents = (yes_bid_cents + yes_ask_cents) // 2
        implied_prob = mid_cents / 100.0

    # Days to expiration
    days_to_exp = None
    close_time = market.get("endDate") or market.get("end_date")
    if close_time:
        try:
            if isinstance(close_time, str):
                close_dt = datetime.fromisoformat(close_time.replace("Z", "+00:00"))
            elif isinstance(close_time, int | float):
                close_dt = datetime.fromtimestamp(close_time, tz=UTC)
            else:
                close_dt = None
            if close_dt:
                days_to_exp = max(0, (close_dt - datetime.now(UTC)).total_seconds() / 86400)
        except (ValueError, TypeError, OSError):
            pass

    volume = market.get("volume") or market.get("volumeNum")
    slug = market.get("slug") or market.get("ticker_slug") or market.get("id", "")

    return {
        "captured_at": now,
        "source": "collector",
        "exchange": "polymarket",
        "ticker": slug,
        "event_ticker": market.get("eventSlug") or market.get("event_slug"),
        "series_ticker": None,
        "title": market.get("title") or market.get("question"),
        "category": market.get("category"),
        "status": "open" if market.get("active") else "closed",
        "yes_bid": yes_bid_cents,
        "yes_ask": yes_ask_cents,
        "no_bid": None,
        "no_ask": None,
        "last_price": mid_cents,
        "volume": int(volume) if volume else None,
        "volume_24h": None,
        "open_interest": market.get("openInterest") or market.get("open_interest"),
        "spread_cents": spread_cents,
        "mid_price_cents": mid_cents,
        "implied_probability": implied_prob,
        "days_to_expiration": days_to_exp,
        "close_time": str(close_time) if close_time else None,
        "settlement_value": None,
        "markets_in_event": None,
        "raw_json": json.dumps(market, default=str),
    }


def collect_polymarket_markets(
    client: PolymarketAPIClient,
    db: AgentDatabase,
) -> int:
    """Collect open markets from Polymarket US."""
    now = _now_iso()
    total = 0
    batch: list[dict[str, Any]] = []

    print("Collecting Polymarket markets...")
    offset = 0
    while True:
        resp = client.search_markets(status="open", limit=100, offset=offset)
        markets = resp if isinstance(resp, list) else resp.get("markets", resp.get("data", []))
        if not markets:
            break
        for m in markets:
            batch.append(_compute_derived_polymarket(m, now))
        if len(batch) >= 500:
            total += db.insert_market_snapshots(batch)
            batch.clear()
        offset += len(markets)

    if batch:
        total += db.insert_market_snapshots(batch)
    print(f"  → {total} Polymarket market snapshots")
    return total


def run_collector() -> None:
    """Main entry point for the collector."""
    _, trading_config = load_configs()

    limiter = RateLimiter(
        reads_per_sec=trading_config.rate_limit_reads_per_sec,
        writes_per_sec=trading_config.rate_limit_writes_per_sec,
    )
    client = KalshiAPIClient(trading_config, rate_limiter=limiter)
    db = AgentDatabase(trading_config.db_path)

    start = time.time()
    print(f"Data collector starting ({trading_config.kalshi_env})")
    print(f"DB: {trading_config.db_path}")

    try:
        open_count = collect_open_markets(client, db)
        settled_count = collect_settled_markets(client, db)
        event_count = collect_events(client, db)

        pm_count = 0
        if trading_config.polymarket_enabled and trading_config.polymarket_key_id:
            pm_client = PolymarketAPIClient(trading_config, rate_limiter=limiter)
            pm_count = collect_polymarket_markets(pm_client, db)

        elapsed = time.time() - start
        print(f"\nCollection complete in {elapsed:.1f}s")
        print(f"  Open: {open_count} | Settled: {settled_count} | Events: {event_count}")
        print(f"  Polymarket: {pm_count}")
    except KeyboardInterrupt:
        print("\nInterrupted.")
    finally:
        db.close()


if __name__ == "__main__":
    run_collector()
