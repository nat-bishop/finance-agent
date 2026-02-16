"""Data collector -- snapshots market data to SQLite.

Standalone script, no LLM. Run via `make collect` or `python -m finance_agent.collector`.

Events-first architecture: both Kalshi and Polymarket organise around Events,
each containing one or more Markets.  We fetch events with nested markets in a
single paginated pass, storing both event structure and market snapshots.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .config import load_configs
from .database import AgentDatabase
from .kalshi_client import KalshiAPIClient
from .polymarket_client import PolymarketAPIClient

logger = logging.getLogger(__name__)


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


def _parse_days_to_expiry(close_time: Any) -> float | None:
    """Parse a close/expiration time into days remaining. Returns None on failure."""
    if not close_time:
        return None
    try:
        if isinstance(close_time, datetime):
            close_dt = close_time
        elif isinstance(close_time, str):
            close_dt = datetime.fromisoformat(close_time)
        elif isinstance(close_time, int | float):
            close_dt = datetime.fromtimestamp(close_time, tz=UTC)
        else:
            return None
        if close_dt.tzinfo is None:
            close_dt = close_dt.replace(tzinfo=UTC)
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
        "status": "open" if market.get("status") == "active" else market.get("status"),
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


# ── Kalshi: events-first collection ─────────────────────────────


def _upsert_kalshi_event(db: AgentDatabase, event: dict[str, Any]) -> str | None:
    """Store a Kalshi event row. Returns event_ticker, or None to skip."""
    et = event.get("event_ticker")
    if not et:
        return None
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
    return et


async def collect_kalshi(
    client: KalshiAPIClient,
    db: AgentDatabase,
    *,
    status: str = "open",
    max_pages: int | None = None,
) -> tuple[int, int]:
    """Collect Kalshi events with nested markets in a single pass.

    Returns (event_count, market_count).
    """
    label = f"Kalshi {status} events"
    logger.info("Collecting %s...", label)

    now = _now_iso()
    event_count = 0
    market_count = 0
    market_batch: list[dict[str, Any]] = []
    meta_batch: list[dict[str, Any]] = []
    cursor: str | None = None
    pages = 0

    while True:
        try:
            resp = await client.get_events(status=status, with_nested_markets=True, cursor=cursor)
        except Exception as e:
            logger.warning("Error during %s collection: %s", label, e)
            break

        events = resp.get("events", [])
        if not events:
            break

        page_markets = 0
        for event in events:
            if not _upsert_kalshi_event(db, event):
                continue
            event_count += 1
            nested = event.get("markets", [])
            for m in nested:
                market_batch.append(_compute_derived(m, now))
                meta_batch.append(
                    {
                        "ticker": m.get("ticker"),
                        "event_ticker": event.get("event_ticker"),
                        "series_ticker": event.get("series_ticker"),
                        "title": m.get("title"),
                        "category": event.get("category"),
                    }
                )
            page_markets += len(nested)

        if len(market_batch) >= 500:
            market_count += db.insert_market_snapshots(market_batch)
            market_batch.clear()
        if len(meta_batch) >= 500:
            db.upsert_market_meta(meta_batch)
            meta_batch.clear()

        pages += 1
        logger.info(
            "  page %d: %d events, %d markets (total: %d events, %d markets)",
            pages,
            len(events),
            page_markets,
            event_count,
            market_count + len(market_batch),
        )
        cursor = resp.get("cursor")
        if not cursor or (max_pages and pages >= max_pages):
            break

    if market_batch:
        market_count += db.insert_market_snapshots(market_batch)
    if meta_batch:
        db.upsert_market_meta(meta_batch)

    logger.info("  -> %d events, %d market snapshots", event_count, market_count)
    return event_count, market_count


# ── Polymarket: events-first collection ──────────────────────────


async def collect_polymarket(
    client: PolymarketAPIClient,
    db: AgentDatabase,
) -> tuple[int, int]:
    """Collect Polymarket events with nested markets in a single pass.

    Returns (event_count, market_count).
    """
    logger.info("Collecting Polymarket events...")

    now = _now_iso()
    event_count = 0
    market_count = 0
    market_batch: list[dict[str, Any]] = []
    offset = 0

    while True:
        try:
            resp = await client.list_events(active=True, limit=100, offset=offset)
        except Exception as e:
            logger.warning("Error during Polymarket event collection: %s", e)
            break

        events = _as_list(resp, "events", "data")
        if not events:
            break

        for event in events:
            slug = event.get("slug") or event.get("id", "")
            if not slug:
                continue

            nested = event.get("markets", [])

            # Store event structure
            markets_summary = [
                {
                    "slug": m.get("slug"),
                    "title": m.get("title") or m.get("question"),
                    "yes_price": m.get("yes_price") or m.get("lastTradePrice"),
                    "active": m.get("active"),
                }
                for m in nested
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
            event_count += 1

            # Extract market snapshots — inject parent event slug as fallback
            for m in nested:
                if not m.get("eventSlug") and not m.get("event_slug"):
                    m["eventSlug"] = slug
                market_batch.append(_compute_derived_polymarket(m, now))

        if len(market_batch) >= 500:
            market_count += db.insert_market_snapshots(market_batch)
            market_batch.clear()

        offset += len(events)
        logger.info(
            "  page %d: %d events (total: %d events, %d markets)",
            offset // 100,
            len(events),
            event_count,
            market_count + len(market_batch),
        )

    if market_batch:
        market_count += db.insert_market_snapshots(market_batch)

    logger.info("  -> %d events, %d market snapshots", event_count, market_count)
    return event_count, market_count


# ── Market data export (for agent discovery) ─────────────────────


def _generate_markets_jsonl(db: AgentDatabase, output_path: str) -> None:
    """Write one JSON object per line for agent programmatic discovery."""
    markets = db.get_latest_snapshots(status="open", require_mid_price=False)

    event_rows = db.get_all_events()
    event_map: dict[tuple[str, str], dict[str, Any]] = {
        (e["event_ticker"], e["exchange"]): e for e in event_rows
    }

    out = Path(output_path)
    out.parent.mkdir(parents=True, exist_ok=True)

    count = 0
    with out.open("w", encoding="utf-8") as f:
        for m in markets:
            evt_ticker = m.get("event_ticker") or ""
            evt_meta = event_map.get((evt_ticker, m["exchange"]), {})

            # Parse raw_json for description
            raw: dict[str, Any] = {}
            if m.get("raw_json"):
                with contextlib.suppress(json.JSONDecodeError, TypeError):
                    raw = json.loads(m["raw_json"])

            record = {
                "exchange": m["exchange"],
                "ticker": m["ticker"],
                "event_ticker": m.get("event_ticker"),
                "event_title": evt_meta.get("title"),
                "mutually_exclusive": bool(evt_meta.get("mutually_exclusive", False)),
                "title": m["title"],
                "description": raw.get("description") or raw.get("rules_primary"),
                "category": evt_meta.get("category") or m.get("category"),
                "mid_price_cents": m.get("mid_price_cents"),
                "spread_cents": m.get("spread_cents"),
                "yes_bid": m.get("yes_bid"),
                "yes_ask": m.get("yes_ask"),
                "volume_24h": m.get("volume_24h"),
                "open_interest": m.get("open_interest"),
                "days_to_expiration": m.get("days_to_expiration"),
            }
            f.write(json.dumps(record, default=str) + "\n")
            count += 1

    logger.info("  -> %d markets written to %s", count, output_path)


# ── Entry point ──────────────────────────────────────────────────


async def _run_collector_async() -> None:
    """Async collector implementation — runs both platforms concurrently."""
    from .logging_config import setup_logging

    setup_logging()

    _, credentials, trading_config = load_configs()

    kalshi = KalshiAPIClient(credentials, trading_config)
    db = AgentDatabase(trading_config.db_path)

    start = time.time()
    logger.info("Data collector starting")
    logger.info("DB: %s", trading_config.db_path)

    pm_client = None
    try:
        # Build tasks
        coros = [collect_kalshi(kalshi, db, status="open")]

        if trading_config.polymarket_enabled and credentials.polymarket_key_id:
            pm_client = PolymarketAPIClient(credentials, trading_config)
            coros.append(collect_polymarket(pm_client, db))

        # Run concurrently, pad with (0,0) so unpacking always works
        results = [*await asyncio.gather(*coros), (0, 0)]
        (k_events, k_markets), (pm_events, pm_markets) = results[0], results[1]

        # Generate JSONL market data for agent programmatic discovery
        jsonl_path = str(Path(trading_config.db_path).parent / "markets.jsonl")
        _generate_markets_jsonl(db, jsonl_path)

        # Sync Kalshi daily historical data (incremental)
        from .backfill import sync_daily

        sync_daily(db)

        # Purge old snapshots
        db.purge_old_snapshots(trading_config.snapshot_retention_days)

        elapsed = time.time() - start
        logger.info("Collection complete in %.1fs", elapsed)
        logger.info("  Kalshi: %d events (%d markets)", k_events, k_markets)
        logger.info("  Polymarket: %d events (%d markets)", pm_events, pm_markets)
    except KeyboardInterrupt:
        logger.warning("Interrupted")
    finally:
        if pm_client:
            await pm_client.close()
        db.close()


def run_collector() -> None:
    """Main entry point for the collector."""
    asyncio.run(_run_collector_async())


if __name__ == "__main__":
    run_collector()
