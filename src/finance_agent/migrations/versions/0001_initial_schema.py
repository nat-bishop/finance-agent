"""Initial schema from ORM models.

Revision ID: 0001
Revises: None
"""

import sqlalchemy as sa
from alembic import op

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "sessions",
        sa.Column("id", sa.Text(), nullable=False),
        sa.Column("started_at", sa.Text(), nullable=False),
        sa.Column("ended_at", sa.Text(), nullable=True),
        sa.Column("summary", sa.Text(), nullable=True),
        sa.Column("trades_placed", sa.Integer(), server_default="0", nullable=False),
        sa.Column("recommendations_made", sa.Integer(), server_default="0", nullable=False),
        sa.Column("pnl_usd", sa.Float(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_table(
        "market_snapshots",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("captured_at", sa.Text(), nullable=False),
        sa.Column("source", sa.Text(), server_default="collector", nullable=False),
        sa.Column("exchange", sa.Text(), server_default="kalshi", nullable=False),
        sa.Column("ticker", sa.Text(), nullable=False),
        sa.Column("event_ticker", sa.Text(), nullable=True),
        sa.Column("series_ticker", sa.Text(), nullable=True),
        sa.Column("title", sa.Text(), nullable=True),
        sa.Column("category", sa.Text(), nullable=True),
        sa.Column("status", sa.Text(), nullable=True),
        sa.Column("yes_bid", sa.Integer(), nullable=True),
        sa.Column("yes_ask", sa.Integer(), nullable=True),
        sa.Column("no_bid", sa.Integer(), nullable=True),
        sa.Column("no_ask", sa.Integer(), nullable=True),
        sa.Column("last_price", sa.Integer(), nullable=True),
        sa.Column("volume", sa.Integer(), nullable=True),
        sa.Column("volume_24h", sa.Integer(), nullable=True),
        sa.Column("open_interest", sa.Integer(), nullable=True),
        sa.Column("spread_cents", sa.Integer(), nullable=True),
        sa.Column("mid_price_cents", sa.Integer(), nullable=True),
        sa.Column("implied_probability", sa.Float(), nullable=True),
        sa.Column("days_to_expiration", sa.Float(), nullable=True),
        sa.Column("close_time", sa.Text(), nullable=True),
        sa.Column("settlement_value", sa.Integer(), nullable=True),
        sa.Column("markets_in_event", sa.Integer(), nullable=True),
        sa.Column("raw_json", sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("idx_snapshots_ticker_time", "market_snapshots", ["ticker", "captured_at"])
    op.create_index("idx_snapshots_series", "market_snapshots", ["series_ticker"])
    op.create_index("idx_snapshots_category", "market_snapshots", ["category"])
    op.create_index("idx_snapshots_exchange", "market_snapshots", ["exchange"])
    op.create_index("idx_snapshots_exchange_status", "market_snapshots", ["exchange", "status"])

    op.create_table(
        "events",
        sa.Column("event_ticker", sa.Text(), nullable=False),
        sa.Column("exchange", sa.Text(), server_default="kalshi", nullable=False),
        sa.Column("series_ticker", sa.Text(), nullable=True),
        sa.Column("title", sa.Text(), nullable=True),
        sa.Column("category", sa.Text(), nullable=True),
        sa.Column("mutually_exclusive", sa.Integer(), nullable=True),
        sa.Column("last_updated", sa.Text(), nullable=True),
        sa.Column("markets_json", sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint("event_ticker", "exchange"),
    )

    op.create_table(
        "signals",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("generated_at", sa.Text(), nullable=False),
        sa.Column("scan_type", sa.Text(), nullable=False),
        sa.Column("exchange", sa.Text(), server_default="kalshi", nullable=True),
        sa.Column("ticker", sa.Text(), nullable=False),
        sa.Column("event_ticker", sa.Text(), nullable=True),
        sa.Column("signal_strength", sa.Float(), nullable=True),
        sa.Column("estimated_edge_pct", sa.Float(), nullable=True),
        sa.Column("details_json", sa.Text(), nullable=True),
        sa.Column("status", sa.Text(), server_default="pending", nullable=True),
        sa.Column("acted_at", sa.Text(), nullable=True),
        sa.Column("session_id", sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "idx_signals_pending",
        "signals",
        ["status"],
        sqlite_where=sa.text("status = 'pending'"),
    )
    op.create_index("idx_signals_type", "signals", ["scan_type"])
    op.create_index("idx_signals_exchange", "signals", ["exchange"])

    op.create_table(
        "trades",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("session_id", sa.Text(), sa.ForeignKey("sessions.id"), nullable=False),
        sa.Column("exchange", sa.Text(), nullable=False),
        sa.Column("timestamp", sa.Text(), nullable=False),
        sa.Column("ticker", sa.Text(), nullable=False),
        sa.Column("action", sa.Text(), nullable=False),
        sa.Column("side", sa.Text(), nullable=False),
        sa.Column("count", sa.Integer(), nullable=False),
        sa.Column("price_cents", sa.Integer(), nullable=True),
        sa.Column("order_type", sa.Text(), nullable=True),
        sa.Column("order_id", sa.Text(), nullable=True),
        sa.Column("status", sa.Text(), nullable=True),
        sa.Column("result_json", sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("idx_trades_ticker", "trades", ["ticker"])
    op.create_index("idx_trades_session", "trades", ["session_id"])
    op.create_index("idx_trades_status", "trades", ["status"])

    op.create_table(
        "portfolio_snapshots",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("captured_at", sa.Text(), nullable=False),
        sa.Column("session_id", sa.Text(), nullable=True),
        sa.Column("balance_usd", sa.Float(), nullable=True),
        sa.Column("positions_json", sa.Text(), nullable=True),
        sa.Column("open_orders_json", sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_table(
        "watchlist",
        sa.Column("ticker", sa.Text(), nullable=False),
        sa.Column("exchange", sa.Text(), server_default="kalshi", nullable=False),
        sa.Column("added_at", sa.Text(), nullable=False),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("alert_condition", sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint("ticker", "exchange"),
    )

    op.create_table(
        "recommendation_groups",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("session_id", sa.Text(), nullable=False),
        sa.Column("created_at", sa.Text(), nullable=False),
        sa.Column("thesis", sa.Text(), nullable=True),
        sa.Column("equivalence_notes", sa.Text(), nullable=True),
        sa.Column("estimated_edge_pct", sa.Float(), nullable=True),
        sa.Column("signal_id", sa.Integer(), nullable=True),
        sa.Column("status", sa.Text(), server_default="pending", nullable=True),
        sa.Column("expires_at", sa.Text(), nullable=True),
        sa.Column("reviewed_at", sa.Text(), nullable=True),
        sa.Column("executed_at", sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("idx_group_status", "recommendation_groups", ["status"])
    op.create_index("idx_rec_session", "recommendation_groups", ["session_id"])

    op.create_table(
        "recommendation_legs",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column(
            "group_id",
            sa.Integer(),
            sa.ForeignKey("recommendation_groups.id"),
            nullable=False,
        ),
        sa.Column("leg_index", sa.Integer(), server_default="0", nullable=False),
        sa.Column("exchange", sa.Text(), nullable=False),
        sa.Column("market_id", sa.Text(), nullable=False),
        sa.Column("market_title", sa.Text(), nullable=True),
        sa.Column("action", sa.Text(), nullable=False),
        sa.Column("side", sa.Text(), nullable=False),
        sa.Column("quantity", sa.Integer(), nullable=False),
        sa.Column("price_cents", sa.Integer(), nullable=False),
        sa.Column("order_type", sa.Text(), server_default="limit", nullable=True),
        sa.Column("status", sa.Text(), server_default="pending", nullable=True),
        sa.Column("order_id", sa.Text(), nullable=True),
        sa.Column("executed_at", sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("idx_leg_group", "recommendation_legs", ["group_id"])


def downgrade() -> None:
    op.drop_table("recommendation_legs")
    op.drop_table("recommendation_groups")
    op.drop_table("watchlist")
    op.drop_table("portfolio_snapshots")
    op.drop_table("trades")
    op.drop_table("signals")
    op.drop_table("events")
    op.drop_table("market_snapshots")
    op.drop_table("sessions")
