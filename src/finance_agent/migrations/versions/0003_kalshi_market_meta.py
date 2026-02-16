"""Add kalshi_market_meta table for permanent market metadata.

Revision ID: 0003
Revises: 0002
"""

import sqlalchemy as sa
from alembic import op

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "kalshi_market_meta",
        sa.Column("ticker", sa.Text(), nullable=False),
        sa.Column("event_ticker", sa.Text(), nullable=True),
        sa.Column("series_ticker", sa.Text(), nullable=True),
        sa.Column("title", sa.Text(), nullable=True),
        sa.Column("category", sa.Text(), nullable=True),
        sa.Column("first_seen", sa.Text(), nullable=True),
        sa.Column("last_seen", sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint("ticker"),
    )
    op.create_index("idx_meta_series", "kalshi_market_meta", ["series_ticker"])
    op.create_index("idx_meta_category", "kalshi_market_meta", ["category"])


def downgrade() -> None:
    op.drop_table("kalshi_market_meta")
