"""Bulk-backfill kalshi_market_meta from Kalshi API for historical tickers.

Two-phase strategy:
  Phase 1 (historical): Paginate GET /historical/markets (1000/page, ~190 calls)
    for all markets settled before the historical cutoff. Bulk and fast.
  Phase 2 (live): Call GET /markets/{ticker} individually for post-cutoff tickers
    in kalshi_daily that still lack metadata. Filtered by --min-days.

Usage:
    make backfill-meta                              # both phases, default settings
    make backfill-meta ARGS="--phase historical"    # only historical bulk fetch
    make backfill-meta ARGS="--phase live"          # only live per-market fetch
    make backfill-meta ARGS="--prefix KXRT%"        # only tickers matching pattern
    make backfill-meta ARGS="--min-days 5"          # only tickers with ≥5 days history
    make backfill-meta ARGS="--dry-run"             # preview without API calls
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import time
from typing import Any

from .config import load_configs
from .database import AgentDatabase
from .kalshi_client import KalshiAPIClient
from .logging_config import setup_logging

logger = logging.getLogger(__name__)


# ── Helpers ──────────────────────────────────────────────────


def _extract_meta(market: dict[str, Any]) -> dict[str, Any]:
    """Extract metadata fields from a market dict (works for both live and historical)."""
    return {
        "ticker": market.get("ticker"),
        "event_ticker": market.get("event_ticker"),
        "series_ticker": market.get("series_ticker"),
        "title": market.get("title"),
        "category": market.get("category"),
    }


def _get_missing_tickers(
    db: AgentDatabase,
    *,
    prefix: str | None = None,
    min_days: int = 0,
) -> list[str]:
    """Return ticker_names from kalshi_daily that have no kalshi_market_meta entry."""
    from sqlalchemy import text

    conditions = ["m.ticker IS NULL"]
    params: dict[str, Any] = {}

    if prefix:
        conditions.append("d.ticker_name LIKE :prefix")
        params["prefix"] = prefix

    having = ""
    if min_days > 0:
        having = "HAVING COUNT(*) >= :min_days"
        params["min_days"] = min_days

    where_sql = " AND ".join(conditions)
    sql = text(
        "SELECT d.ticker_name"  # noqa: S608
        " FROM kalshi_daily d"
        " LEFT JOIN kalshi_market_meta m ON d.ticker_name = m.ticker"
        f" WHERE {where_sql}"
        f" GROUP BY d.ticker_name {having}"
        " ORDER BY COUNT(*) DESC"
    )

    with db._session_factory() as session:
        rows = session.execute(sql, params).fetchall()
        return [r[0] for r in rows]


# ── Phase 1: Historical API bulk pagination ──────────────────


async def _phase_historical(
    kalshi: KalshiAPIClient,
    db: AgentDatabase,
    *,
    dry_run: bool = False,
) -> tuple[int, int]:
    """Paginate GET /historical/markets and upsert all metadata.

    Returns (markets_fetched, markets_upserted).
    """
    cutoff = await kalshi.get_historical_cutoff()
    cutoff_ts = cutoff.get("market_settled_ts", "unknown")
    logger.info("Historical cutoff: %s", cutoff_ts)

    if dry_run:
        # Quick count: fetch one page to see if there's data
        resp = await kalshi.get_historical_markets(limit=1)
        has_data = bool(resp.get("markets"))
        logger.info("Historical phase: dry-run (has data: %s, cutoff: %s)", has_data, cutoff_ts)
        return 0, 0

    total_fetched = 0
    total_upserted = 0
    cursor: str | None = None
    pages = 0
    meta_batch: list[dict[str, Any]] = []
    start = time.time()

    while True:
        resp = await kalshi.get_historical_markets(limit=1000, cursor=cursor)
        markets = resp.get("markets", [])
        if not markets:
            break

        meta_batch.extend(_extract_meta(m) for m in markets)
        total_fetched += len(markets)
        pages += 1

        # Flush every 5000 markets
        if len(meta_batch) >= 5000:
            total_upserted += db.upsert_market_meta(meta_batch)
            meta_batch.clear()

        if pages % 20 == 0:
            elapsed = time.time() - start
            logger.info(
                "  Historical: page %d, %d markets fetched (%.0fs)",
                pages,
                total_fetched,
                elapsed,
            )

        cursor = resp.get("cursor")
        if not cursor:
            break

    # Final flush
    if meta_batch:
        total_upserted += db.upsert_market_meta(meta_batch)

    elapsed = time.time() - start
    logger.info(
        "Historical phase complete in %.1fs: %d fetched, %d upserted, %d pages",
        elapsed,
        total_fetched,
        total_upserted,
        pages,
    )
    return total_fetched, total_upserted


# ── Phase 2: Live API batched ────────────────────────────────

_BATCH_SIZE = 200  # Tickers per GET /markets call (URL length safe)


async def _phase_live(
    kalshi: KalshiAPIClient,
    db: AgentDatabase,
    *,
    prefix: str | None = None,
    min_days: int = 5,
    dry_run: bool = False,
) -> tuple[int, int, int]:
    """Fetch metadata for post-cutoff tickers via batched GET /markets.

    Sends up to 200 tickers per API call using the ``tickers`` parameter.
    Returns (tickers_requested, markets_upserted, errors).
    """
    missing = _get_missing_tickers(db, prefix=prefix, min_days=min_days)
    total = len(missing)
    n_batches = (total + _BATCH_SIZE - 1) // _BATCH_SIZE

    logger.info(
        "Live phase: %d tickers missing metadata (%d batches, prefix=%s, min_days=%d)",
        total,
        n_batches,
        prefix or "all",
        min_days,
    )

    if dry_run:
        for ticker in missing[:30]:
            logger.info("  %s", ticker)
        if total > 30:
            logger.info("  ... and %d more", total - 30)
        return 0, 0, 0

    upserted = 0
    errors = 0
    fetched = 0
    meta_batch: list[dict[str, Any]] = []
    start = time.time()

    for batch_idx in range(n_batches):
        batch_start = batch_idx * _BATCH_SIZE
        batch_tickers = missing[batch_start : batch_start + _BATCH_SIZE]

        try:
            resp = await kalshi.search_markets(tickers=",".join(batch_tickers), limit=1000)
            markets = resp.get("markets", [])
            meta_batch.extend(_extract_meta(m) for m in markets)
            fetched += len(markets)

            # Flush every 5000 markets
            if len(meta_batch) >= 5000:
                upserted += db.upsert_market_meta(meta_batch)
                meta_batch.clear()

        except Exception as exc:
            errors += 1
            if errors <= 10:
                logger.warning("Batch %d failed: %s", batch_idx, exc)
            elif errors == 11:
                logger.warning("Suppressing further error details...")
            logger.debug("Batch %d traceback", batch_idx, exc_info=True)

        # Progress logging
        if (batch_idx + 1) % 50 == 0 or batch_idx == n_batches - 1:
            elapsed = time.time() - start
            tickers_done = min((batch_idx + 1) * _BATCH_SIZE, total)
            rate = tickers_done / elapsed if elapsed > 0 else 0
            remaining = (total - tickers_done) / rate if rate > 0 else 0
            logger.info(
                "  Live: %d/%d tickers, %d fetched (%d batches, %.0fs, ~%.0fs remaining)",
                tickers_done,
                total,
                fetched,
                batch_idx + 1,
                elapsed,
                remaining,
            )

    # Final flush
    if meta_batch:
        upserted += db.upsert_market_meta(meta_batch)

    elapsed = time.time() - start
    logger.info(
        "Live phase complete in %.1fs: %d requested, %d fetched, %d upserted, %d batch errors",
        elapsed,
        total,
        fetched,
        upserted,
        errors,
    )
    return total, upserted, errors


# ── CLI entry point ──────────────────────────────────────────


async def run_backfill(
    kalshi: KalshiAPIClient,
    db: AgentDatabase,
    *,
    phase: str = "all",
    prefix: str | None = None,
    min_days: int = 5,
    dry_run: bool = False,
) -> None:
    """Run the metadata backfill."""
    if phase in ("all", "historical"):
        await _phase_historical(kalshi, db, dry_run=dry_run)

    if phase in ("all", "live"):
        await _phase_live(kalshi, db, prefix=prefix, min_days=min_days, dry_run=dry_run)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Backfill kalshi_market_meta from Kalshi API for historical tickers."
    )
    parser.add_argument(
        "--phase",
        choices=["all", "historical", "live"],
        default="all",
        help="Which phase to run (default: all)",
    )
    parser.add_argument(
        "--prefix",
        help="SQL LIKE pattern to filter tickers (e.g., KXRT%%). Applies to live phase.",
    )
    parser.add_argument(
        "--min-days",
        type=int,
        default=5,
        help="Only backfill tickers with >= N days of daily history (default: 5)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Preview what would be fetched without making API calls",
    )
    args = parser.parse_args()

    setup_logging()

    _, creds, trading_config = load_configs()
    db = AgentDatabase(trading_config.db_path)
    kalshi = KalshiAPIClient(creds, trading_config)

    async def _run() -> None:
        try:
            await run_backfill(
                kalshi,
                db,
                phase=args.phase,
                prefix=args.prefix,
                min_days=args.min_days,
                dry_run=args.dry_run,
            )
        finally:
            await kalshi._client.close()
            db.close()

    asyncio.run(_run())


if __name__ == "__main__":
    main()
