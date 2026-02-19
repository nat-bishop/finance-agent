"""Reusable database helpers for analysis scripts (DuckDB)."""
import time
import duckdb
from pathlib import Path

DB_PATH = Path("/workspace/data/agent.duckdb")
DEFAULT_LIMIT = 10_000


def connect(retries=3, backoff=0.5):
    """Get a read-only DuckDB connection with retry on lock."""
    for attempt in range(retries):
        try:
            return duckdb.connect(str(DB_PATH), read_only=True)
        except duckdb.IOException:
            if attempt < retries - 1:
                time.sleep(backoff * (attempt + 1))
            else:
                raise


def query(sql, params=(), *, limit=DEFAULT_LIMIT):
    """Execute SQL and return list of dicts. Auto-applies LIMIT unless disabled.

    Args:
        sql: SQL query string.
        params: Query parameters (tuple).
        limit: Max rows to return. Set to 0 or None to disable.
    """
    if limit and "LIMIT" not in sql.upper():
        sql = f"{sql.rstrip().rstrip(';')} LIMIT {limit}"
    conn = connect()
    result = conn.execute(sql, params)
    columns = [desc[0] for desc in result.description]
    rows = result.fetchall()
    conn.close()
    return [dict(zip(columns, row)) for row in rows]
