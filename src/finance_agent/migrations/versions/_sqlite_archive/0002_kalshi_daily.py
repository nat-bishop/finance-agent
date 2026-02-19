"""Add kalshi_daily table for historical EOD data.

Revision ID: 0002
Revises: 0001
"""

import sqlalchemy as sa
from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "kalshi_daily",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("date", sa.Text(), nullable=False),
        sa.Column("ticker_name", sa.Text(), nullable=False),
        sa.Column("report_ticker", sa.Text(), nullable=False),
        sa.Column("payout_type", sa.Text(), nullable=True),
        sa.Column("open_interest", sa.Integer(), nullable=True),
        sa.Column("daily_volume", sa.Integer(), nullable=True),
        sa.Column("block_volume", sa.Integer(), nullable=True),
        sa.Column("high", sa.Integer(), nullable=True),
        sa.Column("low", sa.Integer(), nullable=True),
        sa.Column("status", sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "idx_kalshi_daily_unique", "kalshi_daily", ["date", "ticker_name"], unique=True
    )
    op.create_index("idx_kalshi_daily_ticker", "kalshi_daily", ["ticker_name"])
    op.create_index("idx_kalshi_daily_report", "kalshi_daily", ["report_ticker"])


def downgrade() -> None:
    op.drop_table("kalshi_daily")
