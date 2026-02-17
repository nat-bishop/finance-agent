"""Reusable database helpers for analysis scripts."""
import sqlite3
from pathlib import Path

DB_PATH = Path("/workspace/data/agent.db")


def connect():
    """Get a SQLite connection with dict row factory."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def query(sql, params=()):
    """Execute SQL and return list of dicts."""
    conn = connect()
    rows = conn.execute(sql, params).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def latest_snapshot_ids():
    """SQL subquery for latest snapshot ID per open ticker.

    Use inside an IN clause:
        f"... AND id IN ({latest_snapshot_ids()})"
    """
    return (
        "SELECT MAX(id) FROM market_snapshots "
        "WHERE status = 'open' AND exchange = 'kalshi' GROUP BY ticker"
    )


def materialize_latest_ids(conn):
    """Create temp table with latest snapshot IDs on the given connection.

    Use when IN(latest_snapshot_ids()) is too slow inside JOINs.
    After calling, JOIN against _latest_ids instead:
        JOIN _latest_ids li ON ms.id = li.id
    """
    conn.execute("CREATE TEMP TABLE IF NOT EXISTS _latest_ids (id INTEGER PRIMARY KEY)")
    conn.execute("DELETE FROM _latest_ids")
    conn.execute(f"INSERT INTO _latest_ids {latest_snapshot_ids()}")


def latest_snapshots(columns="*", where="", params=()):
    """Query latest snapshot per open ticker with optional filtering.

    Args:
        columns: SQL column list (default "*")
        where: additional WHERE clause (without leading AND)
        params: query parameters for the where clause
    """
    extra = f"AND {where}" if where else ""
    return query(
        f"SELECT {columns} FROM market_snapshots "
        f"WHERE status = 'open' AND exchange = 'kalshi' "
        f"AND id IN ({latest_snapshot_ids()}) {extra}",
        params,
    )
