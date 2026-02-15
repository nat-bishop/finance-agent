"""Data collector -- snapshots market data to SQLite.

Standalone script, no LLM. Run via `make collect` or `python -m finance_agent.collector`.

Collection schedule (all in one run):
- All open markets (paginated) -> market_snapshots
- Event structure (paginated) -> events
- Recently settled markets -> market_snapshots (for calibration)
"""

from __future__ import annotations

import json
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .config import load_configs
from .database import AgentDatabase
from .kalshi_client import KalshiAPIClient
from .polymarket_client import PolymarketAPIClient


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


def _parse_days_to_expiry(close_time: Any) -> float | None:
    """Parse a close/expiration time into days remaining. Returns None on failure."""
    if not close_time:
        return None
    try:
        if isinstance(close_time, str):
            close_dt = datetime.fromisoformat(close_time.replace("Z", "+00:00"))
        elif isinstance(close_time, int | float):
            close_dt = datetime.fromtimestamp(close_time, tz=UTC)
        else:
            return None
        return max(0.0, (close_dt - datetime.now(UTC)).total_seconds() / 86400)
    except (ValueError, TypeError, OSError):
        return None


def _base_snapshot(now: str, exchange: str, market: dict[str, Any]) -> dict[str, Any]:
    return {
        "captured_at": now,
        "source": "collector",
        "exchange": exchange,
        "raw_json": json.dumps(market, default=str),
    }


def _as_list(resp: Any, *keys: str) -> list:
    if isinstance(resp, list):
        return resp
    for k in keys:
        if k in resp:
            return resp[k]
    return []


def _compute_derived(market: dict[str, Any], now: str) -> dict[str, Any]:
    """Compute derived fields from raw Kalshi market data."""
    yes_bid = market.get("yes_bid") or 0
    yes_ask = market.get("yes_ask") or 0

    spread = yes_ask - yes_bid if yes_ask and yes_bid else None
    mid = (yes_bid + yes_ask) // 2 if yes_ask and yes_bid else None
    implied_prob = mid / 100.0 if mid else None

    close_time = market.get("close_time") or market.get("expected_expiration_time")

    return {
        **_base_snapshot(now, "kalshi", market),
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
        "days_to_expiration": _parse_days_to_expiry(close_time),
        "close_time": str(close_time) if close_time else None,
        "settlement_value": market.get("settlement_value"),
        "markets_in_event": None,
    }


def _compute_derived_polymarket(market: dict[str, Any], now: str) -> dict[str, Any]:
    yes_price = market.get("yes_price") or market.get("lastTradePrice")
    mid_cents = int(float(yes_price) * 100) if yes_price is not None else None
    implied_prob = float(yes_price) if yes_price is not None else None

    def _to_cents(key1: str, key2: str) -> int | None:
        v = market.get(key1) or market.get(key2)
        return int(float(v) * 100) if v is not None else None

    yes_bid_cents = _to_cents("bestBid", "best_bid")
    yes_ask_cents = _to_cents("bestAsk", "best_ask")
    spread_cents = None

    if yes_bid_cents is not None and yes_ask_cents is not None:
        spread_cents = yes_ask_cents - yes_bid_cents
        mid_cents = (yes_bid_cents + yes_ask_cents) // 2
        implied_prob = mid_cents / 100.0

    close_time = market.get("endDate") or market.get("end_date")
    volume = market.get("volume") or market.get("volumeNum")
    slug = market.get("slug") or market.get("ticker_slug") or market.get("id", "")

    return {
        **_base_snapshot(now, "polymarket", market),
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
        "days_to_expiration": _parse_days_to_expiry(close_time),
        "close_time": str(close_time) if close_time else None,
        "settlement_value": None,
        "markets_in_event": None,
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

        batch.extend(_compute_derived(m, now) for m in markets)

        if len(batch) >= 500:
            total += db.insert_market_snapshots(batch)
            batch.clear()

        cursor = resp.get("cursor")
        if not cursor or (max_total and total + len(batch) >= max_total):
            break

    if batch:
        total += db.insert_market_snapshots(batch)

    print(f"  -> {total} {label}")
    return total


def collect_open_markets(client: KalshiAPIClient, db: AgentDatabase) -> int:
    return _collect_markets_by_status(client, db, "open", "open market snapshots")


def collect_settled_markets(client: KalshiAPIClient, db: AgentDatabase) -> int:
    return _collect_markets_by_status(client, db, "settled", "settled market snapshots", 1000)


def collect_events(client: KalshiAPIClient, db: AgentDatabase) -> int:
    """Collect event structures with nested markets via paginated GET /events."""
    print("Collecting events...")

    cursor = None
    total = 0

    while True:
        resp = client.get_events(status="open", with_nested_markets=True, limit=200, cursor=cursor)
        events = resp.get("events", [])
        if not events:
            break

        for event in events:
            et = event.get("event_ticker")
            if not et:
                continue
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
                exchange="kalshi",
                series_ticker=event.get("series_ticker"),
                title=event.get("title"),
                category=event.get("category"),
                mutually_exclusive=event.get("mutually_exclusive"),
                markets_json=json.dumps(markets_summary, default=str),
            )
            total += 1

        cursor = resp.get("cursor")
        if not cursor:
            break

    print(f"  -> {total} events")
    return total


def collect_polymarket_markets(client: PolymarketAPIClient, db: AgentDatabase) -> int:
    """Collect open markets from Polymarket US."""
    now = _now_iso()
    total = 0
    batch: list[dict[str, Any]] = []

    print("Collecting Polymarket markets...")
    offset = 0
    while True:
        resp = client.search_markets(status="open", limit=100, offset=offset)
        markets = _as_list(resp, "markets", "data")
        if not markets:
            break
        batch.extend(_compute_derived_polymarket(m, now) for m in markets)
        if len(batch) >= 500:
            total += db.insert_market_snapshots(batch)
            batch.clear()
        offset += len(markets)

    if batch:
        total += db.insert_market_snapshots(batch)
    print(f"  -> {total} Polymarket market snapshots")
    return total


def collect_polymarket_events(client: PolymarketAPIClient, db: AgentDatabase) -> int:
    """Collect event structures from Polymarket US."""
    print("Collecting Polymarket events...")
    total = 0
    offset = 0

    while True:
        resp = client.list_events(active=True, limit=100, offset=offset)
        events = _as_list(resp, "events", "data")
        if not events:
            break

        for event in events:
            slug = event.get("slug") or event.get("id", "")
            if not slug:
                continue
            markets = event.get("markets", [])
            markets_summary = [
                {
                    "slug": m.get("slug"),
                    "title": m.get("title") or m.get("question"),
                    "yes_price": m.get("yes_price") or m.get("lastTradePrice"),
                    "active": m.get("active"),
                }
                for m in markets
            ]
            db.upsert_event(
                event_ticker=slug,
                exchange="polymarket",
                title=event.get("title"),
                category=event.get("category"),
                mutually_exclusive=event.get("mutuallyExclusive")
                or event.get("mutually_exclusive"),
                markets_json=json.dumps(markets_summary, default=str),
            )
            total += 1

        offset += len(events)

    print(f"  -> {total} Polymarket events")
    return total


def _generate_market_listings(db: AgentDatabase, output_path: str) -> None:
    """Write category-grouped market summary for agent semantic discovery."""
    markets = db.query("""
        SELECT exchange, ticker, title, mid_price_cents, category, days_to_expiration
        FROM market_snapshots
        WHERE status = 'open' AND mid_price_cents IS NOT NULL
        GROUP BY exchange, ticker
        HAVING captured_at = MAX(captured_at)
        ORDER BY category, exchange, title
    """)

    # Group by category → exchange
    by_cat: dict[str, dict[str, list]] = {}
    for m in markets:
        cat = m["category"] or "Other"
        exch = m["exchange"]
        by_cat.setdefault(cat, {}).setdefault(exch, []).append(m)

    now = _now_iso()
    total_k = sum(len(v.get("kalshi", [])) for v in by_cat.values())
    total_p = sum(len(v.get("polymarket", [])) for v in by_cat.values())

    lines = [
        f"# Active Markets — {now}\n",
        f"\n{total_k} Kalshi markets, {total_p} Polymarket markets. All prices in cents.\n",
    ]

    for cat in sorted(by_cat):
        lines.append(f"\n## {cat}\n")
        for exch in ["kalshi", "polymarket"]:
            ms = by_cat[cat].get(exch, [])
            if not ms:
                continue
            lines.append(f"\n### {exch.title()} ({len(ms)} markets)")
            for m in ms:
                price = m["mid_price_cents"]
                lines.append(f"- {m['title']} — {price}c [{m['ticker']}]")
        lines.append("")

    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    Path(output_path).write_text("\n".join(lines), encoding="utf-8")
    print(f"  -> Market listings written to {output_path}")


def run_collector() -> None:
    """Main entry point for the collector."""
    _, trading_config = load_configs()

    client = KalshiAPIClient(trading_config)
    db = AgentDatabase(trading_config.db_path)

    start = time.time()
    print(f"Data collector starting ({trading_config.kalshi_env})")
    print(f"DB: {trading_config.db_path}")

    try:
        open_count = collect_open_markets(client, db)
        settled_count = collect_settled_markets(client, db)
        event_count = collect_events(client, db)

        pm_count = 0
        pm_event_count = 0
        if trading_config.polymarket_enabled and trading_config.polymarket_key_id:
            pm_client = PolymarketAPIClient(trading_config)
            pm_count = collect_polymarket_markets(pm_client, db)
            pm_event_count = collect_polymarket_events(pm_client, db)

        # Generate market listings for agent semantic discovery
        listings_path = str(Path(trading_config.db_path).parent / "active_markets.md")
        _generate_market_listings(db, listings_path)

        elapsed = time.time() - start
        print(f"\nCollection complete in {elapsed:.1f}s")
        print(f"  Open: {open_count} | Settled: {settled_count} | Events: {event_count}")
        print(f"  Polymarket: {pm_count} markets, {pm_event_count} events")
    except KeyboardInterrupt:
        print("\nInterrupted.")
    finally:
        db.close()


if __name__ == "__main__":
    run_collector()
