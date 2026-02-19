"""Fresh DuckDB schema — all tables, sequences, and constraints.

Replaces SQLite migrations 0001-0006. Creates all 8 tables with
DuckDB-compatible DDL (sequences for auto-increment PKs, UniqueConstraint
on kalshi_daily for ON CONFLICT support).

Revision ID: 0007
Revises: None (fresh start for DuckDB)
"""

import sqlalchemy as sa
from alembic import op

revision = "0007"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── Sequences ────────────────────────────────────────────
    op.execute("CREATE SEQUENCE IF NOT EXISTS market_snapshot_id_seq")
    op.execute("CREATE SEQUENCE IF NOT EXISTS trade_id_seq")
    op.execute("CREATE SEQUENCE IF NOT EXISTS rec_group_id_seq")
    op.execute("CREATE SEQUENCE IF NOT EXISTS rec_leg_id_seq")
    op.execute("CREATE SEQUENCE IF NOT EXISTS kalshi_daily_id_seq")

    # ── Sessions ─────────────────────────────────────────────
    op.create_table(
        "sessions",
        sa.Column("id", sa.Text, primary_key=True),
        sa.Column("started_at", sa.Text, nullable=False),
    )

    # ── Events ───────────────────────────────────────────────
    op.create_table(
        "events",
        sa.Column("event_ticker", sa.Text, primary_key=True),
        sa.Column("exchange", sa.Text, primary_key=True, server_default="kalshi"),
        sa.Column("series_ticker", sa.Text),
        sa.Column("title", sa.Text),
        sa.Column("category", sa.Text),
        sa.Column("mutually_exclusive", sa.Integer),
        sa.Column("last_updated", sa.Text),
        sa.Column("markets_json", sa.Text),
    )

    # ── Market Snapshots ─────────────────────────────────────
    op.create_table(
        "market_snapshots",
        sa.Column(
            "id",
            sa.Integer,
            primary_key=True,
            server_default=sa.text("nextval('market_snapshot_id_seq')"),
        ),
        sa.Column("captured_at", sa.Text, nullable=False),
        sa.Column("source", sa.Text, nullable=False, server_default="collector"),
        sa.Column("exchange", sa.Text, nullable=False, server_default="kalshi"),
        sa.Column("ticker", sa.Text, nullable=False),
        sa.Column("event_ticker", sa.Text),
        sa.Column("series_ticker", sa.Text),
        sa.Column("title", sa.Text),
        sa.Column("category", sa.Text),
        sa.Column("status", sa.Text),
        sa.Column("yes_bid", sa.Integer),
        sa.Column("yes_ask", sa.Integer),
        sa.Column("no_bid", sa.Integer),
        sa.Column("no_ask", sa.Integer),
        sa.Column("last_price", sa.Integer),
        sa.Column("volume", sa.Integer),
        sa.Column("volume_24h", sa.Integer),
        sa.Column("open_interest", sa.Integer),
        sa.Column("spread_cents", sa.Integer),
        sa.Column("mid_price_cents", sa.Integer),
        sa.Column("implied_probability", sa.Float),
        sa.Column("days_to_expiration", sa.Float),
        sa.Column("close_time", sa.Text),
        sa.Column("settlement_value", sa.Integer),
        sa.Column("markets_in_event", sa.Integer),
        sa.Column("raw_json", sa.Text),
    )
    op.create_index("idx_snapshots_ticker_time", "market_snapshots", ["ticker", "captured_at"])
    op.create_index("idx_snapshots_series", "market_snapshots", ["series_ticker"])
    op.create_index("idx_snapshots_category", "market_snapshots", ["category"])
    op.create_index(
        "idx_snapshots_latest", "market_snapshots", ["status", "exchange", "ticker", "captured_at"]
    )

    # ── Recommendation Groups ────────────────────────────────
    # NOTE: DuckDB has limited FK support (can't UPDATE parent rows when
    # children exist), so FK constraints are omitted. Referential integrity
    # is enforced at the application/ORM layer.
    op.create_table(
        "recommendation_groups",
        sa.Column(
            "id",
            sa.Integer,
            primary_key=True,
            server_default=sa.text("nextval('rec_group_id_seq')"),
        ),
        sa.Column("session_id", sa.Text, nullable=False),
        sa.Column("created_at", sa.Text, nullable=False),
        sa.Column("thesis", sa.Text),
        sa.Column("equivalence_notes", sa.Text),
        sa.Column("estimated_edge_pct", sa.Float),
        sa.Column("status", sa.Text, server_default="pending"),
        sa.Column("expires_at", sa.Text),
        sa.Column("reviewed_at", sa.Text),
        sa.Column("executed_at", sa.Text),
        sa.Column("total_exposure_usd", sa.Float),
        sa.Column("computed_edge_pct", sa.Float),
        sa.Column("computed_fees_usd", sa.Float),
        sa.Column("strategy", sa.Text, server_default="manual"),
        sa.Column("hypothetical_pnl_usd", sa.Float),
    )
    op.create_index("idx_group_status", "recommendation_groups", ["status"])
    op.create_index("idx_rec_session", "recommendation_groups", ["session_id"])
    op.create_index("idx_group_created_at", "recommendation_groups", ["created_at"])

    # ── Recommendation Legs ──────────────────────────────────
    op.create_table(
        "recommendation_legs",
        sa.Column(
            "id", sa.Integer, primary_key=True, server_default=sa.text("nextval('rec_leg_id_seq')")
        ),
        sa.Column("group_id", sa.Integer, nullable=False),
        sa.Column("leg_index", sa.Integer, server_default="0"),
        sa.Column("exchange", sa.Text, nullable=False),
        sa.Column("market_id", sa.Text, nullable=False),
        sa.Column("market_title", sa.Text),
        sa.Column("action", sa.Text),
        sa.Column("side", sa.Text),
        sa.Column("quantity", sa.Integer),
        sa.Column("price_cents", sa.Integer),
        sa.Column("order_type", sa.Text, server_default="limit"),
        sa.Column("status", sa.Text, server_default="pending"),
        sa.Column("order_id", sa.Text),
        sa.Column("executed_at", sa.Text),
        sa.Column("is_maker", sa.Boolean),
        sa.Column("fill_price_cents", sa.Integer),
        sa.Column("fill_quantity", sa.Integer),
        sa.Column("orderbook_snapshot_json", sa.Text),
        sa.Column("settlement_value", sa.Integer),
        sa.Column("settled_at", sa.Text),
    )
    op.create_index("idx_leg_group", "recommendation_legs", ["group_id"])

    # ── Trades ───────────────────────────────────────────────
    op.create_table(
        "trades",
        sa.Column(
            "id", sa.Integer, primary_key=True, server_default=sa.text("nextval('trade_id_seq')")
        ),
        sa.Column("session_id", sa.Text, nullable=False),
        sa.Column("leg_id", sa.Integer),
        sa.Column("exchange", sa.Text, nullable=False),
        sa.Column("timestamp", sa.Text, nullable=False),
        sa.Column("ticker", sa.Text, nullable=False),
        sa.Column("action", sa.Text, nullable=False),
        sa.Column("side", sa.Text, nullable=False),
        sa.Column("quantity", sa.Integer, nullable=False),
        sa.Column("price_cents", sa.Integer),
        sa.Column("order_type", sa.Text),
        sa.Column("order_id", sa.Text),
        sa.Column("status", sa.Text),
        sa.Column("result_json", sa.Text),
    )
    op.create_index("idx_trades_ticker", "trades", ["ticker"])
    op.create_index("idx_trades_session", "trades", ["session_id"])
    op.create_index("idx_trades_status", "trades", ["status"])

    # ── Kalshi Daily ─────────────────────────────────────────
    op.create_table(
        "kalshi_daily",
        sa.Column(
            "id",
            sa.Integer,
            primary_key=True,
            server_default=sa.text("nextval('kalshi_daily_id_seq')"),
        ),
        sa.Column("date", sa.Text, nullable=False),
        sa.Column("ticker_name", sa.Text, nullable=False),
        sa.Column("report_ticker", sa.Text, nullable=False),
        sa.Column("payout_type", sa.Text),
        sa.Column("open_interest", sa.Integer),
        sa.Column("daily_volume", sa.Integer),
        sa.Column("block_volume", sa.Integer),
        sa.Column("high", sa.Integer),
        sa.Column("low", sa.Integer),
        sa.Column("status", sa.Text),
        sa.UniqueConstraint("date", "ticker_name", name="uq_kalshi_daily_date_ticker"),
    )
    op.create_index("idx_kalshi_daily_ticker", "kalshi_daily", ["ticker_name"])
    op.create_index("idx_kalshi_daily_report", "kalshi_daily", ["report_ticker"])

    # ── Kalshi Market Metadata ───────────────────────────────
    op.create_table(
        "kalshi_market_meta",
        sa.Column("ticker", sa.Text, primary_key=True),
        sa.Column("event_ticker", sa.Text),
        sa.Column("series_ticker", sa.Text),
        sa.Column("title", sa.Text),
        sa.Column("category", sa.Text),
        sa.Column("first_seen", sa.Text),
        sa.Column("last_seen", sa.Text),
    )
    op.create_index("idx_meta_series", "kalshi_market_meta", ["series_ticker"])
    op.create_index("idx_meta_category", "kalshi_market_meta", ["category"])


def downgrade() -> None:
    op.drop_table("trades")
    op.drop_table("recommendation_legs")
    op.drop_table("recommendation_groups")
    op.drop_table("market_snapshots")
    op.drop_table("kalshi_market_meta")
    op.drop_table("kalshi_daily")
    op.drop_table("events")
    op.drop_table("sessions")
    op.execute("DROP SEQUENCE IF EXISTS market_snapshot_id_seq")
    op.execute("DROP SEQUENCE IF EXISTS trade_id_seq")
    op.execute("DROP SEQUENCE IF EXISTS rec_group_id_seq")
    op.execute("DROP SEQUENCE IF EXISTS rec_leg_id_seq")
    op.execute("DROP SEQUENCE IF EXISTS kalshi_daily_id_seq")
