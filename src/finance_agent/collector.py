"""Data collector -- snapshots market data to DuckDB.

Standalone script, no LLM. Run via `make collect` or `python -m finance_agent.collector`.

Events-first architecture: Kalshi organises around Events, each containing one or
more Markets.  We fetch events with nested markets in a single paginated pass,
storing both event structure and market snapshots.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from datetime import UTC, datetime
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


# ── Entry point ──────────────────────────────────────────────────


async def resolve_settlements(kalshi: KalshiAPIClient, db: AgentDatabase) -> int:
    """Check unresolved recommendation legs for market settlement.

    Batches API calls by unique ticker (not N calls for N legs).
    Returns count of legs settled.
    """
    tickers = db.get_unresolved_leg_tickers()
    if not tickers:
        logger.info("Settlement check: no unresolved tickers")
        return 0

    logger.info("Settlement check: %d unique tickers to check", len(tickers))

    settled_count = 0
    for ticker in tickers:
        try:
            market_data = await kalshi.get_market(ticker)
            inner = market_data.get("market", market_data) if isinstance(market_data, dict) else {}
            settlement_value = inner.get("settlement_value")
            if settlement_value is not None:
                count = db.settle_legs(ticker, int(settlement_value))
                if count > 0:
                    logger.info(
                        "  Settled %s -> %dc (%d legs updated)", ticker, settlement_value, count
                    )
                    settled_count += count
        except Exception as e:
            logger.debug("  Could not check %s: %s", ticker, e)

    # Compute P&L for groups that became fully settled
    from .fees import compute_hypothetical_pnl

    groups = db.get_groups_pending_pnl()
    for group in groups:
        pnl = compute_hypothetical_pnl(group)
        db.update_group_pnl(group["id"], pnl)
        logger.info(
            "  Group %d P&L: $%.4f (%s, %d legs)",
            group["id"],
            pnl,
            group.get("strategy", "?"),
            len(group.get("legs", [])),
        )

    logger.info("Settlement check complete: %d legs settled", settled_count)
    return settled_count


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

        # Backfill metadata for historical tickers missing titles/categories
        from .backfill import backfill_missing_meta

        await backfill_missing_meta(kalshi, db)

        # Resolve settlements for recommendation legs
        await resolve_settlements(kalshi, db)

        # Purge old snapshots and stale daily data
        db.purge_old_snapshots(trading_config.snapshot_retention_days)
        db.purge_old_daily(
            trading_config.daily_retention_days,
            trading_config.daily_min_ticker_days,
        )

        # Checkpoint and update statistics
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
