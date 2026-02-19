"""One-time migration: copy data from SQLite to DuckDB.

Usage:
    python scripts/migrate_sqlite_to_duckdb.py [--sqlite PATH] [--duckdb PATH]

Requires both the old SQLite DB and the new (empty) DuckDB to exist.
Run `make collect` first to create the DuckDB schema via Alembic, then
run this script to copy historical data.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path


def migrate(sqlite_path: str, duckdb_path: str) -> None:
    import duckdb

    if not Path(sqlite_path).exists():
        print(f"SQLite DB not found: {sqlite_path}")  # noqa: T201
        sys.exit(1)
    if not Path(duckdb_path).exists():
        print(f"DuckDB not found: {duckdb_path}")  # noqa: T201
        print("Run `make collect` first to create the DuckDB schema.")  # noqa: T201
        sys.exit(1)

    conn = duckdb.connect(duckdb_path)
    conn.execute("INSTALL sqlite; LOAD sqlite")
    conn.execute(f"ATTACH '{sqlite_path}' AS old (TYPE sqlite)")

    # Order matters: parent tables before children (FK constraints)
    tables = [
        "sessions",
        "events",
        "market_snapshots",
        "kalshi_daily",
        "kalshi_market_meta",
        "recommendation_groups",
        "recommendation_legs",
        "trades",
    ]

    # Tables with ON CONFLICT support for re-runnability on partial failures
    conflict_sql = {
        "kalshi_daily": (
            "INSERT INTO main.kalshi_daily "
            "SELECT DISTINCT ON (date, ticker_name) * FROM old.kalshi_daily "
            "ORDER BY date, ticker_name "
            "ON CONFLICT (date, ticker_name) DO NOTHING"
        ),
        "kalshi_market_meta": (
            "INSERT INTO main.kalshi_market_meta "
            "SELECT * FROM old.kalshi_market_meta "
            "ON CONFLICT (ticker) DO NOTHING"
        ),
        "events": (
            "INSERT INTO main.events "
            "SELECT * FROM old.events "
            "ON CONFLICT (event_ticker, exchange) DO NOTHING"
        ),
    }

    for table in tables:
        # Tables without ON CONFLICT: skip if target already has data
        if table not in conflict_sql:
            target_count = conn.execute(f"SELECT COUNT(*) FROM main.{table}").fetchone()[0]
            if target_count > 0:
                print(f"  {table}: skipped ({target_count} rows already in DuckDB)")  # noqa: T201
                continue

        sql = conflict_sql.get(table, f"INSERT INTO main.{table} SELECT * FROM old.{table}")
        try:
            count = conn.execute(sql).fetchone()[0]
            print(f"  {table}: {count} rows migrated")  # noqa: T201
        except Exception as e:
            if "does not exist" in str(e):
                print(f"  {table}: skipped (not in SQLite)")  # noqa: T201
            else:
                raise

    # Reset sequences to avoid ID collisions.
    # DuckDB doesn't support ALTER SEQUENCE RESTART, so we drop + recreate.
    seq_tables = {
        "market_snapshots": "market_snapshot_id_seq",
        "trades": "trade_id_seq",
        "recommendation_groups": "rec_group_id_seq",
        "recommendation_legs": "rec_leg_id_seq",
        "kalshi_daily": "kalshi_daily_id_seq",
    }
    for table, seq_name in seq_tables.items():
        max_id = conn.execute(f"SELECT COALESCE(MAX(id), 0) + 1 FROM main.{table}").fetchone()[0]
        conn.execute(f"DROP SEQUENCE IF EXISTS {seq_name}")
        conn.execute(f"CREATE SEQUENCE {seq_name} START {max_id}")
        print(f"  Sequence {seq_name} reset to {max_id}")  # noqa: T201

    conn.execute("DETACH old")
    conn.execute("CHECKPOINT")
    conn.close()
    print("\nMigration complete!")  # noqa: T201


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Migrate SQLite data to DuckDB")
    parser.add_argument(
        "--sqlite",
        default="workspace/data/agent.db",
        help="Path to source SQLite DB",
    )
    parser.add_argument(
        "--duckdb",
        default="workspace/data/agent.duckdb",
        help="Path to target DuckDB",
    )
    args = parser.parse_args()
    migrate(args.sqlite, args.duckdb)
