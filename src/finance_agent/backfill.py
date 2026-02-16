"""Kalshi historical daily data backfill.

Fetches EOD market data from Kalshi's public S3 reporting bucket and stores
it in SQLite.  Called automatically by the collector (incremental) or
standalone via ``python -m finance_agent.backfill``.
"""

from __future__ import annotations

import json
import logging
import time
import urllib.request
from datetime import UTC, date, datetime, timedelta
from typing import Any

from .database import AgentDatabase

logger = logging.getLogger(__name__)

S3_URL_TEMPLATE = "https://kalshi-public-docs.s3.amazonaws.com/reporting/market_data_{date}.json"
FIRST_AVAILABLE_DATE = date(2021, 6, 30)


def _fetch_daily(d: date) -> list[dict[str, Any]] | None:
    """Fetch a single day's JSON from S3. Returns None on 404/error."""
    url = S3_URL_TEMPLATE.format(date=d.isoformat())
    try:
        with urllib.request.urlopen(url, timeout=30) as resp:  # noqa: S310
            return json.loads(resp.read())
    except urllib.error.HTTPError as e:
        if e.code == 404:
            logger.debug("No data for %s (404)", d)
            return None
        logger.warning("HTTP %d fetching %s", e.code, url)
        return None
    except Exception:
        logger.exception("Error fetching %s", url)
        return None


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


def sync_daily(db: AgentDatabase) -> int:
    """Sync Kalshi daily data from S3 to SQLite.

    Fully dynamic: queries ``MAX(date)`` from the table and fetches only
    missing days through yesterday.  On an empty table this backfills from
    2021-06-30.

    Returns total number of rows inserted/updated.
    """
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
    logger.info(
        "Syncing Kalshi daily data: %s to %s (%d days)",
        start_date,
        yesterday,
        total_days,
    )

    total_rows = 0
    current = start_date
    while current <= yesterday:
        records = _fetch_daily(current)
        if records:
            normalised = [_normalise_row(r) for r in records]
            inserted = db.insert_kalshi_daily(normalised)
            total_rows += inserted
            logger.info("  %s: %d markets", current, inserted)
        current += timedelta(days=1)
        time.sleep(0.1)

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
