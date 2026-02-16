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
