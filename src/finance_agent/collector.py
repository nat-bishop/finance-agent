"""Data collector -- snapshots market data to SQLite.

Standalone script, no LLM. Run via `make collect` or `python -m finance_agent.collector`.

Events-first architecture: Kalshi organises around Events, each containing one or
more Markets.  We fetch events with nested markets in a single paginated pass,
storing both event structure and market snapshots.
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
from .constants import EXCHANGE_KALSHI, STATUS_OPEN
from .database import AgentDatabase
from .kalshi_client import KalshiAPIClient

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
        **_base_snapshot(now, EXCHANGE_KALSHI, market),
        "ticker": market.get("ticker", ""),
        "event_ticker": market.get("event_ticker"),
        "series_ticker": market.get("series_ticker"),
        "title": market.get("title"),
        "category": market.get("category"),
        "status": STATUS_OPEN if market.get("status") == "active" else market.get("status"),
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
        exchange=EXCHANGE_KALSHI,
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
    status: str = STATUS_OPEN,
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


# ── Market data export (for agent discovery) ─────────────────────


def _generate_markets_jsonl(db: AgentDatabase, output_path: str) -> None:
    """Write one JSON object per line for agent programmatic discovery."""
    markets = db.get_latest_snapshots(status=STATUS_OPEN, require_mid_price=False)

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
    """Async collector implementation — Kalshi only."""
    from .logging_config import setup_logging

    setup_logging()

    _, credentials, trading_config = load_configs()

    kalshi = KalshiAPIClient(credentials, trading_config)
    db = AgentDatabase(trading_config.db_path)

    start = time.time()
    logger.info("Data collector starting")
    logger.info("DB: %s", trading_config.db_path)

    try:
        k_events, k_markets = await collect_kalshi(kalshi, db, status=STATUS_OPEN)

        # Generate JSONL market data for agent programmatic discovery
        jsonl_path = str(Path(trading_config.db_path).parent / "markets.jsonl")
        _generate_markets_jsonl(db, jsonl_path)

        # Backfill metadata for historical tickers missing titles/categories
        from .backfill import backfill_missing_meta

        await backfill_missing_meta(kalshi, db)

        # Purge old snapshots and stale daily data
        db.purge_old_snapshots(trading_config.snapshot_retention_days)
        db.purge_old_daily(
            trading_config.daily_retention_days,
            trading_config.daily_min_ticker_days,
        )

        # Checkpoint WAL and update query planner statistics
        db.maintenance()

        elapsed = time.time() - start
        logger.info("Collection complete in %.1fs", elapsed)
        logger.info("  Kalshi: %d events (%d markets)", k_events, k_markets)
    except KeyboardInterrupt:
        logger.warning("Interrupted")
    finally:
        await kalshi._client.close()
        db.close()


def run_collector() -> None:
    """Main entry point for the collector."""
    asyncio.run(_run_collector_async())


if __name__ == "__main__":
    run_collector()
