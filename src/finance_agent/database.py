"""SQLite database for agent state, market data, signals, and trades."""

from __future__ import annotations

import json
import sqlite3
import time
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

_SCHEMA = """
-- Market data snapshots (populated by collector)
CREATE TABLE IF NOT EXISTS market_snapshots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    captured_at TEXT NOT NULL,
    source TEXT NOT NULL DEFAULT 'collector',
    ticker TEXT NOT NULL,
    event_ticker TEXT,
    series_ticker TEXT,
    title TEXT,
    category TEXT,
    status TEXT,
    yes_bid INTEGER,
    yes_ask INTEGER,
    no_bid INTEGER,
    no_ask INTEGER,
    last_price INTEGER,
    volume INTEGER,
    volume_24h INTEGER,
    open_interest INTEGER,
    spread_cents INTEGER,
    mid_price_cents INTEGER,
    implied_probability REAL,
    days_to_expiration REAL,
    close_time TEXT,
    settlement_value INTEGER,
    markets_in_event INTEGER,
    raw_json TEXT
);

-- Event structure (for cross-market analysis)
CREATE TABLE IF NOT EXISTS events (
    event_ticker TEXT PRIMARY KEY,
    series_ticker TEXT,
    title TEXT,
    category TEXT,
    mutually_exclusive INTEGER,
    last_updated TEXT,
    markets_json TEXT
);

-- Pre-computed signals (populated by signal generator)
CREATE TABLE IF NOT EXISTS signals (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    generated_at TEXT NOT NULL,
    scan_type TEXT NOT NULL,
    ticker TEXT NOT NULL,
    event_ticker TEXT,
    signal_strength REAL,
    estimated_edge_pct REAL,
    details_json TEXT,
    status TEXT DEFAULT 'pending',
    acted_at TEXT,
    session_id TEXT
);

-- Agent's trades
CREATE TABLE IF NOT EXISTS trades (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT NOT NULL,
    timestamp TEXT NOT NULL,
    ticker TEXT NOT NULL,
    action TEXT NOT NULL,
    side TEXT NOT NULL,
    count INTEGER NOT NULL,
    price_cents INTEGER,
    order_type TEXT,
    order_id TEXT,
    status TEXT,
    thesis TEXT,
    strategy TEXT,
    edge_pct REAL,
    kelly_fraction REAL,
    result_json TEXT
);

-- Agent's probability predictions (for calibration)
CREATE TABLE IF NOT EXISTS predictions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at TEXT NOT NULL,
    market_ticker TEXT NOT NULL,
    prediction REAL NOT NULL,
    market_price_cents INTEGER,
    methodology TEXT,
    outcome INTEGER,
    resolved_at TEXT,
    notes TEXT
);

-- Portfolio state over time
CREATE TABLE IF NOT EXISTS portfolio_snapshots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    captured_at TEXT NOT NULL,
    session_id TEXT,
    balance_usd REAL,
    positions_json TEXT,
    open_orders_json TEXT
);

-- Session lifecycle
CREATE TABLE IF NOT EXISTS sessions (
    id TEXT PRIMARY KEY,
    started_at TEXT NOT NULL,
    ended_at TEXT,
    profile TEXT,
    summary TEXT,
    trades_placed INTEGER DEFAULT 0,
    pnl_usd REAL
);

-- Markets to track across sessions
CREATE TABLE IF NOT EXISTS watchlist (
    ticker TEXT PRIMARY KEY,
    added_at TEXT NOT NULL,
    reason TEXT,
    alert_condition TEXT
);

-- Indexes
CREATE INDEX IF NOT EXISTS idx_snapshots_ticker_time
    ON market_snapshots(ticker, captured_at);
CREATE INDEX IF NOT EXISTS idx_snapshots_series
    ON market_snapshots(series_ticker);
CREATE INDEX IF NOT EXISTS idx_snapshots_category
    ON market_snapshots(category);
CREATE INDEX IF NOT EXISTS idx_signals_pending
    ON signals(status) WHERE status = 'pending';
CREATE INDEX IF NOT EXISTS idx_signals_type
    ON signals(scan_type);
CREATE INDEX IF NOT EXISTS idx_trades_ticker
    ON trades(ticker);
CREATE INDEX IF NOT EXISTS idx_predictions_unresolved
    ON predictions(outcome) WHERE outcome IS NULL;
"""


class AgentDatabase:
    """SQLite database for the trading agent.

    Uses WAL mode for concurrent access (collector + agent).
    """

    def __init__(self, db_path: str | Path) -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(
            str(self.db_path),
            timeout=30,
            check_same_thread=False,
        )
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA foreign_keys=ON")
        self._conn.execute("PRAGMA busy_timeout=30000")
        self._init_schema()

    def _init_schema(self) -> None:
        self._conn.executescript(_SCHEMA)
        self._conn.commit()

    def close(self) -> None:
        self._conn.close()

    # ── Generic query ────────────────────────────────────────────

    def query(self, sql: str, params: tuple = ()) -> list[dict[str, Any]]:
        """Execute a read-only SELECT query. Returns list of dicts."""
        sql_stripped = sql.strip().upper()
        if not sql_stripped.startswith("SELECT") and not sql_stripped.startswith("WITH"):
            raise ValueError("Only SELECT / WITH queries allowed via db_query")
        cursor = self._conn.execute(sql, params)
        columns = [desc[0] for desc in cursor.description] if cursor.description else []
        return [dict(zip(columns, row, strict=False)) for row in cursor.fetchall()]

    def execute(self, sql: str, params: tuple = ()) -> sqlite3.Cursor:
        """Execute a write query (INSERT/UPDATE/DELETE)."""
        cursor = self._conn.execute(sql, params)
        self._conn.commit()
        return cursor

    def executemany(self, sql: str, params_list: list[tuple]) -> None:
        """Execute a parameterized query for many rows."""
        self._conn.executemany(sql, params_list)
        self._conn.commit()

    # ── Sessions ─────────────────────────────────────────────────

    def create_session(self, profile: str = "demo") -> str:
        """Create a new session, return its ID."""
        session_id = str(uuid.uuid4())[:8]
        now = datetime.now(UTC).isoformat()
        self.execute(
            "INSERT INTO sessions (id, started_at, profile) VALUES (?, ?, ?)",
            (session_id, now, profile),
        )
        return session_id

    def end_session(
        self,
        session_id: str,
        summary: str | None = None,
        trades_placed: int = 0,
        pnl_usd: float | None = None,
    ) -> None:
        """Mark a session as ended."""
        now = datetime.now(UTC).isoformat()
        self.execute(
            """UPDATE sessions
               SET ended_at = ?, summary = ?, trades_placed = ?, pnl_usd = ?
               WHERE id = ?""",
            (now, summary, trades_placed, pnl_usd, session_id),
        )

    # ── Trades ───────────────────────────────────────────────────

    def log_trade(
        self,
        session_id: str,
        ticker: str,
        action: str,
        side: str,
        count: int,
        price_cents: int | None = None,
        order_type: str | None = None,
        order_id: str | None = None,
        status: str | None = None,
        thesis: str | None = None,
        strategy: str | None = None,
        edge_pct: float | None = None,
        kelly_fraction: float | None = None,
        result_json: str | None = None,
    ) -> int:
        """Insert a trade record, return its ID."""
        now = datetime.now(UTC).isoformat()
        cursor = self.execute(
            """INSERT INTO trades
               (session_id, timestamp, ticker, action, side, count, price_cents,
                order_type, order_id, status, thesis, strategy, edge_pct,
                kelly_fraction, result_json)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                session_id,
                now,
                ticker,
                action,
                side,
                count,
                price_cents,
                order_type,
                order_id,
                status,
                thesis,
                strategy,
                edge_pct,
                kelly_fraction,
                result_json,
            ),
        )
        return cursor.lastrowid or 0

    # ── Predictions ──────────────────────────────────────────────

    def log_prediction(
        self,
        market_ticker: str,
        prediction: float,
        market_price_cents: int | None = None,
        methodology: str | None = None,
        notes: str | None = None,
    ) -> int:
        """Insert a prediction, return its ID."""
        now = datetime.now(UTC).isoformat()
        cursor = self.execute(
            """INSERT INTO predictions
               (created_at, market_ticker, prediction, market_price_cents,
                methodology, notes)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (now, market_ticker, prediction, market_price_cents, methodology, notes),
        )
        return cursor.lastrowid or 0

    def resolve_prediction(self, prediction_id: int, outcome: int) -> None:
        """Resolve a prediction (outcome: 1=yes, 0=no)."""
        now = datetime.now(UTC).isoformat()
        self.execute(
            "UPDATE predictions SET outcome = ?, resolved_at = ? WHERE id = ?",
            (outcome, now, prediction_id),
        )

    # ── Portfolio snapshots ──────────────────────────────────────

    def log_portfolio_snapshot(
        self,
        session_id: str | None,
        balance_usd: float | None,
        positions_json: str | None = None,
        open_orders_json: str | None = None,
    ) -> None:
        now = datetime.now(UTC).isoformat()
        self.execute(
            """INSERT INTO portfolio_snapshots
               (captured_at, session_id, balance_usd, positions_json, open_orders_json)
               VALUES (?, ?, ?, ?, ?)""",
            (now, session_id, balance_usd, positions_json, open_orders_json),
        )

    # ── Market snapshots (bulk insert for collector) ─────────────

    def insert_market_snapshots(self, rows: list[dict[str, Any]]) -> int:
        """Bulk insert market snapshots. Returns count inserted."""
        if not rows:
            return 0
        cols = [
            "captured_at",
            "source",
            "ticker",
            "event_ticker",
            "series_ticker",
            "title",
            "category",
            "status",
            "yes_bid",
            "yes_ask",
            "no_bid",
            "no_ask",
            "last_price",
            "volume",
            "volume_24h",
            "open_interest",
            "spread_cents",
            "mid_price_cents",
            "implied_probability",
            "days_to_expiration",
            "close_time",
            "settlement_value",
            "markets_in_event",
            "raw_json",
        ]
        placeholders = ", ".join(["?"] * len(cols))
        col_names = ", ".join(cols)
        params_list = [tuple(row.get(c) for c in cols) for row in rows]
        self.executemany(
            f"INSERT INTO market_snapshots ({col_names}) VALUES ({placeholders})",
            params_list,
        )
        return len(params_list)

    # ── Events (upsert for collector) ────────────────────────────

    def upsert_event(
        self,
        event_ticker: str,
        series_ticker: str | None = None,
        title: str | None = None,
        category: str | None = None,
        mutually_exclusive: bool | None = None,
        markets_json: str | None = None,
    ) -> None:
        now = datetime.now(UTC).isoformat()
        self.execute(
            """INSERT INTO events
               (event_ticker, series_ticker, title, category, mutually_exclusive,
                last_updated, markets_json)
               VALUES (?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(event_ticker) DO UPDATE SET
                 series_ticker = excluded.series_ticker,
                 title = excluded.title,
                 category = excluded.category,
                 mutually_exclusive = excluded.mutually_exclusive,
                 last_updated = excluded.last_updated,
                 markets_json = excluded.markets_json""",
            (
                event_ticker,
                series_ticker,
                title,
                category,
                1 if mutually_exclusive else 0,
                now,
                markets_json,
            ),
        )

    # ── Signals (bulk insert for signal generator) ───────────────

    def insert_signals(self, rows: list[dict[str, Any]]) -> int:
        """Bulk insert signals. Returns count inserted."""
        if not rows:
            return 0
        now = datetime.now(UTC).isoformat()
        params_list = []
        for row in rows:
            details = row.get("details_json")
            if isinstance(details, dict):
                details = json.dumps(details)
            params_list.append(
                (
                    now,
                    row["scan_type"],
                    row["ticker"],
                    row.get("event_ticker"),
                    row.get("signal_strength"),
                    row.get("estimated_edge_pct"),
                    details,
                )
            )
        self.executemany(
            """INSERT INTO signals
               (generated_at, scan_type, ticker, event_ticker,
                signal_strength, estimated_edge_pct, details_json)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            params_list,
        )
        return len(params_list)

    def expire_old_signals(self, max_age_hours: int = 48) -> int:
        """Mark old pending signals as expired. Returns count expired."""
        cutoff = datetime.now(UTC).isoformat()
        cursor = self.execute(
            """UPDATE signals SET status = 'expired'
               WHERE status = 'pending'
               AND generated_at < datetime(?, '-' || ? || ' hours')""",
            (cutoff, max_age_hours),
        )
        return cursor.rowcount

    # ── Watchlist ────────────────────────────────────────────────

    def add_to_watchlist(
        self, ticker: str, reason: str | None = None, alert_condition: str | None = None
    ) -> None:
        now = datetime.now(UTC).isoformat()
        self.execute(
            """INSERT INTO watchlist (ticker, added_at, reason, alert_condition)
               VALUES (?, ?, ?, ?)
               ON CONFLICT(ticker) DO UPDATE SET
                 reason = excluded.reason,
                 alert_condition = excluded.alert_condition""",
            (ticker, now, reason, alert_condition),
        )

    def remove_from_watchlist(self, ticker: str) -> None:
        self.execute("DELETE FROM watchlist WHERE ticker = ?", (ticker,))

    # ── Session state (for startup) ──────────────────────────────

    def get_session_state(self) -> dict[str, Any]:
        """Build compact session state for agent startup context."""
        # Last session
        last_sessions = self.query(
            """SELECT id, ended_at, summary, trades_placed, pnl_usd
               FROM sessions WHERE ended_at IS NOT NULL
               ORDER BY ended_at DESC LIMIT 1"""
        )
        last_session = last_sessions[0] if last_sessions else None

        # Pending signals (top 10 by strength)
        pending_signals = self.query(
            """SELECT scan_type, ticker, event_ticker, signal_strength,
                      estimated_edge_pct, details_json
               FROM signals WHERE status = 'pending'
               ORDER BY signal_strength DESC LIMIT 10"""
        )

        # Unresolved predictions
        unresolved = self.query(
            """SELECT id, market_ticker, prediction, market_price_cents, methodology
               FROM predictions WHERE outcome IS NULL
               ORDER BY created_at DESC LIMIT 20"""
        )

        # Watchlist
        watchlist = self.query("SELECT ticker, reason, alert_condition FROM watchlist")

        # Portfolio delta (last two snapshots)
        snapshots = self.query(
            """SELECT balance_usd, captured_at
               FROM portfolio_snapshots
               ORDER BY captured_at DESC LIMIT 2"""
        )
        portfolio_delta = None
        if len(snapshots) >= 2:
            portfolio_delta = {
                "balance_change": (snapshots[0]["balance_usd"] or 0)
                - (snapshots[1]["balance_usd"] or 0),
                "latest_balance": snapshots[0]["balance_usd"],
            }
        elif len(snapshots) == 1:
            portfolio_delta = {
                "balance_change": 0,
                "latest_balance": snapshots[0]["balance_usd"],
            }

        # Recent trades
        recent_trades = self.query(
            """SELECT ticker, action, side, count, price_cents, status, thesis
               FROM trades ORDER BY timestamp DESC LIMIT 5"""
        )

        return {
            "last_session": last_session,
            "pending_signals": pending_signals,
            "unresolved_predictions": unresolved,
            "watchlist": watchlist,
            "portfolio_delta": portfolio_delta,
            "recent_trades": recent_trades,
        }

    # ── Backup ───────────────────────────────────────────────────

    def backup_if_needed(
        self,
        backup_dir: str | Path,
        max_age_hours: int = 24,
        max_backups: int = 7,
    ) -> str | None:
        """Create a backup if the most recent is older than max_age_hours.

        Returns the backup path if created, None if skipped.
        """
        backup_dir = Path(backup_dir)
        backup_dir.mkdir(parents=True, exist_ok=True)

        # Find most recent backup
        backups = sorted(backup_dir.glob("agent_*.db"), key=lambda p: p.stat().st_mtime)
        if backups:
            newest = backups[-1]
            age_hours = (time.time() - newest.stat().st_mtime) / 3600
            if age_hours < max_age_hours:
                return None

        # Create backup
        ts = datetime.now(UTC).strftime("%Y%m%d_%H%M%S")
        backup_path = backup_dir / f"agent_{ts}.db"
        backup_conn = sqlite3.connect(str(backup_path))
        self._conn.backup(backup_conn)
        backup_conn.close()

        # Prune old backups
        backups = sorted(backup_dir.glob("agent_*.db"), key=lambda p: p.stat().st_mtime)
        while len(backups) > max_backups:
            backups.pop(0).unlink()

        return str(backup_path)
