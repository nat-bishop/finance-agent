"""SQLite database for agent state, market data, signals, and trades."""

from __future__ import annotations

import json
import sqlite3
import time
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any


def _now() -> str:
    return datetime.now(UTC).isoformat()


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
        self._run_migrations()

    def _run_migrations(self) -> None:
        """Run Alembic migrations to bring schema up to date."""
        from alembic import command
        from alembic.config import Config

        config = Config()
        config.set_main_option("script_location", str(Path(__file__).parent / "migrations"))
        config.set_main_option("sqlalchemy.url", f"sqlite:///{self.db_path}")

        # If tables exist but no alembic_version, stamp with initial revision
        cursor = self._conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='alembic_version'"
        )
        has_alembic = cursor.fetchone() is not None
        if not has_alembic:
            cursor2 = self._conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='sessions'"
            )
            has_tables = cursor2.fetchone() is not None
            if has_tables:
                command.stamp(config, "0001")

        command.upgrade(config, "head")

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

    def create_session(self) -> str:
        """Create a new session, return its ID."""
        session_id = str(uuid.uuid4())[:8]
        self.execute(
            "INSERT INTO sessions (id, started_at) VALUES (?, ?)",
            (session_id, _now()),
        )
        return session_id

    def end_session(
        self,
        session_id: str,
        summary: str | None = None,
        trades_placed: int = 0,
        recommendations_made: int = 0,
        pnl_usd: float | None = None,
    ) -> None:
        self.execute(
            """UPDATE sessions
               SET ended_at = ?, summary = ?, trades_placed = ?,
                   recommendations_made = ?, pnl_usd = ?
               WHERE id = ?""",
            (_now(), summary, trades_placed, recommendations_made, pnl_usd, session_id),
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

    # ── Recommendation Groups ────────────────────────────────────

    def log_recommendation_group(
        self,
        session_id: str,
        thesis: str | None = None,
        estimated_edge_pct: float | None = None,
        equivalence_notes: str | None = None,
        signal_id: int | None = None,
        legs: list[dict[str, Any]] | None = None,
        ttl_minutes: int = 60,
    ) -> tuple[int, str]:
        """Insert a recommendation group + legs atomically. Returns (group_id, expires_at)."""
        now = _now()
        expires_at = (datetime.fromisoformat(now) + timedelta(minutes=ttl_minutes)).isoformat()
        cursor = self.execute(
            """INSERT INTO recommendation_groups
               (session_id, created_at, thesis, equivalence_notes,
                estimated_edge_pct, signal_id, expires_at)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (
                session_id,
                now,
                thesis,
                equivalence_notes,
                estimated_edge_pct,
                signal_id,
                expires_at,
            ),
        )
        group_id = cursor.lastrowid or 0
        for i, leg in enumerate(legs or []):
            self.execute(
                """INSERT INTO recommendation_legs
                   (group_id, leg_index, exchange, market_id, market_title,
                    action, side, quantity, price_cents)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    group_id,
                    i,
                    leg["exchange"],
                    leg["market_id"],
                    leg.get("market_title"),
                    leg["action"],
                    leg["side"],
                    leg["quantity"],
                    leg["price_cents"],
                ),
            )
        return group_id, expires_at

    def _attach_legs(self, groups: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Fetch and attach legs to each group dict."""
        for group in groups:
            group["legs"] = self.query(
                """SELECT * FROM recommendation_legs
                   WHERE group_id = ? ORDER BY leg_index""",
                (group["id"],),
            )
        return groups

    def get_pending_groups(self) -> list[dict[str, Any]]:
        """Return pending groups with nested legs list."""
        groups = self.query(
            """SELECT * FROM recommendation_groups
               WHERE status = 'pending'
               ORDER BY created_at DESC"""
        )
        return self._attach_legs(groups)

    def get_group(self, group_id: int) -> dict[str, Any] | None:
        """Return a single group with legs."""
        rows = self.query("SELECT * FROM recommendation_groups WHERE id = ?", (group_id,))
        if not rows:
            return None
        return self._attach_legs(rows)[0]

    def update_leg_status(self, leg_id: int, status: str, order_id: str | None = None) -> None:
        """Update a single leg's status after exchange API call."""
        self.execute(
            """UPDATE recommendation_legs
               SET status = ?, order_id = ?, executed_at = ?
               WHERE id = ?""",
            (status, order_id, _now() if status == "executed" else None, leg_id),
        )

    def update_group_status(self, group_id: int, status: str) -> None:
        """Set group status. Also sets reviewed_at or executed_at timestamp."""
        ts_col = "executed_at" if status == "executed" else "reviewed_at"
        self.execute(
            f"""UPDATE recommendation_groups
               SET status = ?, {ts_col} = ?
               WHERE id = ?""",
            (status, _now(), group_id),
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

    # ── Session state (for startup) ──────────────────────────────

    def get_session_state(self) -> dict[str, Any]:
        last_sessions = self.query(
            """SELECT id, ended_at, summary, trades_placed, pnl_usd
               FROM sessions WHERE ended_at IS NOT NULL
               ORDER BY ended_at DESC LIMIT 1"""
        )
        return {
            "last_session": last_sessions[0] if last_sessions else None,
            "pending_signals": self.query(
                """SELECT scan_type, exchange, ticker, event_ticker,
                          signal_strength, estimated_edge_pct
                   FROM signals WHERE status = 'pending'
                   ORDER BY signal_strength DESC LIMIT 10"""
            ),
            "unreconciled_trades": self.query(
                """SELECT exchange, ticker, action, side, count, price_cents, order_id
                   FROM trades WHERE status = 'placed'
                   ORDER BY timestamp DESC LIMIT 10"""
            ),
        }

    # ── TUI query methods ────────────────────────────────────────

    def get_recommendations(
        self,
        *,
        status: str | None = None,
        session_id: str | None = None,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        """Filtered group query for TUI screens. Returns groups with nested legs."""
        clauses: list[str] = ["1=1"]
        params: list[Any] = []
        if status:
            clauses.append("g.status = ?")
            params.append(status)
        if session_id:
            clauses.append("g.session_id = ?")
            params.append(session_id)
        where = " AND ".join(clauses)
        groups = self.query(
            f"""SELECT g.* FROM recommendation_groups g
                WHERE {where} ORDER BY g.created_at DESC LIMIT ?""",
            (*params, limit),
        )
        return self._attach_legs(groups)

    def get_trades(
        self,
        *,
        session_id: str | None = None,
        exchange: str | None = None,
        status: str | None = None,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        """Filtered trade query for TUI screens."""
        clauses, params = ["1=1"], []
        if session_id:
            clauses.append("session_id = ?")
            params.append(session_id)
        if exchange:
            clauses.append("exchange = ?")
            params.append(exchange)
        if status:
            clauses.append("status = ?")
            params.append(status)
        where = " AND ".join(clauses)
        return self.query(
            f"""SELECT * FROM trades WHERE {where}
                ORDER BY timestamp DESC LIMIT ?""",
            (*params, limit),
        )

    def get_sessions(self, limit: int = 20) -> list[dict[str, Any]]:
        """Session listing for history screen."""
        return self.query(
            """SELECT id, started_at, ended_at, summary,
                      trades_placed, recommendations_made, pnl_usd
               FROM sessions ORDER BY started_at DESC LIMIT ?""",
            (limit,),
        )

    def get_signals(
        self,
        *,
        status: str | None = None,
        scan_type: str | None = None,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        """Filtered signal query for TUI screen."""
        clauses, params = ["1=1"], []
        if status:
            clauses.append("status = ?")
            params.append(status)
        if scan_type:
            clauses.append("scan_type = ?")
            params.append(scan_type)
        where = " AND ".join(clauses)
        return self.query(
            f"""SELECT * FROM signals WHERE {where}
                ORDER BY signal_strength DESC LIMIT ?""",
            (*params, limit),
        )

    def update_trade_status(
        self,
        trade_id: int,
        status: str,
        result_json: str | None = None,
    ) -> None:
        """Update trade status after order fills/cancels."""
        self.execute(
            "UPDATE trades SET status = ?, result_json = COALESCE(?, result_json) WHERE id = ?",
            (status, result_json, trade_id),
        )

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
