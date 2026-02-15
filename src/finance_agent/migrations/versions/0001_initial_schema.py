"""Initial schema — all tables and indexes.

Revision ID: 0001
Revises: None
"""

from alembic import op

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
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
        )
    """)

    op.execute("""
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
        )
    """)

    op.execute("""
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
        )
    """)

    op.execute("""
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
        )
    """)

    op.execute("""
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
        )
    """)

    op.execute("""
        CREATE TABLE IF NOT EXISTS portfolio_snapshots (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            captured_at TEXT NOT NULL,
            session_id TEXT,
            balance_usd REAL,
            positions_json TEXT,
            open_orders_json TEXT
        )
    """)

    op.execute("""
        CREATE TABLE IF NOT EXISTS sessions (
            id TEXT PRIMARY KEY,
            started_at TEXT NOT NULL,
            ended_at TEXT,
            profile TEXT,
            summary TEXT,
            trades_placed INTEGER DEFAULT 0,
            pnl_usd REAL
        )
    """)

    op.execute("""
        CREATE TABLE IF NOT EXISTS watchlist (
            ticker TEXT NOT NULL,
            exchange TEXT NOT NULL DEFAULT 'kalshi',
            added_at TEXT NOT NULL,
            reason TEXT,
            alert_condition TEXT,
            PRIMARY KEY (ticker, exchange)
        )
    """)

    # Indexes
    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_snapshots_ticker_time
            ON market_snapshots(ticker, captured_at)
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_snapshots_series
            ON market_snapshots(series_ticker)
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_snapshots_category
            ON market_snapshots(category)
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_snapshots_exchange
            ON market_snapshots(exchange)
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_snapshots_exchange_status
            ON market_snapshots(exchange, status)
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_signals_pending
            ON signals(status) WHERE status = 'pending'
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_signals_type
            ON signals(scan_type)
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_signals_exchange
            ON signals(exchange)
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_trades_ticker
            ON trades(ticker)
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_trades_session
            ON trades(session_id)
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_trades_status
            ON trades(status)
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_predictions_unresolved
            ON predictions(outcome) WHERE outcome IS NULL
    """)


def downgrade() -> None:
    for table in [
        "watchlist",
        "sessions",
        "portfolio_snapshots",
        "predictions",
        "trades",
        "signals",
        "events",
        "market_snapshots",
    ]:
        op.execute(f"DROP TABLE IF EXISTS {table}")
