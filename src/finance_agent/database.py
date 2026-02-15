"""SQLite database for agent state, market data, signals, and trades."""

from __future__ import annotations

import json
import sqlite3
import time
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


def _now() -> str:
    return datetime.now(UTC).isoformat()


_SCHEMA = """
-- Market data snapshots (populated by collector)
CREATE TABLE IF NOT EXISTS market_snapshots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    captured_at TEXT NOT NULL,
    source TEXT NOT NULL DEFAULT 'collector',
    exchange TEXT NOT NULL DEFAULT 'kalshi',
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
    event_ticker TEXT NOT NULL,
    exchange TEXT NOT NULL DEFAULT 'kalshi',
    series_ticker TEXT,
    title TEXT,
    category TEXT,
    mutually_exclusive INTEGER,
    last_updated TEXT,
    markets_json TEXT,
    PRIMARY KEY (event_ticker, exchange)
);

-- Pre-computed signals (populated by signal generator)
CREATE TABLE IF NOT EXISTS signals (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    generated_at TEXT NOT NULL,
    scan_type TEXT NOT NULL,
    exchange TEXT DEFAULT 'kalshi',
    ticker TEXT NOT NULL,
    event_ticker TEXT,
    signal_strength REAL,
    estimated_edge_pct REAL,
    details_json TEXT,
    status TEXT DEFAULT 'pending',
    acted_at TEXT,
    session_id TEXT
);

-- Agent's trades (lean schema)
CREATE TABLE IF NOT EXISTS trades (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT NOT NULL,
    exchange TEXT NOT NULL,
    timestamp TEXT NOT NULL,
    ticker TEXT NOT NULL,
    action TEXT NOT NULL,
    side TEXT NOT NULL,
    count INTEGER NOT NULL,
    price_cents INTEGER,
    order_type TEXT,
    order_id TEXT,
    status TEXT,
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
    ticker TEXT NOT NULL,
    exchange TEXT NOT NULL DEFAULT 'kalshi',
    added_at TEXT NOT NULL,
    reason TEXT,
    alert_condition TEXT,
    PRIMARY KEY (ticker, exchange)
);

-- Indexes
CREATE INDEX IF NOT EXISTS idx_snapshots_ticker_time
    ON market_snapshots(ticker, captured_at);
CREATE INDEX IF NOT EXISTS idx_snapshots_series
    ON market_snapshots(series_ticker);
CREATE INDEX IF NOT EXISTS idx_snapshots_category
    ON market_snapshots(category);
CREATE INDEX IF NOT EXISTS idx_snapshots_exchange
    ON market_snapshots(exchange);
CREATE INDEX IF NOT EXISTS idx_snapshots_exchange_status
    ON market_snapshots(exchange, status);
CREATE INDEX IF NOT EXISTS idx_signals_pending
    ON signals(status) WHERE status = 'pending';
CREATE INDEX IF NOT EXISTS idx_signals_type
    ON signals(scan_type);
CREATE INDEX IF NOT EXISTS idx_signals_exchange
    ON signals(exchange);
CREATE INDEX IF NOT EXISTS idx_trades_ticker
    ON trades(ticker);
CREATE INDEX IF NOT EXISTS idx_trades_session
    ON trades(session_id);
CREATE INDEX IF NOT EXISTS idx_trades_status
    ON trades(status);
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
        self._migrate_schema()

    def _init_schema(self) -> None:
        self._conn.executescript(_SCHEMA)
        self._conn.commit()

    def _migrate_schema(self) -> None:
        """Add columns that may not exist in older databases."""
        migrations = [
            ("market_snapshots", "exchange", "TEXT NOT NULL DEFAULT 'kalshi'"),
            ("trades", "exchange", "TEXT NOT NULL DEFAULT 'kalshi'"),
            ("signals", "exchange", "TEXT DEFAULT 'kalshi'"),
            ("watchlist", "exchange", "TEXT NOT NULL DEFAULT 'kalshi'"),
            ("events", "exchange", "TEXT NOT NULL DEFAULT 'kalshi'"),
        ]
        for table, column, col_type in migrations:
            try:
                self._conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {col_type}")
                self._conn.commit()
            except sqlite3.OperationalError:
                pass  # Column already exists

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
        self.execute(
            "INSERT INTO sessions (id, started_at, profile) VALUES (?, ?, ?)",
            (session_id, _now(), profile),
        )
        return session_id

    def end_session(
        self,
        session_id: str,
        summary: str | None = None,
        trades_placed: int = 0,
        pnl_usd: float | None = None,
    ) -> None:
        self.execute(
            """UPDATE sessions
               SET ended_at = ?, summary = ?, trades_placed = ?, pnl_usd = ?
               WHERE id = ?""",
            (_now(), summary, trades_placed, pnl_usd, session_id),
        )

    # ── Trades (lean schema) ─────────────────────────────────────

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
        result_json: str | None = None,
        exchange: str = "kalshi",
    ) -> int:
        cursor = self.execute(
            """INSERT INTO trades
               (session_id, exchange, timestamp, ticker, action, side, count, price_cents,
                order_type, order_id, status, result_json)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                session_id,
                exchange,
                _now(),
                ticker,
                action,
                side,
                count,
                price_cents,
                order_type,
                order_id,
                status,
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
        cursor = self.execute(
            """INSERT INTO predictions
               (created_at, market_ticker, prediction, market_price_cents,
                methodology, notes)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (_now(), market_ticker, prediction, market_price_cents, methodology, notes),
        )
        return cursor.lastrowid or 0

    def resolve_prediction(self, prediction_id: int, outcome: int) -> None:
        self.execute(
            "UPDATE predictions SET outcome = ?, resolved_at = ? WHERE id = ?",
            (outcome, _now(), prediction_id),
        )

    def auto_resolve_predictions(self) -> list[dict[str, Any]]:
        """Auto-resolve unresolved predictions by matching against settled market_snapshots.

        Returns list of newly resolved predictions for startup context.
        """
        unresolved = self.query(
            """SELECT p.id, p.market_ticker, p.prediction
               FROM predictions p
               WHERE p.outcome IS NULL"""
        )
        if not unresolved:
            return []

        resolved = []
        now = _now()
        for pred in unresolved:
            ticker = pred["market_ticker"]
            settled = self.query(
                """SELECT settlement_value
                   FROM market_snapshots
                   WHERE ticker = ? AND status = 'settled' AND settlement_value IS NOT NULL
                   ORDER BY captured_at DESC LIMIT 1""",
                (ticker,),
            )
            if settled:
                outcome = settled[0]["settlement_value"]
                self.execute(
                    "UPDATE predictions SET outcome = ?, resolved_at = ? WHERE id = ?",
                    (outcome, now, pred["id"]),
                )
                resolved.append(
                    {
                        "prediction_id": pred["id"],
                        "market_ticker": ticker,
                        "prediction": pred["prediction"],
                        "outcome": outcome,
                        "correct": (pred["prediction"] >= 0.5) == (outcome == 1),
                    }
                )
        return resolved

    # ── Portfolio snapshots ──────────────────────────────────────

    def log_portfolio_snapshot(
        self,
        session_id: str | None,
        balance_usd: float | None,
        positions_json: str | None = None,
        open_orders_json: str | None = None,
    ) -> None:
        self.execute(
            """INSERT INTO portfolio_snapshots
               (captured_at, session_id, balance_usd, positions_json, open_orders_json)
               VALUES (?, ?, ?, ?, ?)""",
            (_now(), session_id, balance_usd, positions_json, open_orders_json),
        )

    # ── Market snapshots (bulk insert for collector) ─────────────

    def insert_market_snapshots(self, rows: list[dict[str, Any]]) -> int:
        """Bulk insert market snapshots. Returns count inserted."""
        if not rows:
            return 0
        cols = [
            "captured_at",
            "source",
            "exchange",
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
        params_list = [tuple(row.get(c) for c in cols) for row in rows]
        self.executemany(
            f"INSERT INTO market_snapshots ({', '.join(cols)}) VALUES ({placeholders})",
            params_list,
        )
        return len(params_list)

    # ── Events (upsert for collector) ────────────────────────────

    def upsert_event(
        self,
        event_ticker: str,
        exchange: str = "kalshi",
        series_ticker: str | None = None,
        title: str | None = None,
        category: str | None = None,
        mutually_exclusive: bool | None = None,
        markets_json: str | None = None,
    ) -> None:
        self.execute(
            """INSERT INTO events
               (event_ticker, exchange, series_ticker, title, category, mutually_exclusive,
                last_updated, markets_json)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(event_ticker, exchange) DO UPDATE SET
                 series_ticker = excluded.series_ticker,
                 title = excluded.title,
                 category = excluded.category,
                 mutually_exclusive = excluded.mutually_exclusive,
                 last_updated = excluded.last_updated,
                 markets_json = excluded.markets_json""",
            (
                event_ticker,
                exchange,
                series_ticker,
                title,
                category,
                1 if mutually_exclusive else 0,
                _now(),
                markets_json,
            ),
        )

    # ── Signals (bulk insert for signal generator) ───────────────

    def insert_signals(self, rows: list[dict[str, Any]]) -> int:
        if not rows:
            return 0
        now = _now()
        params_list = []
        for row in rows:
            details = row.get("details_json")
            if isinstance(details, dict):
                details = json.dumps(details)
            params_list.append(
                (
                    now,
                    row["scan_type"],
                    row.get("exchange", "kalshi"),
                    row["ticker"],
                    row.get("event_ticker"),
                    row.get("signal_strength"),
                    row.get("estimated_edge_pct"),
                    details,
                )
            )
        self.executemany(
            """INSERT INTO signals
               (generated_at, scan_type, exchange, ticker, event_ticker,
                signal_strength, estimated_edge_pct, details_json)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            params_list,
        )
        return len(params_list)

    def expire_old_signals(self, max_age_hours: int = 48) -> int:
        cursor = self.execute(
            """UPDATE signals SET status = 'expired'
               WHERE status = 'pending'
               AND generated_at < datetime(?, '-' || ? || ' hours')""",
            (_now(), max_age_hours),
        )
        return cursor.rowcount

    # ── Watchlist ────────────────────────────────────────────────

    def add_to_watchlist(
        self,
        ticker: str,
        reason: str | None = None,
        alert_condition: str | None = None,
        exchange: str = "kalshi",
    ) -> None:
        self.execute(
            """INSERT INTO watchlist (ticker, exchange, added_at, reason, alert_condition)
               VALUES (?, ?, ?, ?, ?)
               ON CONFLICT(ticker, exchange) DO UPDATE SET
                 reason = excluded.reason,
                 alert_condition = excluded.alert_condition""",
            (ticker, exchange, _now(), reason, alert_condition),
        )

    def remove_from_watchlist(self, ticker: str, exchange: str | None = None) -> None:
        if exchange:
            self.execute(
                "DELETE FROM watchlist WHERE ticker = ? AND exchange = ?", (ticker, exchange)
            )
        else:
            self.execute("DELETE FROM watchlist WHERE ticker = ?", (ticker,))

    # ── Session state (for startup) ──────────────────────────────

    def get_session_state(self) -> dict[str, Any]:
        last_sessions = self.query(
            """SELECT id, ended_at, summary, trades_placed, pnl_usd
               FROM sessions WHERE ended_at IS NOT NULL
               ORDER BY ended_at DESC LIMIT 1"""
        )

        snapshots = self.query(
            """SELECT balance_usd FROM portfolio_snapshots
               ORDER BY captured_at DESC LIMIT 2"""
        )
        portfolio_delta = None
        if snapshots:
            latest = snapshots[0]["balance_usd"] or 0
            prev = snapshots[1]["balance_usd"] or 0 if len(snapshots) >= 2 else latest
            portfolio_delta = {"balance_change": latest - prev, "latest_balance": latest}

        return {
            "last_session": last_sessions[0] if last_sessions else None,
            "pending_signals": self.query(
                """SELECT scan_type, exchange, ticker, event_ticker, signal_strength,
                          estimated_edge_pct, details_json
                   FROM signals WHERE status = 'pending'
                   ORDER BY signal_strength DESC LIMIT 10"""
            ),
            "unresolved_predictions": self.query(
                """SELECT id, market_ticker, prediction, market_price_cents, methodology
                   FROM predictions WHERE outcome IS NULL
                   ORDER BY created_at DESC LIMIT 20"""
            ),
            "watchlist": self.query(
                "SELECT ticker, exchange, reason, alert_condition FROM watchlist"
            ),
            "portfolio_delta": portfolio_delta,
            "recent_trades": self.query(
                """SELECT exchange, ticker, action, side, count, price_cents, status
                   FROM trades ORDER BY timestamp DESC LIMIT 5"""
            ),
            "unreconciled_trades": self.query(
                """SELECT exchange, ticker, action, side, count, price_cents, order_id
                   FROM trades WHERE status = 'placed'
                   ORDER BY timestamp DESC LIMIT 10"""
            ),
        }

    # ── Backup ───────────────────────────────────────────────────

    def backup_if_needed(
        self,
        backup_dir: str | Path,
        max_age_hours: int = 24,
        max_backups: int = 7,
    ) -> str | None:
        backup_dir = Path(backup_dir)
        backup_dir.mkdir(parents=True, exist_ok=True)

        backups = sorted(backup_dir.glob("agent_*.db"), key=lambda p: p.stat().st_mtime)
        if backups:
            age_hours = (time.time() - backups[-1].stat().st_mtime) / 3600
            if age_hours < max_age_hours:
                return None

        ts = datetime.now(UTC).strftime("%Y%m%d_%H%M%S")
        backup_path = backup_dir / f"agent_{ts}.db"
        backup_conn = sqlite3.connect(str(backup_path))
        self._conn.backup(backup_conn)
        backup_conn.close()

        backups = sorted(backup_dir.glob("agent_*.db"), key=lambda p: p.stat().st_mtime)
        for old in backups[:-max_backups]:
            old.unlink()

        return str(backup_path)
