"""Kalshi historical daily data backfill.

Fetches EOD market data from Kalshi's public S3 reporting bucket and stores
it in DuckDB.  Standalone long-running command via ``make backfill`` or
``python -m finance_agent.backfill``.
"""

from __future__ import annotations

import http.client
import json
import logging
import ssl
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, date, datetime, timedelta
from typing import Any

from .database import AgentDatabase

logger = logging.getLogger(__name__)

_S3_HOST = "kalshi-public-docs.s3.amazonaws.com"
_S3_PATH_TEMPLATE = "/reporting/market_data_{date}.json"
FIRST_AVAILABLE_DATE = date(2021, 6, 30)
_SSL_CTX = ssl.create_default_context()

_DEFAULT_MAX_WORKERS = 8

# Set by sync_daily on KeyboardInterrupt; checked by worker threads.
_shutdown_event = threading.Event()


_READ_CHUNK = 4 * 1024 * 1024  # 4 MB per read; check shutdown between chunks


def _fetch_daily(d: date) -> list[dict[str, Any]] | None:
    """Fetch a single day's JSON from S3. Returns None on 404/error/shutdown."""
    if _shutdown_event.is_set():
        return None
    path = _S3_PATH_TEMPLATE.format(date=d.isoformat())
    conn = http.client.HTTPSConnection(_S3_HOST, timeout=120, context=_SSL_CTX)
    try:
        conn.request("GET", path)
        resp = conn.getresponse()
        if resp.status == 404:
            logger.debug("No data for %s (404)", d)
            return None
        if resp.status != 200:
            logger.warning("HTTP %d fetching %s%s", resp.status, _S3_HOST, path)
            return None
        # Read in chunks so we can bail on shutdown
        chunks: list[bytes] = []
        while True:
            if _shutdown_event.is_set():
                return None
            chunk = resp.read(_READ_CHUNK)
            if not chunk:
                break
            chunks.append(chunk)
        return json.loads(b"".join(chunks))
    except Exception:
        if _shutdown_event.is_set():
            return None
        logger.exception("Error fetching %s%s", _S3_HOST, path)
        return None
    finally:
        conn.close()


def _fetch_and_normalise(d: date) -> tuple[date, list[dict[str, Any]], float]:
    """Fetch a day from S3 and normalise rows. Thread-safe.

    Returns (date, normalised_rows, fetch_seconds).
    """
    if _shutdown_event.is_set():
        return d, [], 0.0
    logger.info("  Fetching %s ...", d)
    t0 = time.time()
    records = _fetch_daily(d)
    fetch_elapsed = time.time() - t0
    if not records:
        return d, [], fetch_elapsed
    rows = [_normalise_row(r) for r in records if _has_activity(r)]
    return d, rows, fetch_elapsed


def _has_activity(row: dict[str, Any]) -> bool:
    """Return True if the record has any trading activity (volume or open interest)."""
    vol = row.get("daily_volume") or 0
    oi = row.get("open_interest") or 0
    return vol > 0 or oi > 0


def _coerce_int(val: Any) -> int | None:
    """Coerce a numeric value to int, handling floats like 5058.0."""
    if val is None:
        return None
    try:
        return int(val)
    except (ValueError, TypeError):
        return None


def _normalise_row(row: dict[str, Any]) -> dict[str, Any]:
    """Normalise a single S3 record for DB insertion."""
    return {
        "date": row["date"],
        "ticker_name": row["ticker_name"],
        "report_ticker": row.get("report_ticker", ""),
        "payout_type": row.get("payout_type"),
        "open_interest": _coerce_int(row.get("open_interest")),
        "daily_volume": _coerce_int(row.get("daily_volume")),
        "block_volume": _coerce_int(row.get("block_volume")),
        "high": _coerce_int(row.get("high")),
        "low": _coerce_int(row.get("low")),
        "status": row.get("status"),
    }


def sync_daily(db: AgentDatabase, max_workers: int = _DEFAULT_MAX_WORKERS) -> int:
    """Sync Kalshi daily data from S3 to DuckDB.

    Fully dynamic: queries ``MAX(date)`` from the table and fetches only
    missing days through yesterday.  On an empty table this backfills from
    2021-06-30.

    Downloads in parallel (up to ``max_workers`` concurrent S3 fetches).
    Results are processed in date order so cancellation always leaves a
    contiguous prefix — ``MAX(date)`` is correct on the next run.

    Returns total number of rows inserted.
    """
    _shutdown_event.clear()
    max_date_str = db.get_kalshi_daily_max_date()
    if max_date_str:
        start_date = date.fromisoformat(max_date_str) + timedelta(days=1)
    else:
        start_date = FIRST_AVAILABLE_DATE

    yesterday = datetime.now(UTC).date() - timedelta(days=1)

    if start_date > yesterday:
        logger.info("Kalshi daily data is up to date (through %s)", yesterday)
        return 0

    total_days = (yesterday - start_date).days + 1
    dates = [start_date + timedelta(days=i) for i in range(total_days)]
    logger.info(
        "Syncing Kalshi daily data: %s to %s (%d days, %d workers)",
        start_date,
        yesterday,
        total_days,
        max_workers,
    )

    total_rows = 0
    completed = 0

    pool = ThreadPoolExecutor(max_workers=max_workers)
    # Submit all days; iterate in date order so cancellation leaves
    # a contiguous prefix (workers still fetch in parallel).
    futures = [pool.submit(_fetch_and_normalise, d) for d in dates]

    try:
        for future in futures:
            d, rows, fetch_elapsed = future.result()
            completed += 1

            if rows:
                t0 = time.time()
                inserted = db.insert_kalshi_daily_bulk(rows)
                insert_elapsed = time.time() - t0
                total_rows += inserted
                logger.info(
                    "  %s: %d records, fetch=%.1fs insert=%.1fs [%d/%d]",
                    d,
                    len(rows),
                    fetch_elapsed,
                    insert_elapsed,
                    completed,
                    total_days,
                )
            else:
                logger.info(
                    "  %s: no data, fetch=%.1fs [%d/%d]",
                    d,
                    fetch_elapsed,
                    completed,
                    total_days,
                )
    except KeyboardInterrupt:
        logger.info("Interrupted — stopping workers...")
        _shutdown_event.set()
        pool.shutdown(wait=True, cancel_futures=True)
        logger.info("Saved %d rows across %d days before interruption", total_rows, completed)
        return total_rows
    else:
        pool.shutdown(wait=False)

    # Checkpoint WAL and update query planner statistics
    db.maintenance()

    logger.info("Daily sync complete: %d total rows across %d days", total_rows, total_days)
    return total_rows


def run_backfill() -> None:
    """CLI entry point for standalone backfill."""
    from .config import load_configs
    from .logging_config import setup_logging

    setup_logging()

    _, _, trading_config = load_configs()
    db = AgentDatabase(trading_config.db_path)

    try:
        start = time.time()
        total = sync_daily(db)
        elapsed = time.time() - start
        logger.info("Backfill finished in %.1fs (%d rows)", elapsed, total)
    finally:
        db.close()


if __name__ == "__main__":
    run_backfill()
